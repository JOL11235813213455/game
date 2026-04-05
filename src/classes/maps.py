from __future__ import annotations
from collections import namedtuple
from enum import Enum
from classes.trackable import Trackable
from classes.inventory import Inventory

MapKey = namedtuple("MapKey",["w","x","y","z"],defaults=[0,0,0,0])

class Bound(Enum):
    NONE        = None
    WALL        = 'wall'
    OPENING     = 'opening'
    DOOR_OPEN   = 'door_open'
    DOOR_CLOSED = 'door_closed'
    GATE_OPEN   = 'gate_open'
    GATE_CLOSED = 'gate_closed'

Bounds = namedtuple("Bounds",["n","s","e","w","ne","nw","se","sw"],defaults=[Bound.NONE]*8)

BOUND_TRAVERSABLE: dict[Bound, bool] = {
    Bound.NONE:         True
    ,Bound.OPENING:     True
    ,Bound.DOOR_OPEN:   True
    ,Bound.DOOR_CLOSED: False
    ,Bound.GATE_OPEN:   True
    ,Bound.GATE_CLOSED: False
    ,Bound.WALL:        False
    }

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
        ,items:list=[]
        ,tile_template:str=None
        ,sprite_name:str=None
        ,tile_scale:float=None
        ,animation_name:str=None
        ):
        super().__init__()
        tmpl = template or {}
        self.walkable       = walkable    if walkable    is not None else tmpl.get('walkable',    True)
        self.covered        = covered     if covered     is not None else tmpl.get('covered',     False)
        self.bounds         = bounds      if bounds      is not None else tmpl.get('bounds',      Bounds())
        self.sprite_name    = sprite_name if sprite_name is not None else tmpl.get('sprite_name', None)
        self.tile_scale     = tile_scale  if tile_scale  is not None else tmpl.get('tile_scale',  1.0)
        self.animation_name = animation_name if animation_name is not None else tmpl.get('animation_name', None)
        self.nested_map: Map = map
        self.inventory = Inventory(items=items)
        self.tile_template = tile_template

class Map(Trackable):
    def __init__(
        self
        ,tile_set: dict[MapKey, Tile] = {}
        ,entrance: tuple[int, int] = (0, 0)
        ,name: str = None
        ,default_tile: str = None
        ,w_min: int = 0,  w_max: int = 0
        ,x_min: int = -16, x_max: int = 16
        ,y_min: int = -16, y_max: int = 16
        ,z_min: int = -16, z_max: int = 16
        ):
        super().__init__()
        self.tiles = tile_set
        self.entrance = entrance
        self.name = name
        self.default_tile = default_tile
        self.w_min = w_min
        self.w_max = w_max
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max
        self.z_min = z_min
        self.z_max = z_max
