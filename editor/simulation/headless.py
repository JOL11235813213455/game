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

    def __init__(self, arena: dict, tick_ms: int = 500,
                 hunger_drain_enabled: bool = True,
                 combat_enabled: bool = True,
                 gestation_enabled: bool = True,
                 fatigue_enabled: bool = True):
        """Initialize simulation from an arena dict.

        Args:
            arena: dict from generate_arena() with map, creatures, cols, rows
            tick_ms: milliseconds per simulation step
            hunger_drain_enabled: when False, every creature spawned in
                this simulation has its hunger drain disabled and stays
                at its initial hunger value indefinitely. Used by early
                curriculum stages so creatures can learn to navigate
                without starvation pressure.
            combat_enabled: when False, MELEE_ATTACK / RANGED_ATTACK /
                GRAPPLE actions short-circuit to a noop in dispatch.
                Used by early curriculum stages so creatures cannot
                kill each other.
            gestation_enabled: when False, the daily lifecycle pass
                skips egg gestation/hatching entirely. Used by stages
                where reproduction is not yet active.
            fatigue_enabled: when False, creatures never accumulate
                sleep debt or fatigue. Used by early curriculum stages
                so creatures can learn without rest pressure.
        """
        self.game_map = arena['map']
        self.creatures = list(arena['creatures'])
        self.cols = arena['cols']
        self.rows = arena['rows']
        self.tick_ms = tick_ms
        self.now = 0
        self.step_count = 0

        # Curriculum env toggles — applied to every spawned creature
        self.hunger_drain_enabled = hunger_drain_enabled
        self.combat_enabled = combat_enabled
        self.gestation_enabled = gestation_enabled
        self.fatigue_enabled = fatigue_enabled
        if not hunger_drain_enabled:
            for c in self.creatures:
                c._hunger_drain = 0.0
        if not fatigue_enabled:
            for c in self.creatures:
                c.sleep_debt = 0
                c._fatigue_level = 0

        # Rebuild the map's spatial grid from scratch. The arena generator
        # constructs creatures with locations, but if it did so before
        # the Creature.location property setter was in place (e.g. via
        # direct attribute assignment in older code paths), some cells
        # may be missing entries. Rebuilding here is cheap and ensures
        # the sight cache queries get correct results from tick 0.
        if hasattr(self.game_map, 'rebuild_spatial_index'):
            self.game_map.rebuild_spatial_index()

        # World data for god system
        from classes.gods import WorldData
        self.world_data = WorldData()

        # Game clock — drives schedules, day/night, temporal observations.
        # Convention: 1 tick (500ms) = 1 game minute, so 1 game hour = 60
        # ticks and 1 full game day = 1440 ticks (~12 real minutes).
        from main.game_clock import GameClock
        self.game_clock = GameClock(start_hour=8.0)
        self._last_clock_tick = 0
        # Track the integer game day so we can fire daily ticks (eggs
        # gestating, hatching) exactly once per day boundary.
        self._last_game_day = int(self.game_clock.day)

        # Per-creature state tracking
        self._obs_snapshots: dict[int, dict] = {}  # uid → prev observation snapshot
        self._reward_snapshots: dict[int, dict] = {}  # uid → prev reward snapshot

        # Initialize snapshots
        for c in self.creatures:
            self._obs_snapshots[c.uid] = make_snapshot(c)
            self._reward_snapshots[c.uid] = make_reward_snapshot(c)

    def _tick_lifecycle_day(self):
        """Daily population tick: gestation + hatching.

        Walks every Egg in the world (creature inventories and tile
        inventories), advances each by one game day, and hatches any
        that are ready. Hatched creatures appear at the carrier's or
        tile's location and are appended to ``self.creatures`` so the
        next ``step()`` will iterate over them like any other creature.

        This is the entry point for births in the simulation. Pairings
        produce eggs (via :meth:`Creature.propose_pairing` →
        :meth:`Creature._execute_pairing`); this method makes those
        eggs eventually become living creatures.

        Curriculum-gated: when ``self.gestation_enabled`` is False
        (early stages), this method is a noop. Eggs that exist still
        sit in inventories untouched.
        """
        if not self.gestation_enabled:
            return
        from classes.inventory import Egg

        # --- Phase 1: tick gestation on every egg in the world ---
        # Track (egg, owner_kind, owner_ref, location) so phase 2 can
        # remove ready eggs from their containers and place the
        # hatchlings on the right tile.
        eggs_seen: list[tuple] = []

        # Eggs in creature inventories (pregnancies + carried eggs)
        for c in self.creatures:
            if not c.is_alive:
                continue
            for item in c.inventory.items:
                if isinstance(item, Egg):
                    carried = (getattr(c, 'is_pregnant', False)
                               and getattr(c, '_pregnancy_egg', None) is item)
                    item.tick_gestation(carried_by_mother=carried)
                    eggs_seen.append((item, 'creature', c, c.location))

        # Eggs on tiles (abomination drops, lost-and-found)
        for key, tile in self.game_map.tiles.items():
            for item in tile.inventory.items:
                if isinstance(item, Egg):
                    item.tick_gestation(carried_by_mother=False)
                    eggs_seen.append((item, 'tile', tile, key))

        # --- Phase 2: hatch ready eggs into live creatures ---
        for egg, owner_kind, owner_ref, loc in eggs_seen:
            if not egg.ready_to_hatch:
                continue
            child = egg.hatch(self.game_map, loc)
            if child is None:
                continue
            # Remove the egg from its container, end pregnancy if applicable
            if owner_kind == 'creature':
                if egg in owner_ref.inventory.items:
                    owner_ref.inventory.items.remove(egg)
                if (getattr(owner_ref, 'is_pregnant', False)
                        and getattr(owner_ref, '_pregnancy_egg', None) is egg):
                    owner_ref.end_pregnancy()
            else:  # tile
                if egg in owner_ref.inventory.items:
                    owner_ref.inventory.items.remove(egg)

            # Welcome the newborn into the simulation roster
            self.creatures.append(child)
            self._obs_snapshots[child.uid] = make_snapshot(child)
            self._reward_snapshots[child.uid] = make_reward_snapshot(child)

        # --- Phase 3: fatigue accumulation for creatures that didn't sleep ---
        if self.fatigue_enabled:
            for c in self.creatures:
                if not c.is_alive:
                    continue
                if not getattr(c, 'is_sleeping', False):
                    c.add_sleep_debt(1)
                c.age += 1

    def step(self) -> list[dict]:
        """Advance one simulation step.

        Returns list of dicts, one per creature:
            {creature, observation, reward, alive}
        """
        self.now += self.tick_ms
        self.step_count += 1

        # Clear sound buffer at the START of the tick. Action handlers
        # called during the creature update pass will emit fresh sounds
        # into this empty buffer; the perception delivery pass at the
        # end of the tick reads them.
        from classes.sound import clear_sounds, deliver_sounds
        clear_sounds(self.game_map)

        # Advance game clock: 1 tick = 1 game minute, matching the hunger
        # drain convention (2.0 / 1440 ticks = full depletion per game day).
        # GameClock.update takes real seconds and maps 1 real second = 1
        # game minute, so advance by exactly 1 real-second per tick.
        self.game_clock.update(1.0)

        # Detect day boundary and fire the daily lifecycle pass exactly
        # once per game day (eggs gestating + hatching). Loop in case
        # multiple days slipped — defensive, shouldn't normally happen.
        current_day = int(self.game_clock.day)
        if current_day != self._last_game_day:
            for _ in range(max(1, current_day - self._last_game_day)):
                self._tick_lifecycle_day()
            self._last_game_day = current_day

        # Process all creature ticks (behavior, regen, etc.)
        for c in self.creatures:
            if c.is_alive:
                c.update(self.now, self.cols, self.rows)

        # Deliver any sound events that fired during this tick to
        # creatures within range. Done after all creature updates so
        # ordering doesn't matter — every creature sees every sound
        # emitted on this tick (including ones from creatures processed
        # later in the loop).
        for c in self.creatures:
            if c.is_alive:
                deliver_sounds(c, self.step_count)

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
                                   game_clock=self.game_clock,
                                   observation_tick=self.step_count)

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
