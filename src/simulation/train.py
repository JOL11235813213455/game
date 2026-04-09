"""
Training pipeline: MAPPO → ES → PPO cycles.

Usage:
    cd src
    python -m simulation.train --cycles 3 --mappo-steps 100000 --ppo-steps 100000

Requires: numpy (already used). No external RL library — custom PPO.
"""
from __future__ import annotations
import argparse
import os
import sys
import time
import random
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from simulation.net import CreatureNet, relu, softmax
from simulation.arena import generate_arena, spawn_creature
from simulation.headless import Simulation
from classes.observation import OBSERVATION_SIZE, apply_preset_mask
from classes.actions import NUM_ACTIONS
from classes.creature import NeuralBehavior, StatWeightedBehavior

SAVE_DIR = Path(__file__).parent.parent / 'models'
SAVE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# PPO Core (minimal implementation — no external dependencies)
# ---------------------------------------------------------------------------

class PPOBuffer:
    """Stores experience tuples for PPO training."""

    def __init__(self, obs_dim: int, max_size: int = 4096):
        self.obs = np.zeros((max_size, obs_dim), dtype=np.float32)
        self.actions = np.zeros(max_size, dtype=np.int32)
        self.rewards = np.zeros(max_size, dtype=np.float32)
        self.values = np.zeros(max_size, dtype=np.float32)
        self.log_probs = np.zeros(max_size, dtype=np.float32)
        self.dones = np.zeros(max_size, dtype=np.float32)
        self.ptr = 0
        self.max_size = max_size

    def store(self, obs, action, reward, value, log_prob, done):
        i = self.ptr % self.max_size
        self.obs[i] = obs
        self.actions[i] = action
        self.rewards[i] = reward
        self.values[i] = value
        self.log_probs[i] = log_prob
        self.dones[i] = 1.0 if done else 0.0
        self.ptr += 1

    def get(self):
        n = min(self.ptr, self.max_size)
        return (self.obs[:n], self.actions[:n], self.rewards[:n],
                self.values[:n], self.log_probs[:n], self.dones[:n])

    def clear(self):
        self.ptr = 0


