"""
Parallel training workers for MAPPO and PPO.

Each worker process creates its own arena, simulation, and net copy.
Workers collect rollout data as numpy arrays and return them to the
main process for PPO updates. Only weights and rollout buffers cross
process boundaries — no pickling of game objects.
"""
from __future__ import annotations
import multiprocessing as mp
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


_WORKER_STATE_DIR = Path(__file__).parent.parent.parent / 'editor' / 'models'


def _write_worker_state(worker_id: int, stats: dict):
    """Write per-worker live stats to a tiny JSON file."""
    import json, time
    stats['timestamp'] = time.time()
    stats['worker_id'] = worker_id
    path = _WORKER_STATE_DIR / f'_live_worker_{worker_id}.json'
    try:
        path.write_text(json.dumps(stats))
    except Exception:
        pass


def _mappo_worker(worker_id: int, weight_queue: mp.Queue,
                  result_queue: mp.Queue, config: dict):
    """Worker process: creates arena, runs MAPPO rollout, returns buffer data."""
    import numpy as np
    from classes.creature_net import CreatureNet
    from classes.observation import build_observation, OBSERVATION_SIZE
    from classes.actions import Action, dispatch, NUM_ACTIONS, compute_dynamic_mask
    from classes.reward import compute_reward, make_reward_snapshot
    from classes.creature import Creature
    from classes.stats import Stat
    from editor.simulation.arena import generate_arena
    from editor.simulation.headless import Simulation

    arena_kwargs = config['arena_kwargs']
    sim_kwargs = config['sim_kwargs']
    signal_scales = config['signal_scales']
    action_mask = config['action_mask']
    rollout_len = config['rollout_len']

    net = CreatureNet()

    while True:
        # Get updated weights from main process
        msg = weight_queue.get()
        if msg is None:
            break  # shutdown signal
        net.weights = msg

        # Create fresh arena
        arena = generate_arena(**arena_kwargs)
        sim = Simulation(arena, **sim_kwargs)
        for c in sim.creatures:
            c.behavior = None
            c.unregister_tick('behavior')

        # Collect rollout
        obs_buf = []
        act_buf = []
        rew_buf = []
        val_buf = []
        lp_buf = []
        done_buf = []
        mask_buf = []

        reward_snapshots = {}
        for c in sim.creatures:
            reward_snapshots[c.uid] = make_reward_snapshot(c)

        action_counts = {}
        signal_totals = {}
        total_reward = 0.0

        for step in range(rollout_len):
            sim.now += sim.tick_ms
            sim.step_count += 1
            sim.game_clock.update(1.0)
            if sim._hot_creatures:
                sim._hot_creatures.sync(list(sim.creatures))
                Creature._hot_array = sim._hot_creatures
            if sim._tile_grid:
                Creature._tile_grid = sim._tile_grid

            for c in sim.creatures:
                if not c.is_alive:
                    continue

                c.update_spatial_memory(sim.now)
                obs = build_observation(c, sim.cols, sim.rows,
                                        game_clock=sim.game_clock,
                                        observation_tick=sim.step_count)
                obs_arr = np.array(obs, dtype=np.float32)

                dyn_mask = compute_dynamic_mask(c)
                combined = action_mask * dyn_mask if action_mask is not None else dyn_mask

                probs = net.forward(obs_arr)
                probs = probs * combined
                total = probs.sum()
                if total > 0:
                    probs /= total
                else:
                    probs = combined / combined.sum() if combined.sum() > 0 else np.ones(NUM_ACTIONS) / NUM_ACTIONS

                action = int(np.random.choice(NUM_ACTIONS, p=probs))
                log_prob = float(np.log(probs[action] + 1e-8))
                value = 0.0  # simplified — workers don't need value estimates

                target = next((o for o in c.nearby(include_ghosts=False) if c.can_see(o)), None)
                dispatch(c, action, {'cols': sim.cols, 'rows': sim.rows,
                                     'target': target, 'now': sim.now,
                                     'combat_enabled': sim_kwargs.get('combat_enabled', True)})

                prev_rew = reward_snapshots.get(c.uid)
                curr_rew = make_reward_snapshot(c)
                if prev_rew:
                    reward, signals = compute_reward(c, prev_rew, curr_rew,
                                                     breakdown=True, last_action=action,
                                                     signal_scales=signal_scales)
                else:
                    reward, signals = 0.0, {}
                reward_snapshots[c.uid] = curr_rew

                obs_buf.append(obs_arr)
                act_buf.append(action)
                rew_buf.append(reward)
                val_buf.append(value)
                lp_buf.append(log_prob)
                done_buf.append(0.0 if c.is_alive else 1.0)
                mask_buf.append(combined)

                action_counts[action] = action_counts.get(action, 0) + 1
                total_reward += reward
                if signals:
                    for sk, sv in signals.items():
                        signal_totals[sk] = signal_totals.get(sk, 0.0) + sv

            # Process opponent ticks
            for c in sim.creatures:
                if c.is_alive:
                    c.process_ticks(sim.now)

            # Live stats every 50 steps
            if step % 10 == 0:
                alive = sum(1 for c in sim.creatures if c.is_alive)
                n_steps = max(1, len(rew_buf))
                _day = int(sim.game_clock.day)
                _hr = int(sim.game_clock.hour)
                _mn = int((sim.game_clock.hour % 1) * 60)
                top_actions = sorted(action_counts.items(), key=lambda x: -x[1])[:5]
                act_total = max(1, sum(action_counts.values()))
                act_pcts = {}
                for aid, cnt in top_actions:
                    try:
                        act_pcts[Action(aid).name.lower()] = round(cnt / act_total, 3)
                    except ValueError:
                        act_pcts[f'act_{aid}'] = round(cnt / act_total, 3)
                sig_avgs = {k: round(v / n_steps, 4) for k, v in signal_totals.items() if abs(v) > 0.001}
                _write_worker_state(worker_id, {
                    'phase': 'MAPPO', 'step': step,
                    'alive': alive, 'total': len(sim.creatures),
                    'avg_reward': round(total_reward / n_steps, 4),
                    'samples': n_steps,
                    'clock': f'{_day:02d}:{_hr:02d}:{_mn:02d}',
                    'actions': act_pcts,
                    'signals': sig_avgs,
                })

        # Package as numpy arrays
        result = {
            'obs': np.array(obs_buf, dtype=np.float32),
            'actions': np.array(act_buf, dtype=np.int64),
            'rewards': np.array(rew_buf, dtype=np.float32),
            'values': np.array(val_buf, dtype=np.float32),
            'log_probs': np.array(lp_buf, dtype=np.float32),
            'dones': np.array(done_buf, dtype=np.float32),
            'masks': np.array(mask_buf, dtype=np.float32),
            'worker_id': worker_id,
        }
        result_queue.put(result)


