from __future__ import annotations
import random
from classes.maps import MapKey, DIRECTION_BOUNDS
from classes.stats import Stat
from classes.creature._constants import SIZE_FOOTPRINT, SIZE_UNITS, TILE_CAPACITY


class MovementMixin:
    """Movement and map transition methods for Creature."""

    _DIR_BEHAVIORS = {
        (0, -1): 'walk_north', (0, 1): 'walk_south',
        (-1, 0): 'walk_west',  (1, 0): 'walk_east',
        (-1, -1): 'walk_north', (1, -1): 'walk_north',
        (-1,  1): 'walk_south', (1,  1): 'walk_south',
    }

    def _get_footprint_tiles(self, x: int, y: int) -> list[tuple[int, int]]:
        """Return list of (x, y) tiles this creature would occupy at position (x, y)."""
        tiles = [(x, y)]
        for ox, oy in SIZE_FOOTPRINT.get(self.size, []):
            tiles.append((x + ox, y + oy))
        return tiles

    def _tile_blocked(self, game_map, x: int, y: int) -> bool:
        """Return True if this creature cannot fit at anchor (x, y).

        Checks ALL footprint tiles for walkability, structure collision,
        and size-based capacity. Tiny creatures always fit.
        """
        from classes.world_object import WorldObject
        from classes.inventory import Structure
        from classes.creature import Creature

        my_units = SIZE_UNITS.get(self.size, 4)

        # Tiny always fits
        if my_units == 0:
            return False

        # Check every tile in footprint
        for fx, fy in self._get_footprint_tiles(x, y):
            tile = game_map.tiles.get(MapKey(fx, fy, self.location.z))
            if not tile or not tile.walkable:
                return True  # footprint tile doesn't exist or unwalkable

            used_units = 0
            for obj in WorldObject.colliders_on_map(game_map):
                if isinstance(obj, Structure):
                    ox, oy = obj.location.x, obj.location.y
                    if (fx - ox, fy - oy) in obj.collision_mask:
                        return True
                elif isinstance(obj, Creature) and obj is not self:
                    obj_tiles = obj._get_footprint_tiles(obj.location.x, obj.location.y)
                    if (fx, fy) in obj_tiles:
                        if self._is_family_passthrough(obj):
                            continue
                        used_units += SIZE_UNITS.get(obj.size, 4)

            if (used_units + my_units) > TILE_CAPACITY:
                return True

        return False

    def _is_family_passthrough(self, other) -> bool:
        """Return True if self and other are parent-child and child is not adult."""
        from classes.creature import Creature
        # Am I this creature's child (and I'm not adult)?
        if self.is_child and (self.mother_uid == other.uid or self.father_uid == other.uid):
            return True
        # Is this creature my child (and they're not adult)?
        if (isinstance(other, Creature) and other.is_child and
                (other.mother_uid == self.uid or other.father_uid == self.uid)):
            return True
        return False

    def move(self, dx: int, dy: int, cols: int, rows: int):
        # Clamp so entire footprint stays in bounds
        foot = SIZE_FOOTPRINT.get(self.size, [])
        max_ox = max((ox for ox, _ in foot), default=0)
        max_oy = max((oy for _, oy in foot), default=0)
        nx = max(0, min(cols - 1 - max_ox, self.location.x + dx))
        ny = max(0, min(rows - 1 - max_oy, self.location.y + dy))
        current_tile = self.current_map.tiles.get(self.location)
        target = self.current_map.tiles.get(MapKey(nx, ny, self.location.z))
        if not (target and target.walkable):
            return
        if current_tile and (dx, dy) in DIRECTION_BOUNDS:
            exit_attr, entry_attr = DIRECTION_BOUNDS[(dx, dy)]
            if not getattr(current_tile.bounds, exit_attr) or not getattr(target.bounds, entry_attr):
                return
        if self._tile_blocked(self.current_map, nx, ny):
            return
        self.location = self.location._replace(x=nx, y=ny)
        behavior = self._DIR_BEHAVIORS.get((dx, dy), 'walk_south')
        self.play_animation(behavior)

        # Trap check on the landed tile
        landed = self.current_map.tiles.get(self.location)
        if landed:
            self._check_trap(landed)

        # Auto-link: if the new tile has link_auto, teleport immediately
        if landed and landed.link_auto and landed.linked_map:
            self._do_link(landed)

    # -- Map transitions ----------------------------------------------------

    def _do_link(self, tile):
        """Teleport to another map/location based on tile link fields."""
        from data.db import MAPS
        target_map = MAPS.get(tile.linked_map)
        if target_map is None:
            return False
        self.map_stack.append((self.current_map, self.location))
        self.current_map = target_map
        if tile.linked_location is not None:
            self.location = tile.linked_location
        else:
            self.location = MapKey(*target_map.entrance, 0)
        return True

    def enter(self):
        # Check tile link (enter-key triggered) first
        tile = self.current_map.tiles.get(self.location)
        if tile and tile.linked_map and not tile.link_auto:
            if self._do_link(tile):
                return True
        # Check tile nested maps
        if tile and tile.nested_map is not None:
            self.map_stack.append((self.current_map, self.location))
            self.current_map = tile.nested_map
            self.location = MapKey(*self.current_map.entrance, 0)
            return True
        # Check structure entry points
        from classes.inventory import Structure
        from classes.world_object import WorldObject
        from data.db import MAPS
        px, py = self.location.x, self.location.y
        for s in WorldObject.on_map(self.current_map):
            if not isinstance(s, Structure) or not s.nested_map_name:
                continue
            offset = (px - s.location.x, py - s.location.y)
            offset_key = f'{offset[0]},{offset[1]}'
            if offset_key in s.entry_points or offset in s.footprint:
                nested = MAPS.get(s.nested_map_name)
                if nested is None:
                    continue
                self.map_stack.append((self.current_map, self.location))
                self.current_map = nested
                ep = s.entry_points.get(offset_key)
                if ep:
                    self.location = MapKey(ep[0], ep[1], 0)
                else:
                    self.location = MapKey(*self.current_map.entrance, 0)
                return True
        return False

    def exit(self):
        entrance = MapKey(*self.current_map.entrance, 0)
        if self.location == entrance:
            if self.map_stack:
                self.current_map, self.location = self.map_stack.pop()
                return True
        return False

    def flee(self, threat, cols: int, rows: int) -> bool:
        """Move one tile away from the threat creature.

        Picks the direction that maximizes distance. Costs stamina (run cost).
        Returns True if moved.
        """
        # Stamina cost for fleeing (running)
        stam_cost = 3
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stam_cost:
            return False
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stam_cost

        # Pick direction away from threat
        dx = self.location.x - threat.location.x
        dy = self.location.y - threat.location.y
        # Normalize to -1/0/1
        mdx = (1 if dx > 0 else (-1 if dx < 0 else 0))
        mdy = (1 if dy > 0 else (-1 if dy < 0 else 0))

        if mdx == 0 and mdy == 0:
            # On same tile — pick random direction
            mdx, mdy = random.choice([(1,0),(-1,0),(0,1),(0,-1)])

        old_loc = self.location
        self.move(mdx, mdy, cols, rows)
        return self.location != old_loc

    def follow(self, target, cols: int, rows: int) -> bool:
        """Move one tile toward the target creature.

        Returns True if moved.
        """
        dx = target.location.x - self.location.x
        dy = target.location.y - self.location.y
        mdx = (1 if dx > 0 else (-1 if dx < 0 else 0))
        mdy = (1 if dy > 0 else (-1 if dy < 0 else 0))

        if mdx == 0 and mdy == 0:
            return False  # Already at target

        old_loc = self.location
        self.move(mdx, mdy, cols, rows)
        return self.location != old_loc

    def run(self, dx: int, dy: int, cols: int, rows: int) -> bool:
        """Move at 150% speed (immediate) with stamina cost.

        Returns True if moved.
        """
        stam_cost = 3
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stam_cost:
            return False
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stam_cost

        old_loc = self.location
        self.move(dx, dy, cols, rows)
        return self.location != old_loc

    def sneak(self, dx: int, dy: int, cols: int, rows: int) -> bool:
        """Move stealthily with a small stamina cost.

        Activates stealth bonus while sneaking.
        Returns True if moved.
        """
        stam_cost = 1
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stam_cost:
            return False
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stam_cost

        old_loc = self.location
        self.move(dx, dy, cols, rows)
        return self.location != old_loc