class PPOTrainer:
    """Minimal PPO trainer using pure NumPy.

    Policy net: the CreatureNet (action probabilities).
    Value net: separate small net estimating future rewards.
    """

    def __init__(self, policy_net: CreatureNet, lr: float = 3e-4,
                 gamma: float = 0.995, clip_eps: float = 0.2,
                 epochs: int = 4, batch_size: int = 512):
        self.policy = policy_net
        self.lr = lr
        self.gamma = gamma
        self.clip_eps = clip_eps
        self.epochs = epochs
        self.batch_size = batch_size

        # Simple value head: shares first two layers, separate output
        self.value_w = np.random.randn(policy_net.h3_size, 1).astype(np.float32) * 0.01
        self.value_b = np.zeros(1, dtype=np.float32)

    def compute_value(self, obs: np.ndarray) -> float:
        """Estimate state value using shared features."""
        x = np.asarray(obs, dtype=np.float32)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        # Forward through shared layers
        w = self.policy.weights
        x = relu(x @ w['w1'] + w['b1'])
        x = relu(x @ w['w2'] + w['b2'])
        x = relu(x @ w['w3'] + w['b3'])
        v = (x @ self.value_w + self.value_b).flatten()
        return float(v[0]) if len(v) == 1 else v

    def compute_advantages(self, rewards, values, dones):
        """GAE (Generalized Advantage Estimation)."""
        n = len(rewards)
        advantages = np.zeros(n, dtype=np.float32)
        last_gae = 0.0
        for t in reversed(range(n)):
            if t == n - 1:
                next_val = 0.0
            else:
                next_val = values[t + 1]
            delta = rewards[t] + self.gamma * next_val * (1 - dones[t]) - values[t]
            last_gae = delta + self.gamma * 0.95 * (1 - dones[t]) * last_gae
            advantages[t] = last_gae
        returns = advantages + values
        return advantages, returns

    def update(self, buffer: PPOBuffer) -> dict:
        """Run PPO update on collected experience."""
        obs, actions, rewards, values, old_log_probs, dones = buffer.get()
        n = len(obs)
        if n < self.batch_size:
            return {'loss': 0.0}

        advantages, returns = self.compute_advantages(rewards, values, dones)
        # Normalize advantages
        adv_mean = advantages.mean()
        adv_std = advantages.std() + 1e-8
        advantages = (advantages - adv_mean) / adv_std

        total_loss = 0.0
        for _ in range(self.epochs):
            indices = np.random.permutation(n)
            for start in range(0, n - self.batch_size + 1, self.batch_size):
                batch_idx = indices[start:start + self.batch_size]
                b_obs = obs[batch_idx]
                b_act = actions[batch_idx]
                b_adv = advantages[batch_idx]
                b_ret = returns[batch_idx]
                b_old_lp = old_log_probs[batch_idx]

                # Forward pass
                probs = self.policy.forward(b_obs)
                new_log_probs = np.log(probs[np.arange(len(b_act)), b_act] + 1e-8)

                # PPO clipped objective
                ratio = np.exp(new_log_probs - b_old_lp)
                clip_ratio = np.clip(ratio, 1 - self.clip_eps, 1 + self.clip_eps)
                policy_loss = -np.minimum(ratio * b_adv, clip_ratio * b_adv).mean()

                total_loss += policy_loss

                # Simple gradient approximation via finite differences
                # (real implementation would use autograd — this is a placeholder
                # that works for demonstration/initial training)
                self._finite_diff_update(b_obs, b_act, b_adv, b_old_lp)

        return {'loss': total_loss / max(1, self.epochs)}

    def _finite_diff_update(self, obs, actions, advantages, old_log_probs):
        """Approximate gradient update via perturbation.

        This is a simplified training step. For production training,
        use stable-baselines3 or implement proper backprop.
        """
        eps = 1e-3
        for key in self.policy.weights:
            # Random perturbation direction
            noise = np.random.randn(*self.policy.weights[key].shape).astype(np.float32)
            noise *= eps

            # Perturb +
            self.policy.weights[key] += noise
            probs_plus = self.policy.forward(obs)
            lp_plus = np.log(probs_plus[np.arange(len(actions)), actions] + 1e-8)
            loss_plus = -(np.exp(lp_plus - old_log_probs) * advantages).mean()

            # Perturb -
            self.policy.weights[key] -= 2 * noise
            probs_minus = self.policy.forward(obs)
            lp_minus = np.log(probs_minus[np.arange(len(actions)), actions] + 1e-8)
            loss_minus = -(np.exp(lp_minus - old_log_probs) * advantages).mean()

            # Restore + apply gradient
            self.policy.weights[key] += noise  # back to original
            grad = (loss_plus - loss_minus) / (2 * eps)
            self.policy.weights[key] -= self.lr * grad * noise


# ---------------------------------------------------------------------------
# Training Phases
# ---------------------------------------------------------------------------

def run_mappo(net: CreatureNet, steps: int = 100000,
              arena_kwargs: dict = None) -> CreatureNet:
    """Phase 1: Multi-agent PPO — all creatures share weights."""
    print(f'\n=== MAPPO Phase ({steps} steps) ===')
    arena_kwargs = arena_kwargs or {'cols': 20, 'rows': 20, 'num_creatures': 8}
    trainer = PPOTrainer(net)
    buffer = PPOBuffer(OBSERVATION_SIZE)

    episode_rewards = []
    arena = generate_arena(**arena_kwargs)
    sim = Simulation(arena)

    for step in range(steps):
        results = sim.step()

        for r in results:
            c = r['creature']
            if not r['alive']:
                continue
            obs = np.array(r['observation'], dtype=np.float32)
            probs = net.forward(obs)
            action = int(np.random.choice(NUM_ACTIONS, p=probs))
            log_prob = float(np.log(probs[action] + 1e-8))
            value = trainer.compute_value(obs)
            buffer.store(obs, action, r['reward'], value, log_prob,
                         not r['alive'])

        # Update every 2048 steps
        if buffer.ptr >= 2048:
            info = trainer.update(buffer)
            buffer.clear()

        # Reset episode periodically
        if step % 5000 == 4999 or sim.alive_count <= 1:
            avg_rew = np.mean([r['reward'] for r in results])
            episode_rewards.append(avg_rew)
            arena = generate_arena(**arena_kwargs)
            sim = Simulation(arena)

        if step % 10000 == 9999:
            avg = np.mean(episode_rewards[-10:]) if episode_rewards else 0
            print(f'  Step {step+1}: avg_reward={avg:.3f}, alive={sim.alive_count}')

    print(f'  MAPPO complete. Episodes: {len(episode_rewards)}')
    return net


