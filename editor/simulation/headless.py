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
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
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

    def __init__(self, arena: dict, tick_ms: int = 500):
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

        # World data for god system
        from classes.gods import WorldData
        self.world_data = WorldData()

        # Game clock — drives schedules, day/night, temporal observations.
        # Convention: 1 tick (500ms) = 1 game minute, so 1 game hour = 60
        # ticks and 1 full game day = 1440 ticks (~12 real minutes).
        from main.game_clock import GameClock
        self.game_clock = GameClock(start_hour=8.0)
        self._last_clock_tick = 0

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

        # Advance game clock: 1 tick = 1 game minute, matching the hunger
        # drain convention (2.0 / 1440 ticks = full depletion per game day).
        # GameClock.update takes real seconds and maps 1 real second = 1
        # game minute, so advance by exactly 1 real-second per tick.
        self.game_clock.update(1.0)

        # Process all creature ticks (behavior, regen, etc.)
        for c in self.creatures:
            if c.is_alive:
                c.update(self.now, self.cols, self.rows)

        # Grow tile resources every 50 steps (~1 game minute at 500ms ticks)
        if self.step_count % 50 == 0:
            self.game_map.grow_resources()

        # Collect results
        from classes.temporal import make_history_snapshot
        results = []
        for c in self.creatures:
            prev_obs = self._obs_snapshots.get(c.uid)
            prev_rew = self._reward_snapshots.get(c.uid)

            # Build current observation (uses creature's history buffer)
            obs = build_observation(c, self.cols, self.rows, prev_snapshot=prev_obs,
                                   world_data=self.world_data,
                                   game_clock=self.game_clock)

            # Apply observation mask if creature has one
            if c.observation_mask:
                from classes.observation import apply_preset_mask
                apply_preset_mask(obs, c.observation_mask)

            # Compute reward
            curr_rew = make_reward_snapshot(c)
            reward = compute_reward(c, prev_rew, curr_rew) if prev_rew else 0.0

            # Update snapshots
            self._obs_snapshots[c.uid] = make_snapshot(c)
            self._reward_snapshots[c.uid] = curr_rew

            # Append to creature's history buffer for temporal transforms
            if hasattr(c, '_history'):
                c._history.append(make_history_snapshot(c))

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
