from __future__ import annotations
from enum import Enum
import random
from classes.maps import Map, MapKey
from classes.inventory import Inventory
from classes.trackable import Trackable
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

def level_up_heal(creature, old_level, new_level):
    hd = creature.stats.get(Stat.HD, 6)
    con = creature.stats.get(Stat.CON, 0)
    roll = random.randint(1, hd) + con
    creature.stats[Stat.MHP] = creature.stats.get(Stat.MHP, 0) + roll
    creature.stats[Stat.CHP] = int(creature.stats[Stat.MHP] * 0.75)

class Creature(Trackable):
    def __init__(
        self
        ,current_map: Map
        ,location: MapKey = MapKey()
        ,stats: dict = {}
        ,items: list = []
        ):
        super().__init__()
        self.current_map = current_map
        self.location = location
        self.stats = {**stats}
        self._reconcile_exp_level()
        self.inventory = Inventory(items=items)
        self.map_stack: list[tuple[Map, MapKey]] = []
        self.on_level_up: list[callable] = [level_up_heal]

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
        target = self.current_map.tiles.get(MapKey(self.location.w, nx, ny, self.location.z))
        if target and target.walkable:
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

    def transfer_item(self, item, source: Inventory, target: Inventory):
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