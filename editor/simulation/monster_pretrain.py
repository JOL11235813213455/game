"""
Supervised imitation pretraining for MonsterNet and PackNet.

Generates a rollout dataset from the heuristic policy, then trains
the corresponding PyTorch net with cross-entropy (MonsterNet) or MSE
(PackNet) loss. Exports trained weights back to the .npz format that
MonsterNet / PackNet load at runtime.

Usage:
    cd src
    python -m simulation.monster_pretrain --rollouts 50 --epochs 5

DAgger iteration (optional):
    python -m simulation.monster_pretrain --dagger-rounds 3
"""
from __future__ import annotations
import sys
from pathlib import Path
_EDITOR_DIR = Path(__file__).parent.parent
_SRC_DIR = _EDITOR_DIR.parent / 'src'
sys.path.insert(0, str(_SRC_DIR))
sys.path.insert(0, str(_EDITOR_DIR))

import argparse
import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from classes.monster_observation import MONSTER_OBSERVATION_SIZE
from classes.monster_actions import NUM_MONSTER_ACTIONS, compute_monster_mask
from classes.monster_heuristic import heuristic_monster_action, heuristic_pack_outputs
from classes.pack_net import (
    PACK_OBSERVATION_SIZE, PACK_OUTPUT_SIZE, build_pack_observation,
)
from classes.monster_observation import build_monster_observation
from classes.maps import Map, MapKey, Tile
from classes.monster import Monster
from classes.pack import Pack
from data.db import load as load_db, MONSTER_SPECIES


SAVE_DIR = _EDITOR_DIR / 'models'
SAVE_DIR.mkdir(exist_ok=True)


class TorchMonsterNet(nn.Module):
    """PyTorch twin of MonsterNet for training. Exports to numpy .npz."""

    def __init__(self, input_size=MONSTER_OBSERVATION_SIZE,
                 output_size=NUM_MONSTER_ACTIONS):
        super().__init__()
        self.fc1 = nn.Linear(input_size, 256)
        self.fc2 = nn.Linear(256, 128)
        self.fc3 = nn.Linear(128, 64)
        self.pol = nn.Linear(64, output_size)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        x = torch.relu(self.fc3(x))
        return self.pol(x)  # raw logits

    def export_npz(self, path: Path):
        """Write weights in the numpy format MonsterNet.load expects."""
        weights = {
            'w1': self.fc1.weight.data.t().cpu().numpy().astype(np.float32),
            'b1': self.fc1.bias.data.cpu().numpy().astype(np.float32),
            'w2': self.fc2.weight.data.t().cpu().numpy().astype(np.float32),
            'b2': self.fc2.bias.data.cpu().numpy().astype(np.float32),
            'w3': self.fc3.weight.data.t().cpu().numpy().astype(np.float32),
            'b3': self.fc3.bias.data.cpu().numpy().astype(np.float32),
            'w_pol': self.pol.weight.data.t().cpu().numpy().astype(np.float32),
            'b_pol': self.pol.bias.data.cpu().numpy().astype(np.float32),
        }
        np.savez(str(path), **weights)


class TorchPackNet(nn.Module):
    """PyTorch twin of PackNet."""

    def __init__(self, input_size=PACK_OBSERVATION_SIZE,
                 output_size=PACK_OUTPUT_SIZE):
        super().__init__()
        self.fc1 = nn.Linear(input_size, 64)
        self.fc2 = nn.Linear(64, 32)
        self.out = nn.Linear(32, output_size)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.out(x)  # raw — first 3 via sigmoid, last 3 via softmax

    def export_npz(self, path: Path):
        weights = {
            'w1': self.fc1.weight.data.t().cpu().numpy().astype(np.float32),
            'b1': self.fc1.bias.data.cpu().numpy().astype(np.float32),
            'w2': self.fc2.weight.data.t().cpu().numpy().astype(np.float32),
            'b2': self.fc2.bias.data.cpu().numpy().astype(np.float32),
            'w_out': self.out.weight.data.t().cpu().numpy().astype(np.float32),
            'b_out': self.out.bias.data.cpu().numpy().astype(np.float32),
        }
        np.savez(str(path), **weights)


# ---------------------------------------------------------------------------
# Rollout / dataset generation
# ---------------------------------------------------------------------------

