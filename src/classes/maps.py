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
        ,map:Map=None
        ,walkable:bool=True
        ,covered:bool=False
        ,bounds:Bounds=Bounds()
        ,items:list=[]
        ):
        super().__init__()
        self.walkable=walkable
        self.covered=covered
        self.bounds=bounds
        self.nested_map: Map = map
        self.inventory = Inventory(items=items)

class Map(Trackable):
    def __init__(
        self
        ,tile_set: dict[MapKey, Tile] = {}
        ,entrance: tuple[int, int] = (0, 0)
        ,w_minmax: tuple[int, int] = (0, 0)
        ,x_minmax: tuple[int, int] = (-16, 16)
        ,y_minmax: tuple[int, int] = (-16, 16)
        ,z_minmax: tuple[int, int] = (-16, 16)
        ):
        super().__init__()
        self.tiles = tile_set
        self.entrance = entrance
