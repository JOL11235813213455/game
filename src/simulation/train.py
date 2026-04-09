"""
Training pipeline: MAPPO → ES → PPO cycles.

Uses PyTorch for training (proper backprop), exports weights to .npz
for NumPy CreatureNet runtime inference.

Usage:
    cd src
    python -m simulation.train --cycles 3 --mappo-steps 100000 --ppo-steps 100000
"""
from __future__ import annotations
import argparse
import sys
import time
import random
import numpy as np
import torch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from simulation.torch_net import TorchCreatureNet, PPO, RolloutBuffer
from simulation.arena import generate_arena
from simulation.headless import Simulation
from classes.observation import OBSERVATION_SIZE, apply_preset_mask
from classes.actions import NUM_ACTIONS
from classes.creature import NeuralBehavior, StatWeightedBehavior
from simulation.net import CreatureNet

SAVE_DIR = Path(__file__).parent.parent / 'models'
SAVE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Training Phases
# ---------------------------------------------------------------------------

def run_mappo(net: TorchCreatureNet, ppo: PPO, steps: int = 100000,
              arena_kwargs: dict = None, rollout_len: int = 2048) -> TorchCreatureNet:
    """Phase 1: Multi-agent PPO — all creatures share weights."""
    print(f'\n=== MAPPO Phase ({steps} steps) ===')
    arena_kwargs = arena_kwargs or {'cols': 20, 'rows': 20, 'num_creatures': 8}
    buffer = RolloutBuffer()

    episode_rewards = []
    arena = generate_arena(**arena_kwargs)
    sim = Simulation(arena)

    total_reward = 0.0
    ep_steps = 0

    for step in range(steps):
        # Each creature acts using the shared net
        for c in sim.creatures:
            if not c.is_alive:
                continue

            from classes.observation import build_observation, make_snapshot
            obs = build_observation(c, sim.cols, sim.rows,
                                    world_data=sim.world_data)
            if c.observation_mask:
                apply_preset_mask(obs, c.observation_mask)

            obs_arr = np.array(obs, dtype=np.float32)
            action, log_prob, value = net.get_action(obs_arr)

            # Dispatch action
            from classes.actions import dispatch
            from classes.world_object import WorldObject
            from classes.creature import Creature
            target = None
            for obj in WorldObject.on_map(c.current_map):
                if isinstance(obj, Creature) and obj is not c and obj.is_alive and c.can_see(obj):
                    target = obj
                    break

            dispatch(c, action, {'cols': sim.cols, 'rows': sim.rows,
                                 'target': target, 'now': sim.now})

        # Advance simulation
        sim.now += sim.tick_ms
        sim.step_count += 1
        for c in sim.creatures:
            if c.is_alive:
                c.process_ticks(sim.now)

        # Collect rewards and store experience
        from classes.reward import compute_reward, make_reward_snapshot
        from classes.temporal import make_history_snapshot

        for c in sim.creatures:
            if not c.is_alive:
                continue

            obs = build_observation(c, sim.cols, sim.rows,
                                    world_data=sim.world_data)
            if c.observation_mask:
                apply_preset_mask(obs, c.observation_mask)
            obs_arr = np.array(obs, dtype=np.float32)

            action, log_prob, value = net.get_action(obs_arr)

            prev_rew = sim._reward_snapshots.get(c.uid)
            curr_rew = make_reward_snapshot(c)
            reward = compute_reward(c, prev_rew, curr_rew) if prev_rew else 0.0
            sim._reward_snapshots[c.uid] = curr_rew

            if hasattr(c, '_history'):
                c._history.append(make_history_snapshot(c))

            buffer.store(obs_arr, action, reward, value, log_prob,
                         not c.is_alive)
            total_reward += reward
            ep_steps += 1

        # PPO update every rollout_len steps
        if len(buffer) >= rollout_len:
            info = ppo.update(*buffer.get())
            buffer.clear()

        # Reset episode periodically
        if step % 5000 == 4999 or sim.alive_count <= 1:
            avg = total_reward / max(1, ep_steps)
            episode_rewards.append(avg)
            total_reward = 0.0
            ep_steps = 0
            arena = generate_arena(**arena_kwargs)
            sim = Simulation(arena)

        if step % 10000 == 9999:
            avg = np.mean(episode_rewards[-10:]) if episode_rewards else 0
            print(f'  Step {step+1}: avg_reward={avg:.4f}, alive={sim.alive_count}')

    print(f'  MAPPO complete. Episodes: {len(episode_rewards)}')
    return net