def _ppo_worker(worker_id: int, weight_queue: mp.Queue,
                result_queue: mp.Queue, config: dict):
    """Worker process: runs single-agent PPO episodes, returns buffer data."""
    import numpy as np
    from classes.creature_net import CreatureNet
    from classes.observation import build_observation, OBSERVATION_SIZE
    from classes.actions import Action, dispatch, NUM_ACTIONS, compute_dynamic_mask
    from classes.reward import compute_reward, make_reward_snapshot
    from classes.creature import Creature
    from classes.creature._behaviors import StatWeightedBehavior
    from classes.stats import Stat
    from editor.simulation.arena import generate_arena
    from editor.simulation.headless import Simulation

    arena_kwargs = config['arena_kwargs']
    sim_kwargs = config['sim_kwargs']
    signal_scales = config['signal_scales']
    action_mask = config['action_mask']
    rollout_len = config['rollout_len']

    net = CreatureNet()

    while True:
        msg = weight_queue.get()
        if msg is None:
            break
        net.weights = msg

        arena = generate_arena(**arena_kwargs)
        sim = Simulation(arena, **sim_kwargs)
        agent = sim.creatures[0]
        agent.behavior = None

        for c in sim.creatures[1:]:
            c.behavior = StatWeightedBehavior()
            c._combat_enabled = sim_kwargs.get('combat_enabled', True)
            c.register_tick('behavior', 500, c._do_behavior)

        obs_buf = []
        act_buf = []
        rew_buf = []
        val_buf = []
        lp_buf = []
        done_buf = []
        mask_buf = []

        reward_snapshots = {agent.uid: make_reward_snapshot(agent)}
        action_counts = {}
        signal_totals = {}
        total_reward = 0.0

        for step in range(rollout_len):
            sim.now += sim.tick_ms
            sim.step_count += 1
            sim.game_clock.update(1.0)

            if not agent.is_alive:
                # Reset episode
                arena = generate_arena(**arena_kwargs)
                sim = Simulation(arena, **sim_kwargs)
                agent = sim.creatures[0]
                agent.behavior = None
                for c in sim.creatures[1:]:
                    c.behavior = StatWeightedBehavior()
                    c._combat_enabled = sim_kwargs.get('combat_enabled', True)
                    c.register_tick('behavior', 500, c._do_behavior)
                reward_snapshots = {agent.uid: make_reward_snapshot(agent)}
                continue

            if sim._hot_creatures:
                sim._hot_creatures.sync(list(sim.creatures))
                Creature._hot_array = sim._hot_creatures

            # Opponents tick
            for c in sim.creatures:
                if c is not agent and c.is_alive:
                    c.process_ticks(sim.now)

            agent.update_spatial_memory(sim.now)
            obs = build_observation(agent, sim.cols, sim.rows,
                                    game_clock=sim.game_clock,
                                    observation_tick=sim.step_count)
            obs_arr = np.array(obs, dtype=np.float32)

            dyn_mask = compute_dynamic_mask(agent)
            combined = action_mask * dyn_mask if action_mask is not None else dyn_mask

            probs = net.forward(obs_arr)
            probs = probs * combined
            total = probs.sum()
            if total > 0:
                probs /= total
            else:
                probs = combined / combined.sum() if combined.sum() > 0 else np.ones(NUM_ACTIONS) / NUM_ACTIONS

            action = int(np.random.choice(NUM_ACTIONS, p=probs))
            log_prob = float(np.log(probs[action] + 1e-8))

            target = next((o for o in agent.nearby(include_ghosts=False) if agent.can_see(o)), None)
            dispatch(agent, action, {'cols': sim.cols, 'rows': sim.rows,
                                     'target': target, 'now': sim.now,
                                     'combat_enabled': sim_kwargs.get('combat_enabled', True)})

            prev_rew = reward_snapshots.get(agent.uid)
            curr_rew = make_reward_snapshot(agent)
            if prev_rew:
                reward, signals = compute_reward(agent, prev_rew, curr_rew,
                                                 breakdown=True, last_action=action,
                                                 signal_scales=signal_scales)
            else:
                reward, signals = 0.0, {}
            reward_snapshots[agent.uid] = curr_rew

            obs_buf.append(obs_arr)
            act_buf.append(action)
            rew_buf.append(reward)
            val_buf.append(0.0)
            lp_buf.append(log_prob)
            done_buf.append(0.0 if agent.is_alive else 1.0)
            mask_buf.append(combined)

            action_counts[action] = action_counts.get(action, 0) + 1
            total_reward += reward
            for sk, sv in signals.items():
                signal_totals[sk] = signal_totals.get(sk, 0.0) + sv

            if step % 10 == 0:
                n_steps = max(1, len(rew_buf))
                _day = int(sim.game_clock.day)
                _hr = int(sim.game_clock.hour)
                _mn = int((sim.game_clock.hour % 1) * 60)
                act_total = max(1, sum(action_counts.values()))
                act_pcts = {}
                for aid, cnt in sorted(action_counts.items(), key=lambda x: -x[1])[:5]:
                    try:
                        act_pcts[Action(aid).name.lower()] = round(cnt / act_total, 3)
                    except ValueError:
                        act_pcts[f'act_{aid}'] = round(cnt / act_total, 3)
                sig_avgs = {k: round(v / n_steps, 4) for k, v in signal_totals.items() if abs(v) > 0.001}
                _write_worker_state(worker_id, {
                    'phase': 'PPO', 'step': step,
                    'alive': sim.alive_count,
                    'total': len(sim.creatures),
                    'avg_reward': round(total_reward / n_steps, 4),
                    'samples': n_steps,
                    'clock': f'{_day:02d}:{_hr:02d}:{_mn:02d}',
                    'actions': act_pcts,
                    'signals': sig_avgs,
                })

        result = {
            'obs': np.array(obs_buf, dtype=np.float32) if obs_buf else np.empty((0, OBSERVATION_SIZE), dtype=np.float32),
            'actions': np.array(act_buf, dtype=np.int64) if act_buf else np.empty(0, dtype=np.int64),
            'rewards': np.array(rew_buf, dtype=np.float32) if rew_buf else np.empty(0, dtype=np.float32),
            'values': np.array(val_buf, dtype=np.float32) if val_buf else np.empty(0, dtype=np.float32),
            'log_probs': np.array(lp_buf, dtype=np.float32) if lp_buf else np.empty(0, dtype=np.float32),
            'dones': np.array(done_buf, dtype=np.float32) if done_buf else np.empty(0, dtype=np.float32),
            'masks': np.array(mask_buf, dtype=np.float32) if mask_buf else np.empty((0, NUM_ACTIONS), dtype=np.float32),
            'worker_id': worker_id,
        }
        result_queue.put(result)


