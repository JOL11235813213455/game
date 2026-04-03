from __future__ import annotations
from class_maps import Map, MapKey


class Creature:
    def __init__(
        self
        ,current_map: Map
        ,x: int = 0
        ,y: int = 0
        ):
        self.current_map = current_map
        self.x = x
        self.y = y
        self.map_stack: list[tuple[Map, int, int]] = []

    def move(self, dx: int, dy: int, cols: int, rows: int):
        nx = max(0, min(cols - 1, self.x + dx))
        ny = max(0, min(rows - 1, self.y + dy))
        target = self.current_map.tiles.get(MapKey(0, nx, ny, 0))
        if target and target.walkable:
            self.x, self.y = nx, ny

    def enter(self):
        tile = self.current_map.tiles.get(MapKey(0, self.x, self.y, 0))
        if tile and tile.nested_map is not None:
            self.map_stack.append((self.current_map, self.x, self.y))
            self.current_map = tile.nested_map
            self.x, self.y = self.current_map.entrance
            return True
        return False

    def exit(self):
        if self.x == self.current_map.entrance[0] and self.y == self.current_map.entrance[1]:
            if self.map_stack:
                self.current_map, self.x, self.y = self.map_stack.pop()
                return True
        return False
