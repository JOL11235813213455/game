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
import json
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

DB_PATH = _SRC_DIR / 'data' / 'game.db'

# TensorBoard writer — initialized in train()
_writer = None


def _load_state_into_net(net: TorchCreatureNet, saved_state: dict,
                         old_obs_schema_id: int | None = None,
                         old_act_schema_id: int | None = None) -> TorchCreatureNet:
    """Load a saved state_dict into a net, remapping by named sections.

    When schema IDs are provided, uses named section/action remapping so that
    reordered or inserted sections are correctly aligned. Falls back to
    positional padding when schema IDs are not available (backward compat).

    Handles:
    - Observation size changes (fc1 input dimension) via section remapping
    - Action count changes (policy_head output dimension) via action name remapping
    Preserves all learned weights for matched sections/actions.
    """
    curr_state = net.state_dict()

    # --- fc1 (input layer): columns = observation features ---
    saved_w1 = saved_state.get('fc1.weight')
    if saved_w1 is not None and saved_w1.shape != curr_state['fc1.weight'].shape:
        old_in = saved_w1.shape[1]
        new_in = curr_state['fc1.weight'].shape[1]
        print(f'  Observation size changed: {old_in} -> {new_in}')

        if old_obs_schema_id is not None:
            # Named section remapping
            from editor.simulation.training_db import (
                get_schema, generate_observation_schema,
            )
            old_layout, _ = get_schema('observation', old_obs_schema_id)
            new_layout = generate_observation_schema()
            old_by_name = {s['section']: s for s in old_layout}
            new_by_name = {s['section']: s for s in new_layout}

            padded = torch.zeros_like(curr_state['fc1.weight'])
            matched = []
            for name in old_by_name.keys() & new_by_name.keys():
                old_s, new_s = old_by_name[name], new_by_name[name]
                copy_size = min(old_s['size'], new_s['size'])
                padded[:, new_s['start']:new_s['start'] + copy_size] = \
                    saved_w1[:, old_s['start']:old_s['start'] + copy_size]
                matched.append(name)

            added = set(new_by_name) - set(old_by_name)
            dropped = set(old_by_name) - set(new_by_name)
            print(f'  fc1 section remap: {len(matched)} matched, '
                  f'{len(added)} new (zeroed), {len(dropped)} dropped')
            if added:
                print(f'    Added: {sorted(added)}')
            if dropped:
                print(f'    Dropped: {sorted(dropped)}')
            saved_state['fc1.weight'] = padded
        else:
            # Positional fallback (no schema available)
            print(f'  fc1: positional padding (no obs schema)')
            padded = torch.zeros_like(curr_state['fc1.weight'])
            min_in = min(old_in, new_in)
            padded[:, :min_in] = saved_w1[:, :min_in]
            saved_state['fc1.weight'] = padded

    # --- policy_head (output layer): rows = actions ---
    saved_ph = saved_state.get('policy_head.weight')
    if saved_ph is not None and saved_ph.shape != curr_state['policy_head.weight'].shape:
        old_out = saved_ph.shape[0]
        new_out = curr_state['policy_head.weight'].shape[0]
        print(f'  Action count changed: {old_out} -> {new_out}')

        if old_act_schema_id is not None:
            # Named action remapping
            from editor.simulation.training_db import (
                get_schema, generate_action_schema,
            )
            old_layout, _ = get_schema('action', old_act_schema_id)
            new_layout = generate_action_schema()
            old_by_name = {a['name']: a for a in old_layout}
            new_by_name = {a['name']: a for a in new_layout}

            padded_w = torch.zeros_like(curr_state['policy_head.weight'])
            padded_b = torch.zeros_like(curr_state['policy_head.bias'])
            saved_pb = saved_state.get('policy_head.bias')
            matched = []
            for name in old_by_name.keys() & new_by_name.keys():
                old_idx = old_by_name[name]['index']
                new_idx = new_by_name[name]['index']
                padded_w[new_idx, :] = saved_ph[old_idx, :]
                if saved_pb is not None:
                    padded_b[new_idx] = saved_pb[old_idx]
                matched.append(name)

            added = set(new_by_name) - set(old_by_name)
            dropped = set(old_by_name) - set(new_by_name)
            print(f'  policy_head action remap: {len(matched)} matched, '
                  f'{len(added)} new (zeroed), {len(dropped)} dropped')
            if added:
                print(f'    Added: {sorted(added)}')
            if dropped:
                print(f'    Dropped: {sorted(dropped)}')
            saved_state['policy_head.weight'] = padded_w
            saved_state['policy_head.bias'] = padded_b
        else:
            # Positional fallback
            print(f'  policy_head: positional padding (no act schema)')
            padded_w = torch.zeros_like(curr_state['policy_head.weight'])
            min_out = min(old_out, new_out)
            padded_w[:min_out, :] = saved_ph[:min_out, :]
            saved_state['policy_head.weight'] = padded_w
            saved_pb = saved_state.get('policy_head.bias')
            if saved_pb is not None:
                padded_b = torch.zeros_like(curr_state['policy_head.bias'])
                padded_b[:min_out] = saved_pb[:min_out]
                saved_state['policy_head.bias'] = padded_b

    net.load_state_dict(saved_state, strict=False)
    return net


