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
        self.nested_map: Map = map
        self.inventory = Inventory(items=items or [])
        self.tile_template = tile_template
        self.linked_map    = linked_map
        self.linked_location = (MapKey(linked_x, linked_y, linked_z or 0)
                                if linked_x is not None else None)
        self.link_auto     = link_auto
        self.stat_mods     = stat_mods or {}

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