class ParallelTrainer:
    """Manages N worker processes for parallel rollout collection."""

    def __init__(self, n_workers: int, mode: str, config: dict):
        """
        n_workers: number of parallel arena processes
        mode: 'mappo' or 'ppo'
        config: dict with arena_kwargs, sim_kwargs, signal_scales,
                action_mask, rollout_len
        """
        self.n_workers = n_workers
        self.weight_queues = []
        self.result_queue = mp.Queue()
        self.workers = []

        worker_fn = _mappo_worker if mode == 'mappo' else _ppo_worker

        for i in range(n_workers):
            wq = mp.Queue()
            self.weight_queues.append(wq)
            p = mp.Process(target=worker_fn, args=(i, wq, self.result_queue, config),
                           daemon=True)
            p.start()
            self.workers.append(p)

    def collect_rollouts(self, weights: dict) -> list[dict]:
        """Send weights to all workers, wait for all rollouts.

        Returns list of rollout dicts (one per worker).
        """
        for wq in self.weight_queues:
            wq.put(weights)

        results = []
        for _ in range(self.n_workers):
            results.append(self.result_queue.get())
        return results

    def shutdown(self):
        """Send shutdown signal to all workers."""
        for wq in self.weight_queues:
            wq.put(None)
        for p in self.workers:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()

    @staticmethod
    def merge_rollouts(rollouts: list[dict]) -> dict:
        """Merge multiple rollout dicts into one."""
        return {
            'obs': np.concatenate([r['obs'] for r in rollouts if len(r['obs']) > 0]),
            'actions': np.concatenate([r['actions'] for r in rollouts if len(r['actions']) > 0]),
            'rewards': np.concatenate([r['rewards'] for r in rollouts if len(r['rewards']) > 0]),
            'values': np.concatenate([r['values'] for r in rollouts if len(r['values']) > 0]),
            'log_probs': np.concatenate([r['log_probs'] for r in rollouts if len(r['log_probs']) > 0]),
            'dones': np.concatenate([r['dones'] for r in rollouts if len(r['dones']) > 0]),
            'masks': np.concatenate([r['masks'] for r in rollouts if len(r['masks']) > 0]),
        }


