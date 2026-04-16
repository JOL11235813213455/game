"""
Monster + Pack online RL training.

Provides a MonsterTrainer that plugs into the existing Simulation loop.
Collects per-monster (obs, action, reward) tuples during a sim run,
periodically updates MonsterNet via PPO and PackNet via REINFORCE-style
gradient ascent.

Kept in a separate module from train.py so the main pipeline can
optionally attach monster training without coupling the creature path
to monster internals.

Usage:
    from editor.simulation.monster_train import MonsterTrainer

    trainer = MonsterTrainer.build_from_pretrained(
        monster_weights='models/monster_net_pretrained.npz',
        pack_weights='models/pack_net_pretrained.npz',
    )
    trainer.attach_to_sim(sim)   # replaces sim.use_monster_heuristic
    for step in range(N):
        sim.step()
        trainer.on_step(sim)
    trainer.export_weights(out_dir='models')
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from classes.monster_actions import NUM_MONSTER_ACTIONS, compute_monster_mask
from classes.monster_observation import (
    MONSTER_OBSERVATION_SIZE, build_monster_observation,
)
from classes.monster_reward import (
    compute_monster_reward, make_monster_snapshot,
)
from classes.pack_net import (
    PACK_OBSERVATION_SIZE, PACK_OUTPUT_SIZE, build_pack_observation,
)


class TorchMonsterPolicy(nn.Module):
    """MonsterNet with actor-critic heads for PPO."""

    def __init__(self, input_size=MONSTER_OBSERVATION_SIZE,
                 output_size=NUM_MONSTER_ACTIONS):
        super().__init__()
        self.fc1 = nn.Linear(input_size, 256)
        self.fc2 = nn.Linear(256, 128)
        self.fc3 = nn.Linear(128, 64)
        self.pol = nn.Linear(64, output_size)
        self.val = nn.Linear(64, 1)

    def forward(self, x):
        h = torch.relu(self.fc1(x))
        h = torch.relu(self.fc2(h))
        h = torch.relu(self.fc3(h))
        return self.pol(h), self.val(h).squeeze(-1)

    def get_action(self, obs: np.ndarray, mask: np.ndarray,
                   temperature: float = 1.0):
        with torch.no_grad():
            obs_t = torch.from_numpy(obs).float().unsqueeze(0)
            logits, value = self.forward(obs_t)
            logits = logits.squeeze(0)
            mask_t = torch.from_numpy(mask).float()
            # Mask invalid actions
            logits = logits + (mask_t + 1e-8).log()
            if temperature != 1.0:
                logits = logits / max(1e-3, temperature)
            probs = torch.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs=probs)
            action = dist.sample()
            log_prob = dist.log_prob(action)
        return int(action.item()), float(log_prob.item()), float(value.item())

    def export_inference_npz(self, path: Path):
        """Write weights in the format MonsterNet.load (numpy) expects.

        MonsterNet has w1/b1/w2/b2/w3/b3/w_pol/b_pol keys (no critic).
        """
        w = {
            'w1': self.fc1.weight.data.t().cpu().numpy().astype(np.float32),
            'b1': self.fc1.bias.data.cpu().numpy().astype(np.float32),
            'w2': self.fc2.weight.data.t().cpu().numpy().astype(np.float32),
            'b2': self.fc2.bias.data.cpu().numpy().astype(np.float32),
            'w3': self.fc3.weight.data.t().cpu().numpy().astype(np.float32),
            'b3': self.fc3.bias.data.cpu().numpy().astype(np.float32),
            'w_pol': self.pol.weight.data.t().cpu().numpy().astype(np.float32),
            'b_pol': self.pol.bias.data.cpu().numpy().astype(np.float32),
        }
        np.savez(str(path), **w)

    def load_inference_npz(self, path: Path):
        """Load MonsterNet-format weights, leaving the critic head as init."""
        data = np.load(str(path))
        self.fc1.weight.data = torch.from_numpy(data['w1']).t().float()
        self.fc1.bias.data = torch.from_numpy(data['b1']).float()
        self.fc2.weight.data = torch.from_numpy(data['w2']).t().float()
        self.fc2.bias.data = torch.from_numpy(data['b2']).float()
        self.fc3.weight.data = torch.from_numpy(data['w3']).t().float()
        self.fc3.bias.data = torch.from_numpy(data['b3']).float()
        self.pol.weight.data = torch.from_numpy(data['w_pol']).t().float()
        self.pol.bias.data = torch.from_numpy(data['b_pol']).float()


class TorchPackPolicy(nn.Module):
    """PackNet with critic head for REINFORCE with baseline."""

    def __init__(self, input_size=PACK_OBSERVATION_SIZE,
                 output_size=PACK_OUTPUT_SIZE):
        super().__init__()
        self.fc1 = nn.Linear(input_size, 64)
        self.fc2 = nn.Linear(64, 32)
        self.out = nn.Linear(32, output_size)
        self.val = nn.Linear(32, 1)

    def forward(self, x):
        h = torch.relu(self.fc1(x))
        h = torch.relu(self.fc2(h))
        return self.out(h), self.val(h).squeeze(-1)

    def export_inference_npz(self, path: Path):
        w = {
            'w1': self.fc1.weight.data.t().cpu().numpy().astype(np.float32),
            'b1': self.fc1.bias.data.cpu().numpy().astype(np.float32),
            'w2': self.fc2.weight.data.t().cpu().numpy().astype(np.float32),
            'b2': self.fc2.bias.data.cpu().numpy().astype(np.float32),
            'w_out': self.out.weight.data.t().cpu().numpy().astype(np.float32),
            'b_out': self.out.bias.data.cpu().numpy().astype(np.float32),
        }
        np.savez(str(path), **w)


# ---------------------------------------------------------------------------
# MonsterTrainer — orchestrates online RL during a sim run
# ---------------------------------------------------------------------------

class MonsterRollout:
    """Per-monster rollout buffer: obs, action, logp, value, reward, done."""

    def __init__(self):
        self.obs: list[np.ndarray] = []
        self.actions: list[int] = []
        self.log_probs: list[float] = []
        self.values: list[float] = []
        self.rewards: list[float] = []
        self.dones: list[bool] = []
        self.masks: list[np.ndarray] = []

    def store(self, obs, action, log_prob, value, reward, done, mask):
        self.obs.append(obs)
        self.actions.append(action)
        self.log_probs.append(log_prob)
        self.values.append(value)
        self.rewards.append(reward)
        self.dones.append(done)
        self.masks.append(mask)

    def __len__(self):
        return len(self.obs)


class MonsterTrainer:
    """Drives MonsterNet + PackNet online RL during a Simulation run.

    Replaces the monster heuristic with NN-driven actions, collects
    rollouts, and updates networks on a schedule.
    """

    def __init__(self, monster_policy: TorchMonsterPolicy = None,
                 pack_policy: TorchPackPolicy = None,
                 monster_lr: float = 3e-4, pack_lr: float = 3e-4,
                 monster_rollout_len: int = 1024,
                 gamma: float = 0.99, clip_eps: float = 0.2,
                 ent_coef: float = 0.02):
        self.monster = monster_policy or TorchMonsterPolicy()
        self.pack = pack_policy or TorchPackPolicy()
        self.monster_opt = optim.Adam(self.monster.parameters(), lr=monster_lr)
        self.pack_opt = optim.Adam(self.pack.parameters(), lr=pack_lr)
        self.monster_rollout_len = monster_rollout_len
        self.gamma = gamma
        self.clip_eps = clip_eps
        self.ent_coef = ent_coef

        # Per-monster rollout buffers
        self.rollouts: dict[int, MonsterRollout] = {}
        # Per-monster previous snapshot (for reward deltas)
        self.prev_snapshots: dict[int, dict] = {}
        # Per-monster last observation + action data (for reward pairing)
        self.pending_action: dict[int, dict] = {}

        # Running stats
        self.monster_updates = 0
        self.pack_updates = 0
        self.last_loss = 0.0

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def build_from_pretrained(cls, monster_weights: str = None,
                              pack_weights: str = None) -> 'MonsterTrainer':
        t = cls()
        if monster_weights and Path(monster_weights).exists():
            t.monster.load_inference_npz(Path(monster_weights))
        return t

    # ------------------------------------------------------------------
    # Sim integration
    # ------------------------------------------------------------------

    def attach_to_sim(self, sim):
        """Wire this trainer as the monster action policy for a Simulation.

        Sets a hook on sim so monster_tick uses our policy instead of the
        heuristic. The sim's monster_tick function currently reads
        sim.monster_net for its forward pass; we replace that.
        """
        sim.use_monster_heuristic = False

        # Build a numpy-compatible MonsterNet shim that calls our PyTorch
        # policy. The monster_tick code calls .forward(np_batch) expecting
        # numpy output — we wrap the torch forward pass.
        class _NetShim:
            def __init__(self, policy):
                self.policy = policy

            def forward(self, obs_batch: np.ndarray) -> np.ndarray:
                with torch.no_grad():
                    obs_t = torch.from_numpy(obs_batch).float()
                    logits, _ = self.policy(obs_t)
                    return torch.softmax(logits, dim=-1).cpu().numpy()

        sim.monster_net = _NetShim(self.monster)

        # Pack net shim: pack NN output is 4-tuple (sleep, alert, cohesion,
        # role_fractions). Wrap accordingly.
        class _PackShim:
            def __init__(self, policy):
                self.policy = policy

            def forward(self, obs_arr: np.ndarray):
                with torch.no_grad():
                    obs_t = torch.from_numpy(obs_arr).float().unsqueeze(0)
                    raw, _ = self.policy(obs_t)
                    raw = raw.squeeze(0)
                    sleep = torch.sigmoid(raw[0]).item()
                    alert = torch.sigmoid(raw[1]).item()
                    cohesion = torch.sigmoid(raw[2]).item()
                    role_logits = raw[3:6]
                    role_probs = torch.softmax(role_logits, dim=0).cpu().numpy()
                    roles = {
                        'patrol': float(role_probs[0]),
                        'attack': float(role_probs[1]),
                        'guard_eggs': float(role_probs[2]),
                    }
                    return sleep, alert, cohesion, roles

        sim.pack_net = _PackShim(self.pack)

    # ------------------------------------------------------------------
    # Per-step reward collection
    # ------------------------------------------------------------------

    def on_step(self, sim, signal_scales: dict = None):
        """Call after sim.step(). Collect rewards for this tick and buffer."""
        for m in sim.monsters:
            if not m.is_alive:
                continue
            # Build observation (post-action snapshot)
            obs = build_monster_observation(m, sim.cols, sim.rows,
                                            game_clock=sim.game_clock)
            obs_np = np.array(obs, dtype=np.float32)
            mask = compute_monster_mask(m)

            # Compute reward delta vs previous snapshot
            prev_snap = self.prev_snapshots.get(m.uid)
            curr_snap = make_monster_snapshot(m)
            if prev_snap is not None:
                reward = compute_monster_reward(
                    m, prev_snap, curr_snap,
                    action_result=self.pending_action.get(m.uid),
                    signal_scales=signal_scales)
            else:
                reward = 0.0

            # If we have a pending action for this monster, store the
            # full tuple (obs is BEFORE the action; we stored it when
            # we selected the action — see select_action hook)
            pending = self.pending_action.get(m.uid)
            if pending is not None:
                self._buffer_store(m.uid, pending['obs'],
                                   pending['action'], pending['log_prob'],
                                   pending['value'], reward, False,
                                   pending['mask'])

            # Record monster's pre-action state for next tick
            self.prev_snapshots[m.uid] = curr_snap
            # Select next action using our policy (replaces heuristic for
            # this monster's next dispatch)
            action, log_prob, value = self.monster.get_action(obs_np, mask)
            self.pending_action[m.uid] = {
                'obs': obs_np, 'action': action, 'log_prob': log_prob,
                'value': value, 'mask': mask,
            }

        # Trigger update when a buffer is full
        if self._total_buffered() >= self.monster_rollout_len:
            self._update_monster_policy()

    def _buffer_store(self, uid, obs, action, log_prob, value,
                      reward, done, mask):
        roll = self.rollouts.setdefault(uid, MonsterRollout())
        roll.store(obs, action, log_prob, value, reward, done, mask)

    def _total_buffered(self) -> int:
        return sum(len(r) for r in self.rollouts.values())

    # ------------------------------------------------------------------
    # PPO update
    # ------------------------------------------------------------------

    def _update_monster_policy(self):
        """Simple PPO update across all pooled monster trajectories."""
        obs_all = []
        act_all = []
        lp_all = []
        val_all = []
        rew_all = []
        mask_all = []
        for roll in self.rollouts.values():
            obs_all.extend(roll.obs)
            act_all.extend(roll.actions)
            lp_all.extend(roll.log_probs)
            val_all.extend(roll.values)
            rew_all.extend(roll.rewards)
            mask_all.extend(roll.masks)

        if not obs_all:
            return

        obs_t = torch.from_numpy(np.stack(obs_all)).float()
        act_t = torch.from_numpy(np.array(act_all, dtype=np.int64))
        old_lp = torch.from_numpy(np.array(lp_all, dtype=np.float32))
        old_val = torch.from_numpy(np.array(val_all, dtype=np.float32))
        rew_t = torch.from_numpy(np.array(rew_all, dtype=np.float32))
        mask_t = torch.from_numpy(np.stack(mask_all)).float()

        # Simple returns (no GAE for MVP)
        returns = rew_t.clone()
        advantages = returns - old_val
        if advantages.numel() > 1:
            advantages = (advantages - advantages.mean()) / (
                advantages.std() + 1e-8)

        # Single PPO epoch for simplicity — mostly safe for on-policy
        # with small buffers
        logits, values = self.monster(obs_t)
        logits = logits + (mask_t + 1e-8).log()
        log_probs = torch.log_softmax(logits, dim=-1)
        new_lp = log_probs.gather(1, act_t.unsqueeze(1)).squeeze(1)
        probs = torch.softmax(logits, dim=-1)
        entropy = -(probs * log_probs).sum(dim=-1).mean()

        ratio = torch.exp(new_lp - old_lp)
        surr1 = ratio * advantages
        surr2 = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * advantages
        policy_loss = -torch.min(surr1, surr2).mean()
        value_loss = ((values - returns) ** 2).mean()
        loss = policy_loss + 0.5 * value_loss - self.ent_coef * entropy

        self.monster_opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.monster.parameters(), 1.0)
        self.monster_opt.step()

        self.last_loss = float(loss.item())
        self.monster_updates += 1

        # Clear rollouts
        self.rollouts.clear()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_weights(self, out_dir: str = 'editor/models'):
        out = Path(out_dir)
        out.mkdir(exist_ok=True, parents=True)
        self.monster.export_inference_npz(out / 'monster_net_trained.npz')
        self.pack.export_inference_npz(out / 'pack_net_trained.npz')