def run_es(net: CreatureNet, generations: int = 50,
           variants: int = 50, steps_per_variant: int = 2000,
           noise_scale: float = 0.1, arena_kwargs: dict = None) -> CreatureNet:
    """Phase 2: Evolutionary Strategies — diversify weights."""
    print(f'\n=== ES Phase ({generations} gens × {variants} variants) ===')
    arena_kwargs = arena_kwargs or {'cols': 15, 'rows': 15, 'num_creatures': 6}

    base_weights = {k: v.copy() for k, v in net.weights.items()}

    for gen in range(generations):
        # Generate noise vectors
        noises = []
        rewards = []

        for v in range(variants):
            noise = {k: np.random.randn(*base_weights[k].shape).astype(np.float32) * noise_scale
                     for k in base_weights}
            noises.append(noise)

            # Apply noise
            for k in net.weights:
                net.weights[k] = base_weights[k] + noise[k]

            # Evaluate
            arena = generate_arena(**arena_kwargs)
            sim = Simulation(arena)
            total_reward = 0.0
            for _ in range(steps_per_variant):
                results = sim.step()
                total_reward += sum(r['reward'] for r in results if r['alive'])
                if sim.alive_count <= 1:
                    break
            rewards.append(total_reward)

        # Rank and update
        rewards = np.array(rewards)
        order = np.argsort(rewards)[::-1]
        top_n = max(1, variants // 5)  # top 20%

        # Average top noise vectors
        for k in base_weights:
            update = np.zeros_like(base_weights[k])
            for idx in order[:top_n]:
                update += noises[idx][k]
            update /= top_n
            base_weights[k] += update * 0.5

        # Restore best weights
        for k in net.weights:
            net.weights[k] = base_weights[k].copy()

        if gen % 10 == 9:
            avg_top = np.mean(rewards[order[:top_n]])
            avg_all = np.mean(rewards)
            print(f'  Gen {gen+1}: top_20%={avg_top:.1f}, avg={avg_all:.1f}')

    print(f'  ES complete.')
    return net


def run_ppo(net: CreatureNet, steps: int = 100000,
            opponent_weights: list = None,
            arena_kwargs: dict = None) -> CreatureNet:
    """Phase 3: Single-agent PPO against diverse opponents."""
    print(f'\n=== PPO Phase ({steps} steps) ===')
    arena_kwargs = arena_kwargs or {'cols': 20, 'rows': 20, 'num_creatures': 8}
    trainer = PPOTrainer(net)
    buffer = PPOBuffer(OBSERVATION_SIZE)

    opponent_weights = opponent_weights or []
    episode_rewards = []

    arena = generate_arena(**arena_kwargs)
    sim = Simulation(arena)

    # Set first creature as agent, rest as opponents
    agent = sim.creatures[0]
    agent.behavior = None  # controlled by training loop

    for c in sim.creatures[1:]:
        if opponent_weights and random.random() < 0.5:
            # Use a random old checkpoint
            opp_net = CreatureNet()
            opp_w = random.choice(opponent_weights)
            opp_net.weights = {k: v.copy() for k, v in opp_w.items()}
            c.behavior = NeuralBehavior(opp_net, temperature=1.0)
        else:
            c.behavior = StatWeightedBehavior()
        c.register_tick('behavior', 500, c._do_behavior)

    for step in range(steps):
        # Agent action
        if agent.is_alive:
            from classes.observation import build_observation, make_snapshot
            obs = build_observation(agent, sim.cols, sim.rows,
                                    world_data=sim.world_data)
            if agent.observation_mask:
                apply_preset_mask(obs, agent.observation_mask)
            obs_arr = np.array(obs, dtype=np.float32)
            probs = net.forward(obs_arr)
            action = int(np.random.choice(NUM_ACTIONS, p=probs))
            log_prob = float(np.log(probs[action] + 1e-8))
            value = trainer.compute_value(obs_arr)

            # Dispatch agent action
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

        # Advance simulation (opponents act via behavior ticks)
        sim.now += sim.tick_ms
        sim.step_count += 1
        for c in sim.creatures:
            if c is not agent and c.is_alive:
                c.update(sim.now, sim.cols, sim.rows)

        # Compute reward for agent
        from classes.reward import compute_reward, make_reward_snapshot
        prev_rew = sim._reward_snapshots.get(agent.uid)
        curr_rew = make_reward_snapshot(agent)
        reward = compute_reward(agent, prev_rew, curr_rew) if prev_rew else 0.0
        sim._reward_snapshots[agent.uid] = curr_rew

        if agent.is_alive:
            buffer.store(obs_arr, action, reward, value, log_prob,
                         not agent.is_alive)

        # Update
        if buffer.ptr >= 2048:
            info = trainer.update(buffer)
            buffer.clear()

        # Reset
        if step % 5000 == 4999 or not agent.is_alive or sim.alive_count <= 1:
            episode_rewards.append(reward)
            arena = generate_arena(**arena_kwargs)
            sim = Simulation(arena)
            agent = sim.creatures[0]
            agent.behavior = None
            for c in sim.creatures[1:]:
                if opponent_weights and random.random() < 0.5:
                    opp_net = CreatureNet()
                    opp_w = random.choice(opponent_weights)
                    opp_net.weights = {k: v.copy() for k, v in opp_w.items()}
                    c.behavior = NeuralBehavior(opp_net, temperature=1.0)
                else:
                    c.behavior = StatWeightedBehavior()
                c.register_tick('behavior', 500, c._do_behavior)

        if step % 10000 == 9999:
            avg = np.mean(episode_rewards[-10:]) if episode_rewards else 0
            print(f'  Step {step+1}: avg_reward={avg:.3f}')

    print(f'  PPO complete.')
    return net


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def train(cycles: int = 3, mappo_steps: int = 100000,
          es_generations: int = 50, es_variants: int = 50,
          ppo_steps: int = 100000):
    """Run the full MAPPO → ES → PPO training pipeline."""
    print(f'Training pipeline: {cycles} cycles')
    print(f'  MAPPO: {mappo_steps} steps per cycle')
    print(f'  ES: {es_generations} generations × {es_variants} variants')
    print(f'  PPO: {ppo_steps} steps per cycle')
    print(f'  Observation size: {OBSERVATION_SIZE}')
    print(f'  Action space: {NUM_ACTIONS}')
    print()

    net = CreatureNet()
    print(f'Net params: {net.param_count():,}')

    checkpoints = []  # saved weight snapshots for opponent pool

    for cycle in range(cycles):
        print(f'\n{"="*60}')
        print(f'CYCLE {cycle + 1} / {cycles}')
        print(f'{"="*60}')

        t0 = time.time()

        # Phase 1: MAPPO
        net = run_mappo(net, steps=mappo_steps)
        checkpoints.append({k: v.copy() for k, v in net.weights.items()})
        net.save(SAVE_DIR / f'mappo_cycle{cycle+1}.npz')

        # Phase 2: ES
        net = run_es(net, generations=es_generations, variants=es_variants)
        checkpoints.append({k: v.copy() for k, v in net.weights.items()})
        net.save(SAVE_DIR / f'es_cycle{cycle+1}.npz')

        # Phase 3: PPO against diverse opponents
        net = run_ppo(net, steps=ppo_steps, opponent_weights=checkpoints)
        checkpoints.append({k: v.copy() for k, v in net.weights.items()})
        net.save(SAVE_DIR / f'ppo_cycle{cycle+1}.npz')

        elapsed = time.time() - t0
        print(f'\nCycle {cycle+1} complete in {elapsed:.0f}s')

    # Save final model
    net.save(SAVE_DIR / 'final.npz')
    print(f'\nTraining complete. Final model saved to {SAVE_DIR / "final.npz"}')
    print(f'Total checkpoints: {len(checkpoints)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train creature AI')
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--mappo-steps', type=int, default=100000)
    parser.add_argument('--es-generations', type=int, default=50)
    parser.add_argument('--es-variants', type=int, default=50)
    parser.add_argument('--ppo-steps', type=int, default=100000)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    train(
        cycles=args.cycles,
        mappo_steps=args.mappo_steps,
        es_generations=args.es_generations,
        es_variants=args.es_variants,
        ppo_steps=args.ppo_steps,
    )
