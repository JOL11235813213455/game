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

_EDITOR_DIR = Path(__file__).parent.parent
_SRC_DIR = _EDITOR_DIR.parent / 'src'
sys.path.insert(0, str(_SRC_DIR))
sys.path.insert(0, str(_EDITOR_DIR))

from editor.simulation.torch_net import TorchCreatureNet, PPO, RolloutBuffer
from editor.simulation.arena import generate_arena
from editor.simulation.headless import Simulation
from classes.observation import OBSERVATION_SIZE, apply_preset_mask
from classes.actions import NUM_ACTIONS
from classes.creature import NeuralBehavior, StatWeightedBehavior
from editor.simulation.net import CreatureNet

SAVE_DIR = Path(__file__).parent.parent / 'models'
SAVE_DIR.mkdir(exist_ok=True)

LOG_DIR = Path(__file__).parent.parent / 'runs'
LOG_DIR.mkdir(exist_ok=True)

# TensorBoard writer — initialized in train()
_writer = None

def _log(tag: str, value: float, step: int):
    """Log a scalar to TensorBoard if writer is available."""
    if _writer is not None:
        _writer.add_scalar(tag, value, step)


# ---------------------------------------------------------------------------
# Training Phases
# ---------------------------------------------------------------------------

def run_mappo(net: TorchCreatureNet, ppo: PPO, steps: int = 100000,
              arena_kwargs: dict = None, rollout_len: int = 4096) -> TorchCreatureNet:
    """Phase 1: Multi-agent PPO — all creatures share weights."""
    print(f'\n=== MAPPO Phase ({steps} steps) ===')
    arena_kwargs = arena_kwargs or {
        'cols': 25, 'rows': 25, 'num_creatures': 16,
        'mask_probability': 0.1,
        'mask_pool': ['socially_deaf', 'blind', 'deaf', 'fearless',
                      'feral', 'impulsive', 'nearsighted', 'paranoid'],
    }
    buffer = RolloutBuffer()

    episode_rewards = []
    arena = generate_arena(**arena_kwargs)
    sim = Simulation(arena)

    # Disable built-in behavior — training loop controls all actions
    for c in sim.creatures:
        c.behavior = None
        c.unregister_tick('behavior')

    total_reward = 0.0
    ep_steps = 0
    action_counts = {}  # action_id → cumulative count
    trail_actions = []  # list of (step, action_id) for trailing window
    TRAIL_WINDOW = 20   # 20 steps = 10 seconds at 500ms ticks
    step_rewards = []   # recent step rewards for rolling avg

    from collections import deque
    from classes.observation import build_observation, make_snapshot
    from classes.actions import dispatch, Action
    from classes.world_object import WorldObject
    from classes.creature import Creature
    from classes.reward import compute_reward, make_reward_snapshot
    from classes.temporal import make_history_snapshot

    for step in range(steps):
        # Store per-creature action data for this tick
        tick_data = {}  # uid → (obs_arr, action, log_prob, value)

        # Each creature acts using the shared net
        for c in sim.creatures:
            if not c.is_alive:
                continue

            obs = build_observation(c, sim.cols, sim.rows,
                                    world_data=sim.world_data)
            if c.observation_mask:
                apply_preset_mask(obs, c.observation_mask)

            obs_arr = np.array(obs, dtype=np.float32)
            action, log_prob, value = net.get_action(obs_arr)

            # Store for later collection
            tick_data[c.uid] = (obs_arr, action, log_prob, value)

            # Dispatch action
            target = None
            for obj in WorldObject.on_map(c.current_map):
                if isinstance(obj, Creature) and obj is not c and obj.is_alive and c.can_see(obj):
                    target = obj
                    break

            dispatch(c, action, {'cols': sim.cols, 'rows': sim.rows,
                                 'target': target, 'now': sim.now})
            action_counts[action] = action_counts.get(action, 0) + 1
            trail_actions.append((step, action))

        # Trim trailing window
        cutoff = step - TRAIL_WINDOW
        while trail_actions and trail_actions[0][0] < cutoff:
            trail_actions.pop(0)

        # Advance simulation
        sim.now += sim.tick_ms
        sim.step_count += 1
        for c in sim.creatures:
            if c.is_alive:
                c.process_ticks(sim.now)

        # Collect rewards using STORED action data
        for c in sim.creatures:
            if c.uid not in tick_data:
                continue

            obs_arr, action, log_prob, value = tick_data[c.uid]

            prev_rew = sim._reward_snapshots.get(c.uid)
            curr_rew = make_reward_snapshot(c)
            reward = compute_reward(c, prev_rew, curr_rew) if prev_rew else 0.0
            sim._reward_snapshots[c.uid] = curr_rew

            if hasattr(c, '_history'):
                c._history.append(make_history_snapshot(c))

            buffer.store(obs_arr, action, reward, value, log_prob,
                         not c.is_alive)
            total_reward += reward
            step_rewards.append(reward)
            if len(step_rewards) > 500:
                step_rewards = step_rewards[-500:]
            ep_steps += 1

        # PPO update every rollout_len steps
        if len(buffer) >= rollout_len:
            info = ppo.update(*buffer.get())
            buffer.clear()
            _log('mappo/policy_loss', info['policy_loss'], step)
            _log('mappo/value_loss', info['value_loss'], step)
            _log('mappo/entropy', info['entropy'], step)

        # Write state for live viewer (every 10 steps to avoid IO spam)
        if step % 10 == 0:
            from editor.simulation.train_state import write_state
            # Build trailing window counts
            trail_counts = {}
            for _, aid in trail_actions:
                trail_counts[aid] = trail_counts.get(aid, 0) + 1
            # Merge all action ids from both dicts, sort by cumulative
            all_aids = set(action_counts) | set(trail_counts)
            ranked = sorted(all_aids, key=lambda a: -action_counts.get(a, 0))[:10]
            top_action_stats = []
            for aid in ranked:
                try:
                    name = Action(aid).name.lower()
                except ValueError:
                    name = f'act_{aid}'
                top_action_stats.append((name, trail_counts.get(aid, 0),
                                         action_counts.get(aid, 0)))
            avg_rew = sum(step_rewards) / max(1, len(step_rewards))
            viewer_info = {
                'avg_reward': round(avg_rew, 4),
                'total_reward': round(total_reward, 2),
                'ep_steps': ep_steps,
                'top_actions': top_action_stats,
            }
            write_state(sim, phase='MAPPO', step=step, info=viewer_info)

        # Random mask injection: occasionally swap a creature's mask mid-episode
        # This trains robustness to sudden sensory changes
        if step % 500 == 0:
            mask_pool = arena_kwargs.get('mask_pool', [])
            if mask_pool:
                for c in sim.creatures:
                    if c.is_alive and random.random() < 0.02:
                        c.observation_mask = random.choice(mask_pool + [None, None, None])
                        # None = remove mask (3/N+3 chance of being normal)

        # Reset episode periodically
        if step % 5000 == 4999 or sim.alive_count <= 1:
            avg = total_reward / max(1, ep_steps)
            episode_rewards.append(avg)
            _log('mappo/episode_reward', avg, step)
            _log('mappo/alive_count', sim.alive_count, step)
            total_reward = 0.0
            ep_steps = 0
            arena = generate_arena(**arena_kwargs)
            sim = Simulation(arena)
            for c in sim.creatures:
                c.behavior = None
                c.unregister_tick('behavior')

        if step % 10000 == 9999:
            avg = np.mean(episode_rewards[-10:]) if episode_rewards else 0
            print(f'  Step {step+1}: avg_reward={avg:.6f}, alive={sim.alive_count}')

    print(f'  MAPPO complete. Episodes: {len(episode_rewards)}')
    return net


