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
        ,resource_type:str=None     # harvestable resource name (e.g. 'wheat', 'fish', 'berries')
        ,resource_amount:int=0      # current resource units available
        ,resource_max:int=0         # maximum resource capacity
        ,growth_rate:float=0.0      # units regenerated per grow tick
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
        self.resource_type   = resource_type   if resource_type   is not None else tmpl.get('resource_type',   None)
        self.resource_amount = resource_amount if resource_amount else tmpl.get('resource_amount', 0)
        self.resource_max    = resource_max    if resource_max    else tmpl.get('resource_max',    0)
        self.growth_rate     = growth_rate     if growth_rate     else tmpl.get('growth_rate',     0.0)
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
    # Grid cell size in tiles. Creatures self-register their cell when
    # their location changes; sight queries then read only cells within
    # a small neighborhood instead of scanning every creature on the map.
    # 8 tiles is a little larger than typical SIGHT_RANGE (~7) so a 3x3
    # cell neighborhood always contains every potentially-visible creature.
    CELL_SIZE = 8

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
        # Spatial index: (cell_x, cell_y, z) -> set of creature uids.
        # Populated via Creature.location setter when creatures move.
        # Not pickled — rebuilt by caller on load (see _rebuild_spatial_index).
        self._creature_cells: dict = {}

    # --- Spatial index API ----------------------------------------------
    def _cell_for(self, x: int, y: int, z: int = 0) -> tuple:
        return (x // self.CELL_SIZE, y // self.CELL_SIZE, z)

    def register_creature_at(self, creature, x: int, y: int, z: int = 0):
        """Add creature to the grid cell containing (x, y, z)."""
        key = self._cell_for(x, y, z)
        self._creature_cells.setdefault(key, set()).add(creature.uid)

    def unregister_creature_at(self, creature, x: int, y: int, z: int = 0):
        """Remove creature from the grid cell containing (x, y, z)."""
        key = self._cell_for(x, y, z)
        cell = self._creature_cells.get(key)
        if cell is not None:
            cell.discard(creature.uid)
            if not cell:
                self._creature_cells.pop(key, None)

    def creatures_in_range(self, cx: int, cy: int, cz: int,
                            manhattan_range: int) -> list:
        """Return all live creatures whose cell is within the neighborhood
        required to cover a Manhattan-distance query of the given range.

        The caller still applies the precise distance filter; this is a
        cheap broad-phase reject based on cell membership.
        """
        from classes.trackable import Trackable
        cell_span = max(1, (manhattan_range // self.CELL_SIZE) + 1)
        cx0 = cx // self.CELL_SIZE
        cy0 = cy // self.CELL_SIZE
        uids: set = set()
        for ox in range(-cell_span, cell_span + 1):
            for oy in range(-cell_span, cell_span + 1):
                cell = self._creature_cells.get((cx0 + ox, cy0 + oy, cz))
                if cell:
                    uids.update(cell)
        if not uids:
            return []
        # Resolve uids to live Creature instances via Trackable registry.
        from classes.creature import Creature
        out = []
        for obj in Trackable.all_instances():
            if isinstance(obj, Creature) and obj.uid in uids and obj.is_alive:
                out.append(obj)
        return out

    def rebuild_spatial_index(self):
        """Scan all creatures on this map and rebuild the grid cells.

        Called after save/load (when _creature_cells is empty because
        it wasn't pickled) or whenever the index might be stale.
        """
        self._creature_cells = {}
        from classes.world_object import WorldObject
        from classes.creature import Creature
        for obj in WorldObject.on_map(self):
            if isinstance(obj, Creature) and obj.is_alive:
                self.register_creature_at(
                    obj, obj.location.x, obj.location.y, obj.location.z)

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

    def grow_resources(self):
        """Tick resource regeneration on all tiles with a growth_rate.

        Each tile's resource_amount grows toward resource_max by growth_rate
        per call. Designed to be called periodically (e.g. every N training
        steps or every game minute).
        """
        for tile in self.tiles.values():
            if not tile.resource_type or tile.growth_rate <= 0:
                continue
            if tile.resource_amount < tile.resource_max:
                tile.resource_amount = min(
                    tile.resource_max,
                    tile.resource_amount + tile.growth_rate
                )

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