def run_es(net: TorchCreatureNet, generations: int = 50,
           variants: int = 50, steps_per_variant: int = 2000,
           noise_scale: float = 0.02, arena_kwargs: dict = None) -> TorchCreatureNet:
    """Phase 2: Evolutionary Strategies — diversify weights."""
    print(f'\n=== ES Phase ({generations} gens × {variants} variants) ===')
    arena_kwargs = arena_kwargs or {'cols': 15, 'rows': 15, 'num_creatures': 6}

    # Flatten weights for ES
    base_params = torch.nn.utils.parameters_to_vector(net.parameters()).detach().clone()
    param_size = base_params.shape[0]

    for gen in range(generations):
        noises = []
        rewards = []

        for v in range(variants):
            noise = torch.randn(param_size) * noise_scale
            noises.append(noise)

            # Apply noise
            torch.nn.utils.vector_to_parameters(base_params + noise, net.parameters())

            # Evaluate — use NumPy inference for speed
            tmp_path = SAVE_DIR / '_es_tmp.npz'
            net.export_to_numpy(tmp_path)
            np_net = CreatureNet()
            np_net.load(tmp_path)

            arena = generate_arena(**arena_kwargs)
            sim = Simulation(arena)
            total_r = 0.0
            for _ in range(steps_per_variant):
                results = sim.step()
                total_r += sum(r['reward'] for r in results if r['alive'])
                if sim.alive_count <= 1:
                    break
            rewards.append(total_r)

        rewards = np.array(rewards)
        order = np.argsort(rewards)[::-1]
        top_n = max(1, variants // 5)

        # Weighted update from top performers
        update = torch.zeros(param_size)
        for idx in order[:top_n]:
            update += noises[idx] * (rewards[idx] - rewards.mean()) / (rewards.std() + 1e-8)
        update /= top_n

        base_params += 0.02 * update
        torch.nn.utils.vector_to_parameters(base_params, net.parameters())

        if gen % 10 == 9:
            avg_top = np.mean(rewards[order[:top_n]])
            avg_all = np.mean(rewards)
            print(f'  Gen {gen+1}: top_20%={avg_top:.1f}, avg={avg_all:.1f}')

    # Cleanup
    tmp_path = SAVE_DIR / '_es_tmp.npz'
    if tmp_path.exists():
        tmp_path.unlink()

    print(f'  ES complete.')
    return net


def run_ppo(net: TorchCreatureNet, ppo: PPO, steps: int = 100000,
            checkpoint_dir: Path = None,
            arena_kwargs: dict = None, rollout_len: int = 2048) -> TorchCreatureNet:
    """Phase 3: Single-agent PPO against diverse opponents."""
    print(f'\n=== PPO Phase ({steps} steps) ===')
    arena_kwargs = arena_kwargs or {'cols': 20, 'rows': 20, 'num_creatures': 8}
    buffer = RolloutBuffer()

    # Load opponent checkpoints
    opponent_nets = []
    if checkpoint_dir and checkpoint_dir.exists():
        for f in sorted(checkpoint_dir.glob('*.npz')):
            if f.name.startswith('_'):
                continue
            opp = CreatureNet()
            opp.load(f)
            opponent_nets.append(opp)
    print(f'  Opponent pool: {len(opponent_nets)} checkpoints + StatWeighted')

    episode_rewards = []
    arena = generate_arena(**arena_kwargs)
    sim = Simulation(arena)

    agent = sim.creatures[0]
    agent.behavior = None

    for c in sim.creatures[1:]:
        if opponent_nets and random.random() < 0.5:
            opp = random.choice(opponent_nets)
            c.behavior = NeuralBehavior(opp, temperature=1.0)
        else:
            c.behavior = StatWeightedBehavior()
        c.register_tick('behavior', 500, c._do_behavior)

    total_reward = 0.0

    for step in range(steps):
        if agent.is_alive:
            from classes.observation import build_observation
            obs = build_observation(agent, sim.cols, sim.rows,
                                    world_data=sim.world_data)
            if agent.observation_mask:
                apply_preset_mask(obs, agent.observation_mask)
            obs_arr = np.array(obs, dtype=np.float32)
            action, log_prob, value = net.get_action(obs_arr)

            from classes.actions import dispatch
            from classes.world_object import WorldObject
            from classes.creature import Creature
            target = None
            for obj in WorldObject.on_map(agent.current_map):
                if isinstance(obj, Creature) and obj is not agent and obj.is_alive:
                    if agent.can_see(obj):
                        target = obj
                        break

            dispatch(agent, action, {'cols': sim.cols, 'rows': sim.rows,
                                     'target': target, 'now': sim.now})

        # Advance
        sim.now += sim.tick_ms
        sim.step_count += 1
        for c in sim.creatures:
            if c is not agent and c.is_alive:
                c.update(sim.now, sim.cols, sim.rows)

        # Reward
        from classes.reward import compute_reward, make_reward_snapshot
        from classes.temporal import make_history_snapshot
        prev_rew = sim._reward_snapshots.get(agent.uid)
        curr_rew = make_reward_snapshot(agent)
        reward = compute_reward(agent, prev_rew, curr_rew) if prev_rew else 0.0
        sim._reward_snapshots[agent.uid] = curr_rew
        total_reward += reward

        if hasattr(agent, '_history'):
            agent._history.append(make_history_snapshot(agent))

        if agent.is_alive:
            buffer.store(obs_arr, action, reward, value, log_prob,
                         not agent.is_alive)

        # PPO update
        if len(buffer) >= rollout_len:
            info = ppo.update(*buffer.get())
            buffer.clear()

        # Reset
        if step % 5000 == 4999 or not agent.is_alive or sim.alive_count <= 1:
            episode_rewards.append(total_reward)
            total_reward = 0.0
            arena = generate_arena(**arena_kwargs)
            sim = Simulation(arena)
            agent = sim.creatures[0]
            agent.behavior = None
            for c in sim.creatures[1:]:
                if opponent_nets and random.random() < 0.5:
                    opp = random.choice(opponent_nets)
                    c.behavior = NeuralBehavior(opp, temperature=1.0)
                else:
                    c.behavior = StatWeightedBehavior()
                c.register_tick('behavior', 500, c._do_behavior)

        if step % 10000 == 9999:
            avg = np.mean(episode_rewards[-10:]) if episode_rewards else 0
            print(f'  Step {step+1}: avg_reward={avg:.4f}')

    print(f'  PPO complete.')
    return net


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def train(cycles: int = 3, mappo_steps: int = 100000,
          es_generations: int = 50, es_variants: int = 50,
          ppo_steps: int = 100000, lr: float = 3e-4):
    """Run the full MAPPO → ES → PPO training pipeline."""
    print(f'Training pipeline: {cycles} cycles')
    print(f'  MAPPO: {mappo_steps} steps per cycle')
    print(f'  ES: {es_generations} generations × {es_variants} variants')
    print(f'  PPO: {ppo_steps} steps per cycle')
    print(f'  Observation size: {OBSERVATION_SIZE}')
    print(f'  Action space: {NUM_ACTIONS}')
    print(f'  Learning rate: {lr}')

    net = TorchCreatureNet()
    ppo = PPO(net, lr=lr)
    print(f'  Net params: {net.param_count():,}')
    print()

    for cycle in range(cycles):
        print(f'\n{"="*60}')
        print(f'CYCLE {cycle + 1} / {cycles}')
        print(f'{"="*60}')

        t0 = time.time()

        # Phase 1: MAPPO
        net = run_mappo(net, ppo, steps=mappo_steps)
        net.export_to_numpy(SAVE_DIR / f'mappo_cycle{cycle+1}.npz')
        torch.save(net.state_dict(), SAVE_DIR / f'mappo_cycle{cycle+1}.pt')

        # Phase 2: ES
        net = run_es(net, generations=es_generations, variants=es_variants)
        net.export_to_numpy(SAVE_DIR / f'es_cycle{cycle+1}.npz')
        torch.save(net.state_dict(), SAVE_DIR / f'es_cycle{cycle+1}.pt')

        # Phase 3: PPO
        ppo = PPO(net, lr=lr)  # fresh optimizer
        net = run_ppo(net, ppo, steps=ppo_steps, checkpoint_dir=SAVE_DIR)
        net.export_to_numpy(SAVE_DIR / f'ppo_cycle{cycle+1}.npz')
        torch.save(net.state_dict(), SAVE_DIR / f'ppo_cycle{cycle+1}.pt')

        elapsed = time.time() - t0
        print(f'\nCycle {cycle+1} complete in {elapsed:.0f}s')

    # Save final
    net.export_to_numpy(SAVE_DIR / 'final.npz')
    torch.save(net.state_dict(), SAVE_DIR / 'final.pt')
    print(f'\nTraining complete. Models saved to {SAVE_DIR}/')
    print(f'  NumPy weights: final.npz (load with CreatureNet)')
    print(f'  PyTorch state: final.pt (resume training)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train creature AI')
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--mappo-steps', type=int, default=100000)
    parser.add_argument('--es-generations', type=int, default=50)
    parser.add_argument('--es-variants', type=int, default=50)
    parser.add_argument('--ppo-steps', type=int, default=100000)
    parser.add_argument('--lr', type=float, default=3e-4)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    train(
        cycles=args.cycles,
        mappo_steps=args.mappo_steps,
        es_generations=args.es_generations,
        es_variants=args.es_variants,
        ppo_steps=args.ppo_steps,
        lr=args.lr,
    )
