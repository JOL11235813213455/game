from __future__ import annotations
from classes.creature import Creature, Stat
from classes.maps import Map, MapKey
import random

class NPC(Creature):
    _instances  = __import__('weakref').WeakSet()
    sprite_name = 'npc'
    z_index     = 2

    def __init__(
        self
        ,current_map: Map
        ,location: MapKey = MapKey()
        ,stats: dict = {}
        ,items: list = []
        ,move_interval: int = 1000
        ):
        super().__init__(current_map=current_map, location=location, stats=stats, items=items)
        self.move_interval = move_interval  # ms between moves
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
