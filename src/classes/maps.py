from __future__ import annotations
from collections import namedtuple
from classes.trackable import Trackable
from classes.inventory import Inventory

MapKey = namedtuple("MapKey",["x","y","z"],defaults=[0,0,0])
Bounds = namedtuple("Bounds",["n","s","e","w","ne","nw","se","sw"],defaults=[True]*8)

# Maps (dx,dy) to (exit_attr_on_current, entry_attr_on_target)
DIRECTION_BOUNDS: dict[tuple, tuple[str, str]] = {
    ( 0,-1): ('n','s')
    ,( 0, 1): ('s','n')
    ,( 1, 0): ('e','w')
    ,(-1, 0): ('w','e')
    ,( 1,-1): ('ne','sw')
    ,(-1,-1): ('nw','se')
    ,( 1, 1): ('se','nw')
    ,(-1, 1): ('sw','ne')
    }

class Tile(Trackable):
    def __init__(
        self
        ,template:dict=None
        ,map:Map=None
        ,walkable:bool=None
        ,covered:bool=None
        ,bounds:Bounds=None
        ,items:list=None
        ,tile_template:str=None
        ,sprite_name:str=None
        ,tile_scale:float=None
        ,animation_name:str=None
        ,linked_map:str=None
        ,linked_x:int=None
        ,linked_y:int=None
        ,linked_z:int=None
        ,link_auto:bool=False
        ,stat_mods:dict=None
        ,speed_modifier:float=None
        ,bg_color:str=None
        ,liquid:bool=None
        ,flow_direction:str=None    # 'N', 'S', 'E', 'W' or None
        ,flow_speed:float=None      # tiles per second
        ,depth:int=None             # depth in tiles (0 = shallow, 1+ = deep)
        ,purpose:str=None           # tile purpose: trading, farming, hunting, etc.
        ):
        super().__init__()
        tmpl = template or {}
        self.walkable       = walkable    if walkable    is not None else tmpl.get('walkable',    True)
        self.covered        = covered     if covered     is not None else tmpl.get('covered',     False)
        self.bounds         = bounds      if bounds      is not None else Bounds()
        self.sprite_name    = sprite_name if sprite_name is not None else tmpl.get('sprite_name', None)
        self.tile_scale     = tile_scale  if tile_scale  is not None else tmpl.get('tile_scale',  1.0)
        self.animation_name = animation_name if animation_name is not None else tmpl.get('animation_name', None)
        self.speed_modifier = speed_modifier if speed_modifier is not None else tmpl.get('speed_modifier', 1.0)
        self.bg_color       = bg_color     if bg_color     is not None else tmpl.get('bg_color',     None)
        self.liquid         = liquid         if liquid         is not None else tmpl.get('liquid',         False)
        self.flow_direction = flow_direction if flow_direction is not None else tmpl.get('flow_direction', None)
        self.flow_speed     = flow_speed     if flow_speed     is not None else tmpl.get('flow_speed',     0.0)
        self.depth          = depth          if depth          is not None else tmpl.get('depth',          0)
        self._purpose        = purpose        if purpose        is not None else tmpl.get('purpose',        None)
        # Schedule: {purpose_str: (start_hour, end_hour)} for time-dependent purposes
        # e.g. {'sleeping': (20, 6), 'pairing': (20, 6), 'farming': (6, 18)}
        self.purpose_schedule: dict = {}
        self.nested_map: Map = map
        self.inventory = Inventory(items=items or [])
        self.buried_inventory = Inventory()  # requires DIG action + shovel to access
        self.buried_gold: int = 0            # buried gold (separate from surface gold)
        self.gold: int = 0  # gold on the ground
        self.tile_template = tile_template
        self.linked_map    = linked_map
        self.linked_location = (MapKey(linked_x, linked_y, linked_z or 0)
                                if linked_x is not None else None)
        self.link_auto     = link_auto
        self.stat_mods     = stat_mods or {}

    @property
    def purpose(self) -> str | None:
        """Active purpose, accounting for time-of-day schedule.

        If purpose_schedule is set, returns the scheduled purpose for the
        current hour. Falls back to the static _purpose if no schedule
        matches or no game clock is available.
        """
        if self.purpose_schedule:
            try:
                from main.game_clock import GameClock
                from classes.trackable import Trackable
                for obj in Trackable.all_instances():
                    if isinstance(obj, GameClock):
                        hour = obj.hour
                        for purp, (start, end) in self.purpose_schedule.items():
                            if start <= end:
                                if start <= hour < end:
                                    return purp
                            else:  # wraps midnight (e.g. 20-6)
                                if hour >= start or hour < end:
                                    return purp
                        break
            except Exception:
                pass
        return self._purpose

    @purpose.setter
    def purpose(self, value):
        self._purpose = value

