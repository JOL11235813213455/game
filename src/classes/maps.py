from __future__ import annotations
from collections import namedtuple
from enum import Enum
from classes.trackable import Trackable
from classes.inventory import Inventory

MapKey = namedtuple("MapKey",["w","x","y","z"],defaults=[0,0,0,0])

class Tile(Trackable):
    def __init__(
        self
        ,map:Map=None
        ,walkable:bool=True
        ,covered:bool=False
        ,walls_nesw:tuple=(0,0,0,0)
        ,items:list=[]
        ):
        super().__init__()
        self.walkable=walkable
        self.covered=covered
        self.walls_nesw=walls_nesw
        self.nested_map: Map = map
        self.inventory = Inventory(items=items)

class Map(Trackable):
    def __init__(
        self
        ,tile_set: dict[MapKey, Tile] = {}
        ,entrance: tuple[int, int] = (0, 0)
        ,exit: tuple[int, int] = (0, 0)
        ,w_minmax: tuple[int, int] = (0, 0)
        ,x_minmax: tuple[int, int] = (-16, 16)
        ,y_minmax: tuple[int, int] = (-16, 16)
        ,z_minmax: tuple[int, int] = (-16, 16)
        ):
        super().__init__()
        self.tiles = tile_set
        self.entrance = entrance
        self.exit = exit