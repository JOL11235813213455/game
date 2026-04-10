"""Goal and spatial memory methods for Creature."""
from __future__ import annotations


# Max remembered locations per purpose
_MAX_MEMORY_PER_PURPOSE = 10


class GoalMixin:
    """Goal-setting, spatial memory, and pathfinding for Creature."""

    def remember_location(self, purpose: str, map_name: str, x: int, y: int, tick: int = 0):
        """Record a purposeful location in spatial memory.

        Deduplicates by (map_name, x, y). Updates tick if already known.
        """
        locs = self.known_locations.setdefault(purpose, [])
        # Check for existing entry at same coords
        for i, (mn, lx, ly, _) in enumerate(locs):
            if mn == map_name and lx == x and ly == y:
                locs[i] = (map_name, x, y, tick)
                return
        locs.append((map_name, x, y, tick))
        # Cap memory size
        if len(locs) > _MAX_MEMORY_PER_PURPOSE:
            locs.pop(0)

    def update_spatial_memory(self, tick: int = 0, zone_registry=None):
        """Check current location against purpose zones and tile purpose.

        Called each tick to build up the creature's spatial knowledge.
        """
        tile = self.current_map.tiles.get(self.location)
        map_name = getattr(self.current_map, 'name', '') or ''
        x, y, z = self.location.x, self.location.y, self.location.z

        # Check tile-level purpose
        if tile and getattr(tile, 'purpose', None):
            self.remember_location(tile.purpose, map_name, x, y, tick)

        # Check zone registry
        if zone_registry:
            purposes = zone_registry.get_purposes(map_name, x, y, z)
            for p in purposes:
                self.remember_location(p, map_name, x, y, tick)

    def set_goal(self, purpose: str, target_map: str, target_x: int, target_y: int,
                 zone_id: int = None, tick: int = 0):
        """Set a new goal: go to a location and perform a purpose-aligned action."""
        self.current_goal = purpose
        self.goal_target = (target_map, target_x, target_y)
        self.goal_target_zone_id = zone_id
        self.goal_started_tick = tick
        # Calculate initial distance for progress tracking
        if getattr(self.current_map, 'name', '') == target_map:
            self.goal_prev_distance = abs(self.location.x - target_x) + abs(self.location.y - target_y)
        else:
            self.goal_prev_distance = 100.0  # cross-map default

    def clear_goal(self):
        """Clear the current goal (completed or abandoned)."""
        self.current_goal = None
        self.goal_target = None
        self.goal_target_zone_id = None
        self.goal_started_tick = 0
        self.goal_prev_distance = 0.0

    def goal_distance(self) -> float:
        """Manhattan distance to current goal target. Returns inf if no goal or cross-map."""
        if self.goal_target is None:
            return float('inf')
        target_map, tx, ty = self.goal_target
        if getattr(self.current_map, 'name', '') != target_map:
            return 100.0  # cross-map placeholder
        return abs(self.location.x - tx) + abs(self.location.y - ty)

    def goal_progress(self) -> float:
        """Distance decrease since last check. Positive = getting closer."""
        if self.goal_target is None:
            return 0.0
        current_dist = self.goal_distance()
        progress = self.goal_prev_distance - current_dist
        self.goal_prev_distance = current_dist
        return progress

    def at_goal(self) -> bool:
        """True if creature is at or inside the goal target."""
        if self.goal_target is None:
            return False
        target_map, tx, ty = self.goal_target
        if getattr(self.current_map, 'name', '') != target_map:
            return False
        return self.goal_distance() <= 1.0  # within 1 tile

    def pick_goal_target(self, purpose: str, zone_registry=None) -> tuple | None:
        """Pick the best known location for a purpose.

        Prefers: zones on current map > remembered tiles on current map >
                 zones on other maps > remembered tiles on other maps.
        Returns (map_name, x, y, zone_id_or_none) or None.
        """
        map_name = getattr(self.current_map, 'name', '') or ''

        # Try zone registry first (most reliable)
        if zone_registry:
            zone, dist = zone_registry.get_nearest_zone(
                map_name, purpose, self.location.x, self.location.y)
            if zone is not None:
                cx, cy = zone_registry.get_center(zone)
                return (map_name, int(cx), int(cy), zone.id)

        # Try spatial memory
        locs = self.known_locations.get(purpose, [])
        # Prefer current map
        current_map_locs = [(mn, x, y, t) for mn, x, y, t in locs if mn == map_name]
        if current_map_locs:
            # Pick closest
            best = min(current_map_locs,
                       key=lambda l: abs(l[1] - self.location.x) + abs(l[2] - self.location.y))
            return (best[0], best[1], best[2], None)

        # Other maps
        if locs:
            loc = locs[-1]  # most recently discovered
            return (loc[0], loc[1], loc[2], None)

        return None

    def direction_to_goal(self) -> tuple[int, int]:
        """Return (dx, dy) unit vector toward goal. (0,0) if no goal or at goal."""
        if self.goal_target is None:
            return (0, 0)
        target_map, tx, ty = self.goal_target
        if getattr(self.current_map, 'name', '') != target_map:
            return (0, 0)  # cross-map -- needs map graph
        dx = tx - self.location.x
        dy = ty - self.location.y
        if dx == 0 and dy == 0:
            return (0, 0)
        # Normalize to -1/0/1
        ndx = (1 if dx > 0 else (-1 if dx < 0 else 0))
        ndy = (1 if dy > 0 else (-1 if dy < 0 else 0))
        return (ndx, ndy)