class Map(Trackable):
    def __init__(
        self
        ,tile_set: dict[MapKey, Tile] = None
        ,entrance: tuple[int, int] = (0, 0)
        ,name: str = None
        ,default_tile_template: str = None
        ,x_min: int = -16, x_max: int = 16
        ,y_min: int = -16, y_max: int = 16
        ,z_min: int = -16, z_max: int = 16
        ):
        super().__init__()
        self.tiles = tile_set if tile_set is not None else {}
        self.entrance = entrance
        self.name = name
        self.default_tile_template = default_tile_template
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max
        self.z_min = z_min
        self.z_max = z_max

    # Flow directions to (dx, dy)
    _FLOW_DIRS = {'N': (0, -1), 'S': (0, 1), 'E': (1, 0), 'W': (-1, 0)}

    def flow_items(self):
        """Move surface items and gold along liquid flow directions.

        Items only flow into adjacent liquid tiles. Items that reach
        a still liquid tile (no flow) or a non-liquid tile stop.
        """
        moves = []  # (from_key, to_key, items, gold)
        for key, tile in self.tiles.items():
            if not getattr(tile, 'liquid', False):
                continue
            flow_dir = getattr(tile, 'flow_direction', None)
            if not flow_dir or getattr(tile, 'flow_speed', 0) <= 0:
                continue
            if not tile.inventory.items and tile.gold <= 0:
                continue
            fd = self._FLOW_DIRS.get(flow_dir)
            if not fd:
                continue
            dx, dy = fd
            next_key = MapKey(key.x + dx, key.y + dy, key.z)
            next_tile = self.tiles.get(next_key)
            if next_tile and getattr(next_tile, 'liquid', False):
                moves.append((key, next_key,
                               list(tile.inventory.items), tile.gold))

        for from_key, to_key, items, gold in moves:
            from_tile = self.tiles[from_key]
            to_tile = self.tiles[to_key]
            for item in items:
                if item in from_tile.inventory.items:
                    from_tile.inventory.items.remove(item)
                    to_tile.inventory.items.append(item)
            if gold > 0:
                from_tile.gold -= gold
                to_tile.gold += gold

    def generate_buried_loot(self, loot_table: list[dict] = None,
                             density: float = 0.05, seed: int = None):
        """Populate buried_inventory on walkable tiles.

        Args:
            loot_table: list of dicts with keys:
                'item_factory': callable() -> Item
                'weight': float (relative probability)
                'gold_min': int, 'gold_max': int (optional gold range)
            density: fraction of walkable tiles that get buried loot
            seed: random seed for reproducibility
        """
        import random as rng
        if seed is not None:
            rng.seed(seed)

        if loot_table is None:
            # Default: just bury some gold
            loot_table = [{'weight': 1.0, 'gold_min': 1, 'gold_max': 20}]

        total_weight = sum(e.get('weight', 1.0) for e in loot_table)
        walkable = [k for k, t in self.tiles.items() if t.walkable]

        for key in walkable:
            if rng.random() > density:
                continue
            tile = self.tiles[key]
            # Pick a loot entry
            roll = rng.random() * total_weight
            cumul = 0.0
            for entry in loot_table:
                cumul += entry.get('weight', 1.0)
                if roll <= cumul:
                    # Gold
                    gmin = entry.get('gold_min', 0)
                    gmax = entry.get('gold_max', 0)
                    if gmax > 0:
                        tile.buried_gold += rng.randint(gmin, gmax)
                    # Item
                    factory = entry.get('item_factory')
                    if factory:
                        tile.buried_inventory.items.append(factory())
                    break