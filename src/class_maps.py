from __future__ import annotations
from collections import namedtuple
from enum import Enum
import weakref

MapKey = namedtuple("MapKey",["w","x","y","z"],defaults=[0,0,0,0])

class Tile:
    _instances = weakref.WeakSet()
    def __init__(
        self
        ,map:Map=None
        ,walkable:bool=True
        ,covered:bool=False
        ,walls_nesw:tuple=(0,0,0,0)
        ):
        Tile._instances.add(self)
        self.walkable=walkable
        self.covered=covered
        self.walls_nesw=walls_nesw
        self.nested_map: Map = map
        
    @classmethod
    def all(cls):
        return list(cls._instances)

class Map:
    _instances = weakref.WeakSet()
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
        self.tiles = tile_set
        self.entrance = entrance
        self.exit = exit
    
    @classmethod
    def all(cls):
        return list(cls._instances)
    
    def go_west(
        self
        ,start_tile
        ,end_tile
        ):
        pass



