from __future__ import annotations
import random
from classes.maps import Map, MapKey, DIRECTION_BOUNDS
from classes.inventory import Inventory
from classes.world_object import WorldObject
from classes.stats import Stat, Stats


class Creature(WorldObject):
    """Single creature class for players, NPCs, and monsters.

    There are no subclasses. All behavioral differences are driven by
    behavior modules assigned to ``self.behavior``.
    """
    sprite_name = 'player'
    z_index     = 3
    collision   = True

    def __init__(
        self,
        current_map: Map,
        location: MapKey = MapKey(),
        name: str = None,
        species: str = None,
        stats: dict = None,
        items: list = None,
        behavior: object = None,
        move_interval: int = 1000,
    ):
        super().__init__(current_map=current_map, location=location)
        self.name = name
        self.species = species

        from data.db import SPECIES
        species_data = SPECIES.get(species, {}) if species else {}
        self.tile_scale     = species_data.get('tile_scale',     self.__class__.tile_scale)
        self.sprite_name    = species_data.get('sprite_name',    self.__class__.sprite_name)
        self.composite_name = species_data.get('composite_name', self.__class__.composite_name)

        # Build Stats from species defaults + overrides
        species_stats = {k: v for k, v in species_data.items() if isinstance(k, Stat)}
        merged = {**species_stats, **(stats or {})}
        hd = merged.pop(Stat.HD, 6)
        self.stats = Stats(base_stats=merged, hit_dice=hd)

        self.inventory = Inventory(items=items or [])
        self.map_stack: list[tuple[Map, MapKey]] = []

        # Dialogue tree placeholder — will hold dialogue data when fleshed out
        self.dialogue = None

        # Behavior module for non-player creatures (NPC AI, monster AI, etc.)
        self.behavior = behavior
        self.move_interval = move_interval
        self._last_move = 0

    # -- Experience ---------------------------------------------------------

    def gain_exp(self, amount: int):
        self.stats.gain_exp(amount)

    # -- NPC update (driven by behavior module) -----------------------------

    def update(self, now: int, cols: int, rows: int):
        """Called each frame for non-player creatures."""
        if self.behavior is None:
            return
        if now - self._last_move >= self.move_interval:
            self.behavior.think(self, cols, rows)
            self._last_move = now
        else:
            self.play_animation('idle')

    # -- Movement -----------------------------------------------------------

    _DIR_BEHAVIORS = {
        (0, -1): 'walk_north', (0, 1): 'walk_south',
        (-1, 0): 'walk_west',  (1, 0): 'walk_east',
        (-1, -1): 'walk_north', (1, -1): 'walk_north',
        (-1,  1): 'walk_south', (1,  1): 'walk_south',
    }

    @staticmethod
    def _tile_blocked(game_map, x: int, y: int) -> bool:
        """Return True if any WorldObject with collision=True occupies (x, y)."""
        from classes.world_object import WorldObject
        from classes.inventory import Structure
        for obj in WorldObject.colliders_on_map(game_map):
            if isinstance(obj, Structure):
                ox, oy = obj.location.x, obj.location.y
                if (x - ox, y - oy) in obj.collision_mask:
                    return True
            elif obj.location.x == x and obj.location.y == y:
                return True
        return False

    def move(self, dx: int, dy: int, cols: int, rows: int):
        nx = max(0, min(cols - 1, self.location.x + dx))
        ny = max(0, min(rows - 1, self.location.y + dy))
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
        # Auto-link: if the new tile has link_auto, teleport immediately
        landed = self.current_map.tiles.get(self.location)
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

    # -- Inventory ----------------------------------------------------------

    def transfer_item(self, item, source, target):
        tile = self.current_map.tiles.get(self.location)
        accessible = [self.inventory]
        if tile:
            accessible.append(tile.inventory)
            for creature in WorldObject.on_map(self.current_map):
                if isinstance(creature, Creature) and creature is not self and creature.location == self.location:
                    accessible.append(creature.inventory)
        if source not in accessible or target not in accessible:
            return False
        if item not in source.items:
            return False
        source.items.remove(item)
        target.items.append(item)
        return True


# ---------------------------------------------------------------------------
# Built-in behavior modules
# ---------------------------------------------------------------------------

class RandomWanderBehavior:
    """Simple behavior: move in a random direction each think tick."""

    def think(self, creature: Creature, cols: int, rows: int):
        dx, dy = random.choice([
            (-1, -1), (0, -1), (1, -1),
            (-1,  0),          (1,  0),
            (-1,  1), (0,  1), (1,  1),
        ])
        creature.move(dx, dy, cols, rows)
