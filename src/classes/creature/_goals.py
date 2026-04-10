"""Goal and spatial memory methods for Creature."""
from __future__ import annotations


# Max remembered locations per purpose
_MAX_MEMORY_PER_PURPOSE = 10

# Rough cost estimate per map transition for distance calculations.
# Represents "how many tiles of walking" one map hop is worth.
_MAP_TRANSITION_COST = 50


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

    def update_spatial_memory(self, tick: int = 0):
        """Scan visible tiles and objects for purpose, remember locations.

        Sources of purpose (all contribute to spatial memory):
        - Tiles: tile.purpose (full sight range)
        - WorldObjects: structures, creatures, items with purpose set
          (range = sight * obj.purpose_distance)
        """
        from classes.stats import Stat
        from classes.maps import MapKey
        from classes.world_object import WorldObject
        map_name = getattr(self.current_map, 'name', '') or ''
        cx, cy, z = self.location.x, self.location.y, self.location.z
        sight = max(1, self.stats.active[Stat.SIGHT_RANGE]())

        # Scan tiles at full sight range
        for dx in range(-sight, sight + 1):
            for dy in range(-sight, sight + 1):
                if abs(dx) + abs(dy) > sight:
                    continue
                tx, ty = cx + dx, cy + dy
                tile = self.current_map.tiles.get(MapKey(tx, ty, z))
                if tile and getattr(tile, 'purpose', None):
                    self.remember_location(tile.purpose, map_name, tx, ty, tick)

        # Scan visible objects (structures, creatures, items) with purpose
        for obj in WorldObject.on_map(self.current_map):
            if obj is self or not getattr(obj, 'purpose', None):
                continue
            dist = abs(cx - obj.location.x) + abs(cy - obj.location.y)
            max_range = sight * getattr(obj, 'purpose_distance', 0.5)
            if dist <= max_range:
                self.remember_location(obj.purpose, map_name,
                                       obj.location.x, obj.location.y, tick)

    def set_goal(self, purpose: str, target_map: str, target_x: int, target_y: int,
                 tick: int = 0):
        """Set a new goal: go to a location and perform a purpose-aligned action."""
        self.current_goal = purpose
        self.goal_target = (target_map, target_x, target_y)
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
        self.goal_started_tick = 0
        self.goal_prev_distance = 0.0

    def goal_distance(self, map_graph=None) -> float:
        """Manhattan distance to current goal target.

        If goal is on a different map and map_graph is provided,
        computes: distance_to_exit_tile + map_transitions * _MAP_TRANSITION_COST.
        Returns inf if no goal, or if cross-map with no path.
        """
        if self.goal_target is None:
            return float('inf')
        target_map, tx, ty = self.goal_target
        cur_map_name = getattr(self.current_map, 'name', '') or ''

        if cur_map_name == target_map:
            return abs(self.location.x - tx) + abs(self.location.y - ty)

        # Cross-map: use map_graph if available
        if map_graph is not None:
            route = self._cross_map_exit_info(target_map, map_graph)
            if route is not None:
                exit_x, exit_y, remaining_transitions = route
                dist_to_exit = abs(self.location.x - exit_x) + abs(self.location.y - exit_y)
                return dist_to_exit + remaining_transitions * _MAP_TRANSITION_COST
            # No path found
            return float('inf')

        # Fallback: rough cross-map placeholder
        return 100.0

    def goal_progress(self, map_graph=None) -> float:
        """Distance decrease since last check. Positive = getting closer."""
        if self.goal_target is None:
            return 0.0
        current_dist = self.goal_distance(map_graph)
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

    def pick_goal_target(self, purpose: str) -> tuple | None:
        """Pick the best known location for a purpose from spatial memory.

        Prefers current map (closest). Falls back to other maps.
        Returns (map_name, x, y) or None.
        """
        map_name = getattr(self.current_map, 'name', '') or ''

        locs = self.known_locations.get(purpose, [])
        # Prefer current map, closest first
        current_map_locs = [(mn, x, y, t) for mn, x, y, t in locs if mn == map_name]
        if current_map_locs:
            best = min(current_map_locs,
                       key=lambda l: abs(l[1] - self.location.x) + abs(l[2] - self.location.y))
            return (best[0], best[1], best[2])

        # Other maps — most recently discovered
        if locs:
            loc = locs[-1]
            return (loc[0], loc[1], loc[2])

        return None

    def direction_to_goal(self, map_graph=None) -> tuple[int, int]:
        """Return (dx, dy) unit vector toward goal. (0,0) if no goal or at goal.

        If the goal is on a different map and map_graph is provided,
        returns direction toward the exit tile that leads closer to the
        target map, rather than the final destination coordinates.
        """
        if self.goal_target is None:
            return (0, 0)
        target_map, tx, ty = self.goal_target
        cur_map_name = getattr(self.current_map, 'name', '') or ''

        if cur_map_name != target_map and map_graph is not None:
            # Cross-map: navigate toward the exit tile
            route = self._cross_map_exit_info(target_map, map_graph)
            if route is not None:
                exit_x, exit_y, _ = route
                dx = exit_x - self.location.x
                dy = exit_y - self.location.y
                if dx == 0 and dy == 0:
                    return (0, 0)
                ndx = (1 if dx > 0 else (-1 if dx < 0 else 0))
                ndy = (1 if dy > 0 else (-1 if dy < 0 else 0))
                return (ndx, ndy)
            # No path through map graph
            return (0, 0)

        if cur_map_name != target_map:
            return (0, 0)  # cross-map without graph -- can't navigate

        dx = tx - self.location.x
        dy = ty - self.location.y
        if dx == 0 and dy == 0:
            return (0, 0)
        # Normalize to -1/0/1
        ndx = (1 if dx > 0 else (-1 if dx < 0 else 0))
        ndy = (1 if dy > 0 else (-1 if dy < 0 else 0))
        return (ndx, ndy)

    def plan_cross_map_route(self, target_map: str, map_graph) -> tuple | None:
        """Plan a route to another map using the map graph.

        Returns the next step: (exit_x, exit_y) on current map to reach
        the linking tile that gets us closer to target_map.
        Returns None if no path exists or already on target map.
        """
        route = self._cross_map_exit_info(target_map, map_graph)
        if route is None:
            return None
        exit_x, exit_y, _ = route
        return (exit_x, exit_y)

    def _cross_map_exit_info(self, target_map: str, map_graph) -> tuple | None:
        """Internal: find exit tile info for cross-map navigation.

        Returns (exit_x, exit_y, remaining_transitions) or None.
        exit_x/exit_y are coordinates on the current map of the linking
        tile that leads toward target_map.
        remaining_transitions is how many more map hops after this one.
        """
        cur_map_name = getattr(self.current_map, 'name', '') or ''
        if cur_map_name == target_map:
            return None

        detailed = map_graph.find_path_detailed(cur_map_name, target_map)
        if not detailed:
            return None

        # First step: (current_map, exit_x, exit_y, next_map, entry_x, entry_y)
        first_step = detailed[0]
        exit_x, exit_y = first_step[1], first_step[2]
        remaining_transitions = len(detailed)

        # If there are multiple connections to the same next map, pick closest
        next_map = first_step[3]
        conns = map_graph.get_connections(cur_map_name)
        candidates = [(sx, sy) for dm, sx, sy, _, _ in conns if dm == next_map]
        if len(candidates) > 1:
            # Pick the exit tile closest to creature's current position
            best = min(candidates,
                       key=lambda c: abs(c[0] - self.location.x) + abs(c[1] - self.location.y))
            exit_x, exit_y = best

        return (exit_x, exit_y, remaining_transitions)
