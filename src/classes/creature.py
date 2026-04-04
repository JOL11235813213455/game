from __future__ import annotations
from enum import Enum
import random
from classes.maps import Map, MapKey, BOUND_TRAVERSABLE, DIRECTION_BOUNDS
from classes.inventory import Inventory
from classes.world_object import WorldObject
from classes.levels import level_from_exp, cumulative_exp

class Stat(Enum):
    LVL             = 'level'
    HD              = 'hit dice'
    EXP             = 'cumulative xp'
    MHP             = 'max health'
    CHP             = 'health'

    STR             = 'strength'
    INT             = 'intelligence'
    LCK             = 'luck'
    PER             = 'perception'
    CHR             = 'charisma'
    AGL             = 'agility'
    CON             = 'constitution'
    ARM             = 'armor'

def level_up_heal(creature, old_level, new_level):
    hd = creature.stats.get(Stat.HD, 6)
    con = creature.stats.get(Stat.CON, 0)
    roll = random.randint(1, hd) + con
    creature.stats[Stat.MHP] = creature.stats.get(Stat.MHP, 0) + roll
    creature.stats[Stat.CHP] = int(creature.stats[Stat.MHP] * 1)

class Creature(WorldObject):
    sprite_name = 'player'
    z_index     = 3

    def __init__(
        self
        ,current_map: Map
        ,location: MapKey = MapKey()
        ,name: str = None
        ,species: str = None
        ,stats: dict = {}
        ,items: list = []
        ):
        super().__init__(current_map=current_map, location=location)
        self.name = name
        self.species = species
        from data.db import SPECIES
        species_data  = SPECIES.get(species, {}) if species else {}
        self.tile_scale  = species_data.get('tile_scale',  self.__class__.tile_scale)
        self.sprite_name = species_data.get('sprite_name', self.__class__.sprite_name)
        species_stats = {k: v for k, v in species_data.items() if isinstance(k, Stat)}
        self.stats = {Stat.MHP: 1, Stat.CHP: 1, **species_stats, **stats}
        self._reconcile_exp_level()
        self.inventory = Inventory(items=items)
        self.map_stack: list[tuple[Map, MapKey]] = []
        self.on_level_up: list[callable] = [level_up_heal]
        self.hostile = False

    def _reconcile_exp_level(self):
        has_exp = Stat.EXP in self.stats
        has_lvl = Stat.LVL in self.stats
        if has_exp:
            lvl, _, _ = level_from_exp(self.stats[Stat.EXP])
            self.stats[Stat.LVL] = lvl
        elif has_lvl:
            self.stats[Stat.EXP] = cumulative_exp(self.stats[Stat.LVL])
        else:
            self.stats[Stat.LVL] = 0
            self.stats[Stat.EXP] = 0

    def gain_exp(self, amount: int):
        old_level = self.stats.get(Stat.LVL, 0)
        self.stats[Stat.EXP] = self.stats.get(Stat.EXP, 0) + amount
        self._reconcile_exp_level()
        if self.stats[Stat.LVL] > old_level:
            for callback in self.on_level_up:
                callback(self, old_level, self.stats[Stat.LVL])

    def move(self, dx: int, dy: int, cols: int, rows: int):
        nx = max(0, min(cols - 1, self.location.x + dx))
        ny = max(0, min(rows - 1, self.location.y + dy))
        current_tile = self.current_map.tiles.get(self.location)
        target = self.current_map.tiles.get(MapKey(self.location.w, nx, ny, self.location.z))
        if not (target and target.walkable):
            return
        if current_tile and (dx, dy) in DIRECTION_BOUNDS:
            exit_attr, entry_attr = DIRECTION_BOUNDS[(dx, dy)]
            exit_bound = getattr(current_tile.bounds, exit_attr)
            entry_bound = getattr(target.bounds, entry_attr)
            if not BOUND_TRAVERSABLE[exit_bound] or not BOUND_TRAVERSABLE[entry_bound]:
                return
        self.location = self.location._replace(x=nx, y=ny)

    def enter(self):
        tile = self.current_map.tiles.get(self.location)
        if tile and tile.nested_map is not None:
            self.map_stack.append((self.current_map, self.location))
            self.current_map = tile.nested_map
            self.location = MapKey(0, *self.current_map.entrance, 0)
            return True
        return False

    def exit(self):
        entrance = MapKey(0, *self.current_map.entrance, 0)
        if self.location == entrance:
            if self.map_stack:
                self.current_map, self.location = self.map_stack.pop()
                return True
        return False

    def transfer_item(self, item, source, target):
        tile = self.current_map.tiles.get(self.location)
        accessible = [self.inventory]
        if tile:
            accessible.append(tile.inventory)
            for creature in Creature.all():
                if creature is not self and creature.current_map is self.current_map and creature.location == self.location:
                    accessible.append(creature.inventory)
        if source not in accessible or target not in accessible:
            return False
        if item not in source.items:
            return False
        source.items.remove(item)
        target.items.append(item)
        return True


class NPC(Creature):
    sprite_name = 'npc'
    z_index     = 2

    def __init__(
        self
        ,current_map: Map
        ,location: MapKey = MapKey()
        ,species: str = None
        ,stats: dict = {}
        ,items: list = []
        ,move_interval: int = 1000
        ):
        super().__init__(current_map=current_map, location=location, species=species, stats=stats, items=items)
        self.move_interval = move_interval
        self._last_move = 0

    def update(self, now: int, cols: int, rows: int):
        if now - self._last_move >= self.move_interval:
            self._think(cols, rows)
            self._last_move = now

    def _think(self, cols: int, rows: int):
        dx, dy = random.choice([
            (-1,-1),( 0,-1),( 1,-1)
            ,(-1, 0),        ( 1, 0)
            ,(-1, 1),( 0, 1),( 1, 1)
        ])
        self.move(dx, dy, cols, rows)