"""
World manager for multi-map creature management.

Handles off-screen maps at reduced tick rates: creatures on maps
the player isn't currently viewing get simplified updates (hunger,
fatigue, age) once per game-second instead of every frame.
"""
from __future__ import annotations


class WorldManager:
    """Manages creature ticking across multiple maps."""

    def __init__(self, slow_interval_ms: int = 30000):
        """Args:
            slow_interval_ms: how often off-map creatures tick (default 30s = ~1 game hour)
        """
        self.slow_interval_ms = slow_interval_ms
        self._last_slow_tick: int = 0

    def tick_all_maps(self, active_map, all_maps: list, now: int,
                      cols: int, rows: int, scheduler=None):
        """Tick creatures on all maps.

        Active map: full update via scheduler (perception, behavior, etc.)
        Other maps: slow tick for hunger/fatigue/age only.
        """
        from classes.creature import Creature

        # Active map: full updates (optionally staggered)
        active_creatures = Creature.on_same_map(active_map)
        if scheduler:
            due = scheduler.due_this_frame(active_creatures)
        else:
            due = active_creatures
        for c in due:
            if c.is_alive:
                c.update(now, cols, rows)

        # Off-map: slow tick at reduced rate
        if now - self._last_slow_tick >= self.slow_interval_ms:
            self._last_slow_tick = now
            active_id = id(active_map)
            for m in all_maps:
                if id(m) == active_id:
                    continue
                for c in Creature.on_same_map(m):
                    if c.is_alive:
                        self._slow_tick(c, now)

    def _slow_tick(self, creature, now: int):
        """Minimal update for off-map creatures: hunger, fatigue, age."""
        if hasattr(creature, '_do_hunger_tick'):
            creature._do_hunger_tick(now)
        if hasattr(creature, '_do_water_tick'):
            creature._do_water_tick(now)