def _save_model_to_db(net: TorchCreatureNet, name: str, parent_version: int | None,
                      training_params: dict, training_stats: dict,
                      training_seconds: float, notes: str = '',
                      obs_schema_id: int | None = None,
                      act_schema_id: int | None = None) -> int:
    """Save model weights + metadata to nn_models table. Returns new version number."""
    import sqlite3, json, io
    from datetime import datetime

    # Serialize state_dict to bytes
    buf = io.BytesIO()
    torch.save(net.state_dict(), buf)
    weights_blob = buf.getvalue()

    con = sqlite3.connect(DB_PATH)
    # Get next version for this name
    row = con.execute('SELECT COALESCE(MAX(version), 0) FROM nn_models WHERE name = ?',
                      (name,)).fetchone()
    version = row[0] + 1

    con.execute('''INSERT INTO nn_models
        (name, version, parent_version, weights, observation_size, num_actions,
         training_params, training_stats, training_seconds, created_at, notes,
         obs_schema_id, act_schema_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (name, version, parent_version, weights_blob,
         OBSERVATION_SIZE, NUM_ACTIONS,
         json.dumps(training_params), json.dumps(training_stats),
         training_seconds, datetime.utcnow().isoformat(sep=' ', timespec='seconds'),
         notes, obs_schema_id, act_schema_id))
    con.commit()
    con.close()
    print(f'  Saved to DB: {name} v{version}')
    return version


def _load_model_from_db(net: TorchCreatureNet, name: str,
                        version: int | None = None) -> tuple[TorchCreatureNet, dict]:
    """Load model weights from nn_models table.

    Args:
        net: target network (may have different dimensions)
        name: model lineage name
        version: specific version, or None for latest

    Returns:
        (net_with_loaded_weights, row_dict)
    """
    import sqlite3, json, io

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    if version is None:
        row = con.execute(
            'SELECT * FROM nn_models WHERE name = ? ORDER BY version DESC LIMIT 1',
            (name,)).fetchone()
    else:
        row = con.execute(
            'SELECT * FROM nn_models WHERE name = ? AND version = ?',
            (name, version)).fetchone()
    con.close()

    if row is None:
        raise ValueError(f'Model not found: {name} v{version}')

    row_dict = dict(row)
    print(f'  Loading from DB: {name} v{row_dict["version"]} '
          f'(obs={row_dict["observation_size"]}, actions={row_dict["num_actions"]})')

    buf = io.BytesIO(row_dict['weights'])
    saved_state = torch.load(buf, weights_only=True)
    net = _load_state_into_net(
        net, saved_state,
        old_obs_schema_id=row_dict.get('obs_schema_id'),
        old_act_schema_id=row_dict.get('act_schema_id'),
    )

    row_dict['training_params'] = json.loads(row_dict['training_params'])
    row_dict['training_stats'] = json.loads(row_dict['training_stats'])
    # Don't return blob in dict
    del row_dict['weights']
    return net, row_dict


def _list_models_from_db() -> list[dict]:
    """List all model versions from the DB."""
    import sqlite3, json
    if not DB_PATH.exists():
        return []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        'SELECT id, name, version, parent_version, observation_size, num_actions, '
        'training_seconds, created_at, notes FROM nn_models ORDER BY name, version'
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def _log(tag: str, value: float, step: int):
    """Log a scalar to TensorBoard if writer is available."""
    if _writer is not None:
        _writer.add_scalar(tag, value, step)


def _creature_final_state(c) -> dict:
    """Capture a creature's final state for analytics."""
    from classes.stats import Stat
    hp_max = max(1, c.stats.active[Stat.HP_MAX]())
    all_rels = list(c.relationships.values())
    base_stats = {}
    for st in [Stat.STR, Stat.VIT, Stat.AGL, Stat.PER, Stat.INT, Stat.CHR, Stat.LCK]:
        base_stats[st.name] = c.stats.base.get(st, 10)
    return {
        'species': c.species, 'sex': c.sex,
        'profile': '', 'mask': c.observation_mask,
        'hp_ratio': c.stats.active[Stat.HP_CURR]() / hp_max,
        'gold': c.gold,
        'items': len(c.inventory.items),
        'equipment': len(c.equipment),
        'allies': sum(1 for r in all_rels if r[0] > 5),
        'enemies': sum(1 for r in all_rels if r[0] < -5),
        'kills': getattr(c, '_kills', 0),
        'tiles_explored': getattr(c, '_tiles_explored', 0),
        'creatures_met': len(c.relationships),
        'base_stats': base_stats,
    }


# ---------------------------------------------------------------------------
# Training Phases
# ---------------------------------------------------------------------------

def run_mappo(net: TorchCreatureNet, ppo: PPO, steps: int = 100000,
              arena_kwargs: dict = None, rollout_len: int = 4096,
              sink=None, goal_net=None, goal_ppo=None) -> TorchCreatureNet:
    """Phase 1: Multi-agent PPO — all creatures share weights.

    If goal_net is provided, runs hierarchical goal selection every
    GOAL_INTERVAL steps for each creature.
    """
    print(f'\n=== MAPPO Phase ({steps} steps) ===')
    arena_kwargs = arena_kwargs or {
        'cols': 25, 'rows': 25, 'num_creatures': 16,
        'mask_probability': 0.1,
        'mask_pool': ['socially_deaf', 'blind', 'deaf', 'fearless',
                      'feral', 'impulsive', 'nearsighted', 'paranoid'],
    }
    buffer = RolloutBuffer()
    goal_buffer = RolloutBuffer() if goal_net else None
    GOAL_INTERVAL = 50  # re-evaluate goals every 50 action steps

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
    # Goal tracking per creature: {uid: (goal_obs, goal_idx, log_prob, value, cumul_reward)}
    _goal_states = {}

    from collections import deque
    from classes.observation import build_observation, make_snapshot
    from classes.actions import dispatch, Action, TILE_PURPOSES
    from classes.world_object import WorldObject
    from classes.creature import Creature
    from classes.reward import compute_reward, make_reward_snapshot
    from classes.temporal import make_history_snapshot
    from classes.goal_net import build_goal_observation

    for step in range(steps):
        # Store per-creature action data for this tick
        tick_data = {}  # uid → (obs_arr, action, log_prob, value)

        # Goal selection (hierarchical): every GOAL_INTERVAL steps
        if goal_net and step % GOAL_INTERVAL == 0:
            for c in sim.creatures:
                if not c.is_alive:
                    continue
                # Collect goal reward from previous goal period
                gs = _goal_states.get(c.uid)
                if gs and goal_buffer:
                    g_obs, g_idx, g_lp, g_val, g_rew = gs
                    goal_buffer.store(g_obs, g_idx, g_rew, g_val, g_lp, not c.is_alive)
                # Select new goal
                goal_obs = build_goal_observation(c, sim.cols, sim.rows)
                goal_obs_arr = np.array(goal_obs, dtype=np.float32)
                known = set(c.known_locations.keys()) if c.known_locations else set()
                g_idx, g_lp, g_val = goal_net.get_goal(goal_obs_arr, known_purposes=known)
                purpose = TILE_PURPOSES[g_idx]
                # Set goal on creature
                target_info = c.pick_goal_target(purpose)
                if target_info:
                    c.set_goal(purpose, *target_info[:3],
                               zone_id=target_info[3] if len(target_info) > 3 else None,
                               tick=sim.now)
                else:
                    c.set_goal(purpose, getattr(sim.game_map, 'name', ''),
                               c.location.x, c.location.y, tick=sim.now)
                _goal_states[c.uid] = (goal_obs_arr, g_idx, g_lp, g_val, 0.0)

        # Each creature acts using the shared net
        for c in sim.creatures:
            if not c.is_alive:
                continue

            # Update spatial memory
            c.update_spatial_memory(sim.now)

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
            if prev_rew:
                reward, signals = compute_reward(c, prev_rew, curr_rew,
                                                 breakdown=True, last_action=action)
            else:
                reward, signals = 0.0, {}
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

            # Accumulate reward for goal model
            if c.uid in _goal_states:
                gs = _goal_states[c.uid]
                _goal_states[c.uid] = (gs[0], gs[1], gs[2], gs[3], gs[4] + reward)

            if sink:
                sink.record_step(c.uid, action, reward, signals,
                                 creature_name=c.name or '', alive=c.is_alive)

        # PPO update every rollout_len steps
        if len(buffer) >= rollout_len:
            info = ppo.update(*buffer.get())
            buffer.clear()
            _log('mappo/policy_loss', info['policy_loss'], step)
            _log('mappo/value_loss', info['value_loss'], step)
            _log('mappo/entropy', info['entropy'], step)
            if sink:
                sink.record_training_update(info['entropy'], info['value_loss'],
                                            info['policy_loss'])

        # Goal PPO update (goal buffer fills slower — every GOAL_INTERVAL steps)
        if goal_buffer and goal_ppo and len(goal_buffer) >= max(64, rollout_len // GOAL_INTERVAL):
            g_info = goal_ppo.update(*goal_buffer.get())
            goal_buffer.clear()
            _log('mappo/goal_policy_loss', g_info['policy_loss'], step)
            _log('mappo/goal_entropy', g_info['entropy'], step)

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

            if sink:
                # Gather creature final states
                creature_finals = {}
                for c in sim.creatures:
                    creature_finals[c.uid] = _creature_final_state(c)
                sink.end_episode('MAPPO', 0, sim.alive_count,
                                 len(sim.creatures),
                                 arena_kwargs.get('cols', 0),
                                 arena_kwargs.get('rows', 0),
                                 creature_finals)

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
            arena_kwargs: dict = None, rollout_len: int = 2048,
            sink=None, goal_net=None, goal_ppo=None) -> TorchCreatureNet:
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
        if prev_rew:
            reward, signals = compute_reward(agent, prev_rew, curr_rew, breakdown=True)
        else:
            reward, signals = 0.0, {}
        sim._reward_snapshots[agent.uid] = curr_rew
        total_reward += reward
        ppo_step_rewards.append(reward)
        if len(ppo_step_rewards) > 500:
            ppo_step_rewards = ppo_step_rewards[-500:]

        if sink and agent.is_alive:
            sink.record_step(agent.uid, action, reward, signals,
                             creature_name=agent.name or '', alive=agent.is_alive)

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
            if sink:
                sink.record_training_update(info['entropy'], info['value_loss'],
                                            info['policy_loss'])

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

            if sink:
                creature_finals = {}
                for c in sim.creatures:
                    creature_finals[c.uid] = _creature_final_state(c)
                sink.end_episode('PPO', 0, sim.alive_count,
                                 len(sim.creatures),
                                 arena_kwargs.get('cols', 0),
                                 arena_kwargs.get('rows', 0),
                                 creature_finals)

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
          model_name: str = None, resume_from: str = None,
          arena_cols: int = 25, arena_rows: int = 25,
          num_creatures: int = 16):
    """Run the full MAPPO → ES → PPO training pipeline.

    Models are saved to the game.db nn_models table with versioning.
    TensorBoard logs still go to editor/runs/.
    """
    global _writer, SAVE_DIR
    from torch.utils.tensorboard import SummaryWriter

    if not model_name:
        model_name = f'model_{time.strftime("%Y%m%d_%H%M%S")}'
    run_tag = f'{model_name}_{time.strftime("%Y%m%d_%H%M%S")}'

    # Keep a run-specific dir for TensorBoard + .npz runtime weights
    SAVE_DIR = Path(__file__).parent.parent / 'models' / run_tag
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    _writer = SummaryWriter(log_dir=LOG_DIR / run_tag)

    training_params = {
        'cycles': cycles,
        'mappo_steps': mappo_steps,
        'es_generations': es_generations,
        'es_variants': es_variants,
        'es_steps': es_steps,
        'ppo_steps': ppo_steps,
        'lr': lr,
        'arena_cols': arena_cols,
        'arena_rows': arena_rows,
        'num_creatures': num_creatures,
        'observation_size': OBSERVATION_SIZE,
        'num_actions': NUM_ACTIONS,
    }

    print(f'TensorBoard: tensorboard --logdir {LOG_DIR}')
    print(f'Model name: {model_name}')
    print(f'Training pipeline: {cycles} cycles')
    print(f'  MAPPO: {mappo_steps} steps per cycle')
    print(f'  ES: {es_generations} generations x {es_variants} variants x {es_steps} steps')
    print(f'  PPO: {ppo_steps} steps per cycle')
    print(f'  Observation size: {OBSERVATION_SIZE}')
    print(f'  Action space: {NUM_ACTIONS}')
    print(f'  Learning rate: {lr}')

    net = TorchCreatureNet()
    parent_version = None

    # Resume: try DB first (name:version format), then fall back to .pt file
    if resume_from:
        if ':' in resume_from:
            # DB format: "model_name:version" or "model_name" for latest
            parts = resume_from.split(':', 1)
            rname = parts[0]
            rver = int(parts[1]) if parts[1] else None
            net, row_info = _load_model_from_db(net, rname, rver)
            parent_version = row_info['version']
            print(f'  Resumed from DB: {rname} v{parent_version}')
        else:
            # Legacy .pt file path
            print(f'  Resuming from file: {resume_from}')
            saved_state = torch.load(resume_from, weights_only=True)
            net = _load_state_into_net(net, saved_state)

    ppo = PPO(net, lr=lr)

    # Goal model (hierarchical)
    from editor.simulation.torch_net import TorchGoalNet
    from classes.goal_net import GOAL_OBSERVATION_SIZE
    goal_net = TorchGoalNet(input_size=GOAL_OBSERVATION_SIZE)
    goal_ppo = PPO(goal_net, lr=lr)
    print(f'  Action net params: {net.param_count():,}')
    print(f'  Goal net params: {goal_net.param_count():,}')
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
    es_arena_kwargs = {
        **arena_kwargs,
        'mask_probability': 0.15,
        'mask_pool': ['socially_deaf', 'blind', 'deaf', 'fearless',
                      'feral', 'impulsive', 'nearsighted', 'paranoid',
                      'amnesiac', 'greedy', 'zealot'],
    }

    pipeline_t0 = time.time()
    all_cycle_stats = []

    # Initialize training analytics sink
    from editor.simulation.training_sink import TrainingSink, summarize_to_db
    from editor.simulation.training_db import (
        get_con as get_training_con, save_schema,
        generate_observation_schema, generate_action_schema,
    )

    sink = TrainingSink(SAVE_DIR)

    # Save current observation/action schemas
    obs_schema = generate_observation_schema()
    act_schema = generate_action_schema()
    obs_schema_id = save_schema('observation', obs_schema, OBSERVATION_SIZE)
    act_schema_id = save_schema('action', act_schema, NUM_ACTIONS)
    print(f'  Obs schema: id={obs_schema_id}, Act schema: id={act_schema_id}')

    for cycle in range(cycles):
        print(f'\n{"="*60}')
        print(f'CYCLE {cycle + 1} / {cycles}')
        print(f'{"="*60}')

        t0 = time.time()

        # Phase 1: MAPPO
        mappo_t0 = time.time()
        net = run_mappo(net, ppo, steps=mappo_steps, arena_kwargs=arena_kwargs,
                        sink=sink, goal_net=goal_net, goal_ppo=goal_ppo)
        sink.end_phase('MAPPO', cycle + 1, 0, mappo_steps,
                       time.time() - mappo_t0)
        net.export_to_numpy(SAVE_DIR / f'mappo_cycle{cycle+1}.npz')

        # Phase 2: ES
        es_t0 = time.time()
        net = run_es(net, generations=es_generations, variants=es_variants,
                     steps_per_variant=es_steps, arena_kwargs=es_arena_kwargs)
        sink.end_phase('ES', cycle + 1, mappo_steps,
                       mappo_steps + es_generations * es_variants,
                       time.time() - es_t0)

        # Phase 3: PPO
        ppo_t0 = time.time()
        ppo = PPO(net, lr=lr)  # fresh optimizer
        net = run_ppo(net, ppo, steps=ppo_steps, checkpoint_dir=SAVE_DIR,
                      arena_kwargs=arena_kwargs, sink=sink,
                      goal_net=goal_net, goal_ppo=goal_ppo)
        sink.end_phase('PPO', cycle + 1, mappo_steps, mappo_steps + ppo_steps,
                       time.time() - ppo_t0)

        elapsed = time.time() - t0
        all_cycle_stats.append({'cycle': cycle + 1, 'seconds': round(elapsed, 1)})
        print(f'\nCycle {cycle+1} complete in {elapsed:.0f}s')

    sink.close()

    # Save final model to DB
    total_seconds = time.time() - pipeline_t0
    training_stats = {
        'total_seconds': round(total_seconds, 1),
        'cycles': all_cycle_stats,
    }

    version = _save_model_to_db(
        net, model_name, parent_version,
        training_params, training_stats, total_seconds,
        obs_schema_id=obs_schema_id, act_schema_id=act_schema_id,
    )

    # Create training_runs record and summarize sink to training.db
    try:
        from datetime import datetime
        tcon = get_training_con()
        tcon.execute('''INSERT INTO training_runs
            (model_name, model_version, parent_version,
             obs_schema_id, act_schema_id,
             started_at, finished_at, total_seconds, training_params)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (model_name, version, parent_version,
             obs_schema_id, act_schema_id,
             datetime.utcfromtimestamp(pipeline_t0).isoformat(sep=' ', timespec='seconds'),
             datetime.utcnow().isoformat(sep=' ', timespec='seconds'),
             total_seconds, json.dumps(training_params)))
        tcon.commit()
        run_id = tcon.execute('SELECT last_insert_rowid()').fetchone()[0]
        tcon.close()
        # Update sink run_id and summarize
        summarize_to_db(SAVE_DIR, run_id)
        print(f'  Training analytics saved to training.db (run_id={run_id})')
    except Exception as e:
        print(f'  Warning: failed to save training analytics: {e}')

    # Export .npz for runtime use
    net.export_to_numpy(SAVE_DIR / 'final.npz')
    root_models = Path(__file__).parent.parent / 'models'
    net.export_to_numpy(root_models / 'latest.npz')

    if _writer:
        _writer.close()
    from editor.simulation.train_state import clear_state
    clear_state()
    print(f'\nTraining complete in {total_seconds:.0f}s')
    print(f'  Saved to DB: {model_name} v{version}')
    print(f'  NumPy weights: {SAVE_DIR}/final.npz')
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
    parser.add_argument('--model', type=str, default=None, help='Model lineage name (stored in DB)')
    parser.add_argument('--resume', type=str, default=None,
                        help='Resume from: "name:version" for DB, or path to .pt file')
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
        model_name=args.model,
        resume_from=args.resume,
        arena_cols=args.arena_cols,
        arena_rows=args.arena_rows,
        num_creatures=args.num_creatures,
    )