def _build_scenario(species_list: list[str], per_species: int = 3,
                    map_size: int = 25):
    """Build a small arena with packs of the given species."""
    tiles = {MapKey(x, y, 0): Tile(walkable=True)
             for x in range(map_size) for y in range(map_size)}
    m = Map(tile_set=tiles, entrance=(0, 0), x_max=map_size, y_max=map_size)
    m.name = 'pretrain_scenario'

    monsters = []
    packs = []
    for species in species_list:
        if species not in MONSTER_SPECIES:
            continue
        center = MapKey(random.randint(5, map_size - 6),
                        random.randint(5, map_size - 6), 0)
        pack = Pack(species=species, territory_center=center, game_map=m)
        packs.append(pack)
        for i in range(per_species):
            loc = MapKey(max(0, min(map_size - 1, center.x + random.randint(-2, 2))),
                         max(0, min(map_size - 1, center.y + random.randint(-2, 2))),
                         0)
            sex = 'male' if i % 2 == 0 else 'female'
            mon = Monster(current_map=m, location=loc, species=species, sex=sex, age=20)
            pack.add_member(mon)
            monsters.append(mon)
    return m, monsters, packs


def _collect_monster_dataset(rollouts: int, steps_per_rollout: int,
                             species_list: list[str]):
    """Run heuristic rollouts and log (obs, action, mask) tuples."""
    obs_list = []
    act_list = []
    mask_list = []
    for r in range(rollouts):
        m, monsters, packs = _build_scenario(species_list)
        for step in range(steps_per_rollout):
            for mon in monsters:
                if not mon.is_alive:
                    continue
                obs = build_monster_observation(mon, 25, 25)
                mask = compute_monster_mask(mon)
                action = heuristic_monster_action(mon)
                obs_list.append(obs)
                act_list.append(action)
                mask_list.append(mask)
        # Clean up world between rollouts
        for mon in monsters:
            mon.current_map = None
    return (np.array(obs_list, dtype=np.float32),
            np.array(act_list, dtype=np.int64),
            np.array(mask_list, dtype=np.float32))


def _collect_pack_dataset(rollouts: int, steps_per_rollout: int,
                          species_list: list[str]):
    obs_list = []
    out_list = []
    for r in range(rollouts):
        m, monsters, packs = _build_scenario(species_list)
        for step in range(steps_per_rollout):
            for pack in packs:
                if pack.size == 0:
                    continue
                obs = build_pack_observation(pack)
                sleep, alert, cohesion, roles = heuristic_pack_outputs(pack)
                out = np.array([
                    sleep, alert, cohesion,
                    roles.get('patrol', 0), roles.get('attack', 0),
                    roles.get('guard_eggs', 0),
                ], dtype=np.float32)
                obs_list.append(obs)
                out_list.append(out)
        for mon in monsters:
            mon.current_map = None
    return (np.array(obs_list, dtype=np.float32),
            np.array(out_list, dtype=np.float32))


# ---------------------------------------------------------------------------
# Training loops
# ---------------------------------------------------------------------------

