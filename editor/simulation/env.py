"""
Gym-compatible RL environment for creature AI training.

Wraps the headless simulation as a standard step/reset interface.
Supports single-agent (controls one creature, others use fallback AI)
and multi-agent (returns observations/rewards for all creatures).

Compatible with gymnasium (OpenAI Gym successor) API:
    env.reset() → observation, info
    env.step(action) → observation, reward, terminated, truncated, info
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
import numpy as np
from editor.simulation.arena import generate_arena
from editor.simulation.headless import Simulation
from classes.observation import build_observation, make_snapshot, OBSERVATION_SIZE
from classes.reward import compute_reward, make_reward_snapshot
from classes.actions import NUM_ACTIONS, dispatch
from classes.creature import StatWeightedBehavior


class CreatureEnv:
    """Single-agent Gym-compatible environment.

    Controls one creature (the agent). All other creatures use
    StatWeightedBehavior as background AI.

    Observation: float32 array of shape (OBSERVATION_SIZE,)
    Action: int in [0, NUM_ACTIONS)
    """

    def __init__(self, arena_kwargs: dict = None, max_steps: int = 1000,
                 tick_ms: int = 100):
        self.arena_kwargs = arena_kwargs or {
            'cols': 15, 'rows': 15, 'num_creatures': 6,
            'obstacle_density': 0.08,
        }
        self.max_steps = max_steps
        self.tick_ms = tick_ms

        # Gym-like spaces (as dicts for compatibility without gymnasium dep)
        self.observation_space = {'shape': (OBSERVATION_SIZE,), 'dtype': 'float32'}
        self.action_space = {'n': NUM_ACTIONS}

        self.sim = None
        self.agent = None
        self._step_count = 0
        self._prev_obs_snap = None
        self._prev_rew_snap = None

    def reset(self, seed: int = None) -> tuple[np.ndarray, dict]:
        """Reset environment. Returns (observation, info)."""
        if seed is not None:
            import random
            random.seed(seed)
            np.random.seed(seed)

        arena = generate_arena(**self.arena_kwargs)

        # First creature is the agent; rest get fallback AI
        self.agent = arena['creatures'][0]
        self.agent.behavior = None  # controlled by env.step()

        for c in arena['creatures'][1:]:
            c.behavior = StatWeightedBehavior()
            c.register_tick('behavior', 500, c._do_behavior)

        self.sim = Simulation(arena, tick_ms=self.tick_ms)
        self._step_count = 0

        # Initial snapshots
        self._prev_obs_snap = make_snapshot(self.agent)
        self._prev_rew_snap = make_reward_snapshot(self.agent)

        obs = self._get_obs()
        info = {'step': 0, 'alive_count': self.sim.alive_count}
        return obs, info

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        """Execute one step.

        Args:
            action: Action enum index for the agent creature

        Returns:
            (observation, reward, terminated, truncated, info)
        """
        # Execute the agent's action
        context = {
            'cols': self.sim.cols,
            'rows': self.sim.rows,
            'target': self._find_nearest_target(),
            'now': self.sim.now,
        }
        dispatch(self.agent, action, context)

        # Advance simulation (processes background AI ticks)
        self.sim.now += self.tick_ms
        self.sim.step_count += 1
        self._step_count += 1

        for c in self.sim.creatures:
            if c is not self.agent and c.is_alive:
                c.update(self.sim.now, self.sim.cols, self.sim.rows)

        # Compute reward
        curr_rew = make_reward_snapshot(self.agent)
        reward = compute_reward(self.agent, self._prev_rew_snap, curr_rew)
        self._prev_rew_snap = curr_rew

        # Get new observation
        obs = self._get_obs()

        # Termination conditions
        terminated = not self.agent.is_alive
        truncated = self._step_count >= self.max_steps

        info = {
            'step': self._step_count,
            'alive_count': self.sim.alive_count,
            'agent_hp': self.agent.stats.active[self.agent.stats.active.__class__.__mro__[0]] if False else None,
        }
        # Simpler info
        from classes.stats import Stat
        info = {
            'step': self._step_count,
            'alive_count': self.sim.alive_count,
            'agent_hp_ratio': (self.agent.stats.active[Stat.HP_CURR]() /
                               max(1, self.agent.stats.active[Stat.HP_MAX]())),
        }

        return obs, reward, terminated, truncated, info

    def _get_obs(self) -> np.ndarray:
        obs = build_observation(self.agent, self.sim.cols, self.sim.rows,
                                prev_snapshot=self._prev_obs_snap)
        self._prev_obs_snap = make_snapshot(self.agent)
        return np.array(obs, dtype=np.float32)

    def _find_nearest_target(self):
        from classes.world_object import WorldObject
        from classes.creature import Creature

        nearest = None
        nearest_dist = 999
        for obj in WorldObject.on_map(self.agent.current_map):
            if not isinstance(obj, Creature) or obj is self.agent or not obj.is_alive:
                continue
            dist = self.agent._sight_distance(obj)
            if dist < nearest_dist and self.agent.can_see(obj):
                nearest_dist = dist
                nearest = obj
        return nearest


class MultiAgentCreatureEnv:
    """Multi-agent environment. All creatures are agents.

    reset() → {uid: observation}
    step(actions: {uid: action}) → {uid: (obs, reward, terminated, info)}
    """

    def __init__(self, arena_kwargs: dict = None, max_steps: int = 1000,
                 tick_ms: int = 100):
        self.arena_kwargs = arena_kwargs or {
            'cols': 15, 'rows': 15, 'num_creatures': 6,
            'obstacle_density': 0.08,
        }
        self.max_steps = max_steps
        self.tick_ms = tick_ms
        self.sim = None
        self._step_count = 0
        self._obs_snaps: dict[int, dict] = {}
        self._rew_snaps: dict[int, dict] = {}

    def reset(self, seed: int = None) -> dict[int, np.ndarray]:
        """Reset. Returns {uid: observation} for all creatures."""
        if seed is not None:
            import random
            random.seed(seed)
            np.random.seed(seed)

        arena = generate_arena(**self.arena_kwargs)
        # All creatures are externally controlled — no behavior
        for c in arena['creatures']:
            c.behavior = None

        self.sim = Simulation(arena, tick_ms=self.tick_ms)
        self._step_count = 0

        observations = {}
        for c in self.sim.creatures:
            self._obs_snaps[c.uid] = make_snapshot(c)
            self._rew_snaps[c.uid] = make_reward_snapshot(c)
            obs = build_observation(c, self.sim.cols, self.sim.rows)
            observations[c.uid] = np.array(obs, dtype=np.float32)

        return observations

    def step(self, actions: dict[int, int]) -> dict:
        """Execute actions for all creatures.

        Args:
            actions: {creature_uid: action_index}

        Returns:
            {uid: {'obs': array, 'reward': float, 'terminated': bool}}
        """
        self.sim.now += self.tick_ms
        self.sim.step_count += 1
        self._step_count += 1

        # Execute all actions
        for c in self.sim.creatures:
            if not c.is_alive:
                continue
            action = actions.get(c.uid)
            if action is None:
                continue

            # Find nearest target for this creature
            from classes.world_object import WorldObject
            from classes.creature import Creature
            target = None
            nearest_dist = 999
            for obj in WorldObject.on_map(c.current_map):
                if not isinstance(obj, Creature) or obj is c or not obj.is_alive:
                    continue
                dist = c._sight_distance(obj)
                if dist < nearest_dist and c.can_see(obj):
                    nearest_dist = dist
                    target = obj

            context = {
                'cols': self.sim.cols,
                'rows': self.sim.rows,
                'target': target,
                'now': self.sim.now,
            }
            dispatch(c, action, context)

        # Process ticks (regen, etc.)
        for c in self.sim.creatures:
            if c.is_alive:
                c.process_ticks(self.sim.now)

        # Collect results
        results = {}
        for c in self.sim.creatures:
            prev_obs = self._obs_snaps.get(c.uid)
            prev_rew = self._rew_snaps.get(c.uid)

            obs = build_observation(c, self.sim.cols, self.sim.rows,
                                    prev_snapshot=prev_obs)
            curr_rew = make_reward_snapshot(c)
            reward = compute_reward(c, prev_rew, curr_rew) if prev_rew else 0.0

            self._obs_snaps[c.uid] = make_snapshot(c)
            self._rew_snaps[c.uid] = curr_rew

            results[c.uid] = {
                'obs': np.array(obs, dtype=np.float32),
                'reward': reward,
                'terminated': not c.is_alive,
            }

        return results

    @property
    def done(self) -> bool:
        return self.sim.alive_count <= 1 or self._step_count >= self.max_steps

    @property
    def agents(self) -> list:
        """Return list of alive creature UIDs."""
        return [c.uid for c in self.sim.creatures if c.is_alive]