# ---------------------------------------------------------------------------
# Parallel ES variant evaluation
# ---------------------------------------------------------------------------

def _es_eval_worker(args):
    """Evaluate one ES variant. Runs in a pool worker process."""
    variant_weights, config = args
    from classes.creature_net import CreatureNet
    from classes.actions import dispatch, Action, NUM_ACTIONS
    from classes.creature import Creature
    from classes.creature._behaviors import StatWeightedBehavior
    from editor.simulation.arena import generate_arena
    from editor.simulation.headless import Simulation

    arena_kwargs = config['arena_kwargs']
    sim_kwargs = config['sim_kwargs']
    steps = config['steps_per_variant']

    net = CreatureNet()
    net.weights = variant_weights

    arena = generate_arena(**arena_kwargs)
    sim = Simulation(arena, **sim_kwargs)
    agent = sim.creatures[0]
    agent.behavior = None
    for c in sim.creatures[1:]:
        c.behavior = StatWeightedBehavior()
        c._combat_enabled = sim_kwargs.get('combat_enabled', True)
        c.register_tick('behavior', 500, c._do_behavior)

    total_reward = 0.0
    for step in range(steps):
        if not agent.is_alive:
            break
        sim.now += sim.tick_ms
        sim.step_count += 1
        for c in sim.creatures:
            if c is not agent and c.is_alive:
                c.process_ticks(sim.now)
        from classes.observation import build_observation
        from classes.reward import compute_reward, make_reward_snapshot
        obs = build_observation(agent, sim.cols, sim.rows,
                                game_clock=sim.game_clock,
                                observation_tick=sim.step_count)
        obs_arr = np.array(obs, dtype=np.float32)
        probs = net.forward(obs_arr)
        action = int(np.random.choice(NUM_ACTIONS, p=probs))
        target = next((o for o in agent.nearby(include_ghosts=False) if agent.can_see(o)), None)
        dispatch(agent, action, {'cols': sim.cols, 'rows': sim.rows,
                                 'target': target, 'now': sim.now,
                                 'combat_enabled': sim_kwargs.get('combat_enabled', True)})
        curr_rew = make_reward_snapshot(agent)
        prev_rew = getattr(agent, '_es_prev_snap', None)
        if prev_rew:
            reward = compute_reward(agent, prev_rew, curr_rew,
                                     signal_scales=config.get('signal_scales'))
        else:
            reward = 0.0
        agent._es_prev_snap = curr_rew
        total_reward += reward

    return total_reward


def parallel_es_evaluate(base_weights: dict, noise_vectors: list,
                          noise_scale: float, config: dict,
                          n_workers: int = 4) -> list[float]:
    """Evaluate ES variants in parallel using a process pool.

    Args:
        base_weights: current network weights dict
        noise_vectors: list of {key: noise_array} dicts (one per variant)
        noise_scale: scale factor for noise
        config: arena/sim/steps config
        n_workers: number of parallel processes

    Returns:
        list of total rewards (one per variant)
    """
    # Build variant weight dicts
    tasks = []
    for noise in noise_vectors:
        variant = {}
        for k, w in base_weights.items():
            variant[k] = (w + noise[k] * noise_scale).astype(np.float32)
        tasks.append((variant, config))

    with mp.Pool(n_workers) as pool:
        rewards = pool.map(_es_eval_worker, tasks)

    return rewards
