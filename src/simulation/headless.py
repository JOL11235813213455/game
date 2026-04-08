"""
Headless simulation loop for RL training.

Runs the game loop without rendering: advances time, processes creature
ticks, collects observations and rewards each step.

Usage:
    from simulation.headless import Simulation
    from simulation.arena import generate_arena

    arena = generate_arena(num_creatures=6)
    sim = Simulation(arena)
    for step in range(1000):
        results = sim.step()
        # results: list of {creature, observation, reward, alive}
"""
from __future__ import annotations
from classes.observation import build_observation, make_snapshot, OBSERVATION_SIZE
from classes.reward import compute_reward, make_reward_snapshot


class Simulation:
    """Headless game simulation for RL training.

    Each step():
    1. Advance simulation time by tick_ms
    2. Process all creature ticks (behavior, regen, etc.)
    3. Collect observations and rewards for each creature
    4. Return per-creature results
    """

    def __init__(self, arena: dict, tick_ms: int = 100):
        """Initialize simulation from an arena dict.

        Args:
            arena: dict from generate_arena() with map, creatures, cols, rows
            tick_ms: milliseconds per simulation step
        """
        self.game_map = arena['map']
        self.creatures = list(arena['creatures'])
        self.cols = arena['cols']
        self.rows = arena['rows']
        self.tick_ms = tick_ms
        self.now = 0
        self.step_count = 0

        # Per-creature state tracking
        self._obs_snapshots: dict[int, dict] = {}  # uid → prev observation snapshot
        self._reward_snapshots: dict[int, dict] = {}  # uid → prev reward snapshot

        # Initialize snapshots
        for c in self.creatures:
            self._obs_snapshots[c.uid] = make_snapshot(c)
            self._reward_snapshots[c.uid] = make_reward_snapshot(c)

    def step(self) -> list[dict]:
        """Advance one simulation step.

        Returns list of dicts, one per creature:
            {creature, observation, reward, alive}
        """
        self.now += self.tick_ms
        self.step_count += 1

        # Process all creature ticks (behavior, regen, etc.)
        for c in self.creatures:
            if c.is_alive:
                c.update(self.now, self.cols, self.rows)

        # Collect results
        results = []
        for c in self.creatures:
            prev_obs = self._obs_snapshots.get(c.uid)
            prev_rew = self._reward_snapshots.get(c.uid)

            # Build current observation
            obs = build_observation(c, self.cols, self.rows, prev_snapshot=prev_obs)

            # Compute reward
            curr_rew = make_reward_snapshot(c)
            reward = compute_reward(c, prev_rew, curr_rew) if prev_rew else 0.0

            # Update snapshots
            self._obs_snapshots[c.uid] = make_snapshot(c)
            self._reward_snapshots[c.uid] = curr_rew

            results.append({
                'creature': c,
                'observation': obs,
                'reward': reward,
                'alive': c.is_alive,
            })

        return results

    @property
    def alive_count(self) -> int:
        return sum(1 for c in self.creatures if c.is_alive)

    @property
    def done(self) -> bool:
        """Simulation is done when 0 or 1 creatures remain alive."""
        return self.alive_count <= 1

    def summary(self) -> dict:
        """Return a summary of the simulation state."""
        alive = [c for c in self.creatures if c.is_alive]
        dead = [c for c in self.creatures if not c.is_alive]
        return {
            'step': self.step_count,
            'time_ms': self.now,
            'alive': len(alive),
            'dead': len(dead),
            'alive_names': [c.name for c in alive],
            'dead_names': [c.name for c in dead],
        }