def run_es(net: TorchCreatureNet, generations: int = 50,
           variants: int = 50, steps_per_variant: int = 2000,
           noise_scale: float = 0.02, arena_kwargs: dict = None) -> TorchCreatureNet:
    """Phase 2: Evolutionary Strategies — diversify weights."""
    print(f'\n=== ES Phase ({generations} gens × {variants} variants) ===')
    arena_kwargs = arena_kwargs or {
        'cols': 15, 'rows': 15, 'num_creatures': 10,
        'mask_probability': 0.15,
        'mask_pool': ['socially_deaf', 'blind', 'deaf', 'fearless',
                      'feral', 'impulsive', 'nearsighted', 'paranoid',
                      'amnesiac', 'greedy', 'zealot'],
    }

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

        # Write ES progress for live viewer
        from editor.simulation.train_state import write_es_state
        rewards_arr_tmp = np.array(rewards)
        write_es_state(
            generation=gen, total_generations=generations,
            variant=len(rewards), total_variants=variants,
            best_reward=float(np.max(rewards_arr_tmp)) if rewards else 0.0,
            avg_reward=float(np.mean(rewards_arr_tmp)) if rewards else 0.0,
        )

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
            _log('es/top_20_reward', avg_top, gen)
            _log('es/avg_reward', avg_all, gen)

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
    arena_kwargs = arena_kwargs or {
        'cols': 25, 'rows': 25, 'num_creatures': 16,
        'mask_probability': 0.1,
        'mask_pool': ['socially_deaf', 'blind', 'deaf', 'fearless',
                      'feral', 'impulsive', 'nearsighted', 'paranoid'],
    }
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
    ppo_action_counts = {}
    ppo_trail_actions = []
    PPO_TRAIL_WINDOW = 20
    ppo_step_rewards = []

    for step in range(steps):
        if agent.is_alive:
            from classes.observation import build_observation
            obs = build_observation(agent, sim.cols, sim.rows,
                                    world_data=sim.world_data)
            if agent.observation_mask:
                apply_preset_mask(obs, agent.observation_mask)
            obs_arr = np.array(obs, dtype=np.float32)
            action, log_prob, value = net.get_action(obs_arr)

            from classes.actions import dispatch, Action as ActionEnum
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
            ppo_action_counts[action] = ppo_action_counts.get(action, 0) + 1
            ppo_trail_actions.append((step, action))

        # Trim trailing window
        cutoff = step - PPO_TRAIL_WINDOW
        while ppo_trail_actions and ppo_trail_actions[0][0] < cutoff:
            ppo_trail_actions.pop(0)

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
        ppo_step_rewards.append(reward)
        if len(ppo_step_rewards) > 500:
            ppo_step_rewards = ppo_step_rewards[-500:]

        if hasattr(agent, '_history'):
            agent._history.append(make_history_snapshot(agent))

        if agent.is_alive:
            buffer.store(obs_arr, action, reward, value, log_prob,
                         not agent.is_alive)

        # PPO update
        if len(buffer) >= rollout_len:
            info = ppo.update(*buffer.get())
            buffer.clear()
            _log('ppo/policy_loss', info['policy_loss'], step)
            _log('ppo/value_loss', info['value_loss'], step)
            _log('ppo/entropy', info['entropy'], step)

        # Write state for live viewer
        if step % 10 == 0:
            from editor.simulation.train_state import write_state
            trail_counts = {}
            for _, aid in ppo_trail_actions:
                trail_counts[aid] = trail_counts.get(aid, 0) + 1
            all_aids = set(ppo_action_counts) | set(trail_counts)
            ranked = sorted(all_aids, key=lambda a: -ppo_action_counts.get(a, 0))[:10]
            top_action_stats = []
            for aid in ranked:
                try:
                    name = ActionEnum(aid).name.lower()
                except ValueError:
                    name = f'act_{aid}'
                top_action_stats.append((name, trail_counts.get(aid, 0),
                                         ppo_action_counts.get(aid, 0)))
            avg_rew = sum(ppo_step_rewards) / max(1, len(ppo_step_rewards))
            viewer_info = {
                'avg_reward': round(avg_rew, 4),
                'total_reward': round(total_reward, 2),
                'ep_steps': len(ppo_step_rewards),
                'top_actions': top_action_stats,
            }
            write_state(sim, phase='PPO', step=step, info=viewer_info)

        # Reset
        if step % 5000 == 4999 or not agent.is_alive or sim.alive_count <= 1:
            episode_rewards.append(total_reward)
            _log('ppo/episode_reward', total_reward, step)
            _log('ppo/alive_count', sim.alive_count, step)
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
          es_steps: int = 500,
          ppo_steps: int = 100000, lr: float = 3e-4,
          run_name: str = None, resume_from: str = None,
          arena_cols: int = 25, arena_rows: int = 25,
          num_creatures: int = 16):
    """Run the full MAPPO → ES → PPO training pipeline."""
    global _writer, SAVE_DIR
    from torch.utils.tensorboard import SummaryWriter
    if not run_name:
        run_name = f'train_{time.strftime("%Y%m%d_%H%M%S")}'
    # Save models to run-specific subfolder
    SAVE_DIR = Path(__file__).parent.parent / 'models' / run_name
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    _writer = SummaryWriter(log_dir=LOG_DIR / run_name)
    print(f'TensorBoard: tensorboard --logdir {LOG_DIR}')
    print(f'Run name: {run_name}')
    print(f'Models dir: {SAVE_DIR}')
    print(f'Training pipeline: {cycles} cycles')
    print(f'  MAPPO: {mappo_steps} steps per cycle')
    print(f'  ES: {es_generations} generations × {es_variants} variants × {es_steps} steps')
    print(f'  PPO: {ppo_steps} steps per cycle')
    print(f'  Observation size: {OBSERVATION_SIZE}')
    print(f'  Action space: {NUM_ACTIONS}')
    print(f'  Learning rate: {lr}')

    net = TorchCreatureNet()
    if resume_from:
        print(f'  Resuming from: {resume_from}')
        saved_state = torch.load(resume_from, weights_only=True)
        # Handle observation size change — pad fc1 weights if needed
        saved_w1 = saved_state.get('fc1.weight')
        curr_w1 = net.state_dict()['fc1.weight']
        if saved_w1 is not None and saved_w1.shape != curr_w1.shape:
            old_in = saved_w1.shape[1]
            new_in = curr_w1.shape[1]
            print(f'  Observation size changed: {old_in} → {new_in}, padding fc1')
            padded = torch.zeros_like(curr_w1)
            padded[:, :old_in] = saved_w1
            saved_state['fc1.weight'] = padded
        net.load_state_dict(saved_state, strict=False)
    ppo = PPO(net, lr=lr)
    print(f'  Net params: {net.param_count():,}')
    print(f'  Arena: {arena_cols}x{arena_rows}, {num_creatures} creatures')
    print()

    # Build arena kwargs used by all phases
    arena_kwargs = {
        'cols': arena_cols, 'rows': arena_rows,
        'num_creatures': num_creatures,
        'mask_probability': 0.1,
        'mask_pool': ['socially_deaf', 'blind', 'deaf', 'fearless',
                      'feral', 'impulsive', 'nearsighted', 'paranoid'],
    }
    # ES uses smaller arena and more masks by default
    es_arena_kwargs = {
        **arena_kwargs,
        'mask_probability': 0.15,
        'mask_pool': ['socially_deaf', 'blind', 'deaf', 'fearless',
                      'feral', 'impulsive', 'nearsighted', 'paranoid',
                      'amnesiac', 'greedy', 'zealot'],
    }

    for cycle in range(cycles):
        print(f'\n{"="*60}')
        print(f'CYCLE {cycle + 1} / {cycles}')
        print(f'{"="*60}')

        t0 = time.time()

        # Phase 1: MAPPO
        net = run_mappo(net, ppo, steps=mappo_steps, arena_kwargs=arena_kwargs)
        net.export_to_numpy(SAVE_DIR / f'mappo_cycle{cycle+1}.npz')
        torch.save(net.state_dict(), SAVE_DIR / f'mappo_cycle{cycle+1}.pt')

        # Phase 2: ES
        net = run_es(net, generations=es_generations, variants=es_variants,
                     steps_per_variant=es_steps, arena_kwargs=es_arena_kwargs)
        net.export_to_numpy(SAVE_DIR / f'es_cycle{cycle+1}.npz')
        torch.save(net.state_dict(), SAVE_DIR / f'es_cycle{cycle+1}.pt')

        # Phase 3: PPO
        ppo = PPO(net, lr=lr)  # fresh optimizer
        net = run_ppo(net, ppo, steps=ppo_steps, checkpoint_dir=SAVE_DIR,
                      arena_kwargs=arena_kwargs)
        net.export_to_numpy(SAVE_DIR / f'ppo_cycle{cycle+1}.npz')
        torch.save(net.state_dict(), SAVE_DIR / f'ppo_cycle{cycle+1}.pt')

        elapsed = time.time() - t0
        print(f'\nCycle {cycle+1} complete in {elapsed:.0f}s')

    # Save final
    net.export_to_numpy(SAVE_DIR / 'final.npz')
    torch.save(net.state_dict(), SAVE_DIR / 'final.pt')
    # Also save to root models/ for easy resume
    root_models = Path(__file__).parent.parent / 'models'
    net.export_to_numpy(root_models / 'final.npz')
    torch.save(net.state_dict(), root_models / 'final.pt')
    if _writer:
        _writer.close()
    # Clear live state so viewer knows training is done
    from editor.simulation.train_state import clear_state
    clear_state()
    print(f'\nTraining complete. Models saved to {SAVE_DIR}/')
    print(f'  NumPy weights: final.npz (load with CreatureNet)')
    print(f'  PyTorch state: final.pt (resume training)')
    print(f'  TensorBoard: tensorboard --logdir {LOG_DIR}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train creature AI')
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--mappo-steps', type=int, default=100000)
    parser.add_argument('--es-generations', type=int, default=50)
    parser.add_argument('--es-variants', type=int, default=50)
    parser.add_argument('--es-steps', type=int, default=500, help='Sim steps per ES variant evaluation')
    parser.add_argument('--ppo-steps', type=int, default=100000)
    parser.add_argument('--lr', type=float, default=3e-4)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--name', type=str, default=None, help='Run name for TensorBoard')
    parser.add_argument('--resume', type=str, default=None, help='Path to .pt checkpoint to resume from')
    parser.add_argument('--arena-cols', type=int, default=25, help='Arena width in tiles')
    parser.add_argument('--arena-rows', type=int, default=25, help='Arena height in tiles')
    parser.add_argument('--num-creatures', type=int, default=16, help='Creatures per arena')
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    train(
        cycles=args.cycles,
        mappo_steps=args.mappo_steps,
        es_generations=args.es_generations,
        es_variants=args.es_variants,
        es_steps=args.es_steps,
        ppo_steps=args.ppo_steps,
        lr=args.lr,
        run_name=args.name,
        resume_from=args.resume,
        arena_cols=args.arena_cols,
        arena_rows=args.arena_rows,
        num_creatures=args.num_creatures,
    )