def train_monster_net(rollouts: int = 50, steps_per_rollout: int = 30,
                      epochs: int = 5, batch_size: int = 128,
                      lr: float = 1e-3, species_list: list[str] = None) -> TorchMonsterNet:
    if species_list is None:
        species_list = list(MONSTER_SPECIES.keys())
    print(f'[MonsterNet pretrain] collecting {rollouts} rollouts...')
    obs, actions, masks = _collect_monster_dataset(
        rollouts, steps_per_rollout, species_list)
    print(f'  dataset: {obs.shape[0]} samples, action dist = '
          f'{np.bincount(actions, minlength=NUM_MONSTER_ACTIONS).tolist()}')

    net = TorchMonsterNet()
    opt = optim.Adam(net.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()

    obs_t = torch.from_numpy(obs)
    act_t = torch.from_numpy(actions)
    n = len(obs_t)

    for ep in range(epochs):
        perm = torch.randperm(n)
        total_loss = 0.0
        correct = 0
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            logits = net(obs_t[idx])
            loss = loss_fn(logits, act_t[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += loss.item() * len(idx)
            correct += (logits.argmax(dim=1) == act_t[idx]).sum().item()
        print(f'  epoch {ep + 1}/{epochs}: loss={total_loss / n:.4f} '
              f'accuracy={correct / n:.2%}')

    return net


def train_pack_net(rollouts: int = 50, steps_per_rollout: int = 30,
                   epochs: int = 5, batch_size: int = 128,
                   lr: float = 1e-3, species_list: list[str] = None) -> TorchPackNet:
    if species_list is None:
        species_list = list(MONSTER_SPECIES.keys())
    print(f'[PackNet pretrain] collecting {rollouts} rollouts...')
    obs, outputs = _collect_pack_dataset(rollouts, steps_per_rollout, species_list)
    print(f'  dataset: {obs.shape[0]} samples')

    net = TorchPackNet()
    opt = optim.Adam(net.parameters(), lr=lr)
    # Split loss: MSE on sigmoids + cross-entropy on role softmax
    obs_t = torch.from_numpy(obs)
    targets_t = torch.from_numpy(outputs)
    n = len(obs_t)

    for ep in range(epochs):
        perm = torch.randperm(n)
        total_loss = 0.0
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            out = net(obs_t[idx])
            # Sigmoid losses on first 3 (sleep/alert/cohesion)
            sig_pred = torch.sigmoid(out[:, :3])
            sig_tgt = targets_t[idx, :3]
            sig_loss = torch.mean((sig_pred - sig_tgt) ** 2)
            # Role softmax cross-entropy
            role_logits = out[:, 3:]
            role_tgt = targets_t[idx, 3:]
            log_probs = torch.log_softmax(role_logits, dim=1)
            role_loss = -(role_tgt * log_probs).sum(dim=1).mean()
            loss = sig_loss + role_loss
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += loss.item() * len(idx)
        print(f'  epoch {ep + 1}/{epochs}: loss={total_loss / n:.4f}')
    return net


# ---------------------------------------------------------------------------
# DAgger iteration
# ---------------------------------------------------------------------------

def dagger_round(net: TorchMonsterNet, rounds: int,
                 rollouts: int, steps_per_rollout: int,
                 epochs: int, batch_size: int, lr: float,
                 species_list: list[str]):
    """Run DAgger rounds: roll out NN, log disagreements with heuristic, retrain."""
    print(f'[DAgger] {rounds} rounds')
    # Initial dataset
    obs_all, act_all, _ = _collect_monster_dataset(
        rollouts, steps_per_rollout, species_list)

    for rd in range(rounds):
        # Roll out current NN in simulation, log states where heuristic
        # disagrees with NN
        dis_obs = []
        dis_act = []
        for _ in range(rollouts):
            m, monsters, packs = _build_scenario(species_list)
            for step in range(steps_per_rollout):
                for mon in monsters:
                    if not mon.is_alive:
                        continue
                    obs = build_monster_observation(mon, 25, 25)
                    obs_t = torch.from_numpy(np.array(obs, dtype=np.float32))
                    with torch.no_grad():
                        logits = net(obs_t.unsqueeze(0))
                        nn_action = int(logits.argmax(dim=1).item())
                    heur_action = heuristic_monster_action(mon)
                    if nn_action != heur_action:
                        dis_obs.append(obs)
                        dis_act.append(heur_action)
            for mon in monsters:
                mon.current_map = None

        if dis_obs:
            obs_all = np.concatenate(
                [obs_all, np.array(dis_obs, dtype=np.float32)])
            act_all = np.concatenate(
                [act_all, np.array(dis_act, dtype=np.int64)])
        print(f'  round {rd + 1}: aggregated {len(dis_obs)} disagreement samples '
              f'(dataset now {len(obs_all)})')

        # Retrain on aggregated dataset
        obs_t = torch.from_numpy(obs_all)
        act_t = torch.from_numpy(act_all)
        opt = optim.Adam(net.parameters(), lr=lr)
        loss_fn = nn.CrossEntropyLoss()
        n = len(obs_t)
        for ep in range(epochs):
            perm = torch.randperm(n)
            for i in range(0, n, batch_size):
                idx = perm[i:i + batch_size]
                logits = net(obs_t[idx])
                loss = loss_fn(logits, act_t[idx])
                opt.zero_grad()
                loss.backward()
                opt.step()
    return net


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Monster/Pack imitation pretraining')
    parser.add_argument('--rollouts', type=int, default=50)
    parser.add_argument('--steps-per-rollout', type=int, default=30)
    parser.add_argument('--epochs', type=int, default=5)
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--dagger-rounds', type=int, default=0)
    parser.add_argument('--skip-pack', action='store_true')
    parser.add_argument('--skip-monster', action='store_true')
    args = parser.parse_args()

    load_db()
    random.seed(42)
    torch.manual_seed(42)

    if not args.skip_monster:
        net = train_monster_net(
            rollouts=args.rollouts,
            steps_per_rollout=args.steps_per_rollout,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
        )
        if args.dagger_rounds > 0:
            net = dagger_round(
                net, args.dagger_rounds,
                rollouts=args.rollouts // 2,
                steps_per_rollout=args.steps_per_rollout,
                epochs=args.epochs,
                batch_size=args.batch_size,
                lr=args.lr,
                species_list=list(MONSTER_SPECIES.keys()),
            )
        out_path = SAVE_DIR / 'monster_net_pretrained.npz'
        net.export_npz(out_path)
        print(f'Saved MonsterNet weights to {out_path}')

    if not args.skip_pack:
        pnet = train_pack_net(
            rollouts=args.rollouts,
            steps_per_rollout=args.steps_per_rollout,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
        )
        out_path = SAVE_DIR / 'pack_net_pretrained.npz'
        pnet.export_npz(out_path)
        print(f'Saved PackNet weights to {out_path}')


if __name__ == '__main__':
    main()
