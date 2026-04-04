from __future__ import annotations
from typing import TYPE_CHECKING
from classes.trackable import Trackable

if TYPE_CHECKING:
    from classes.maps import Map


class WorldObject(Trackable):
    sprite_name: str          = None
    z_index: int              = 0
    size: tuple[float, float] = (1.0, 1.0)

    def __init__(self, current_map: Map = None, location=None):
        super().__init__()
        self.current_map = current_map
        if location is None:
            from classes.maps import MapKey
            location = MapKey()
        self.location = location

    def make_surface(self, block_size: int):
        if self.sprite_name is None:
            return None
        import pygame
        from data.sprites import SPRITE_DATA
        data = SPRITE_DATA.get(self.sprite_name)
        if data is None:
            return None
        pixels  = data['pixels']
        palette = data['palette']
        cols    = len(pixels[0])
        rows    = len(pixels)
        w = int(block_size * self.size[0])
        h = int(block_size * self.size[1])
        pixel_w = w // cols
        pixel_h = h // rows
        surface = pygame.Surface((w, h), pygame.SRCALPHA)
        for row_idx, row in enumerate(pixels):
            for col_idx, char in enumerate(row):
                if char == '.' or char not in palette:
                    continue
                pygame.draw.rect(surface, palette[char], pygame.Rect(
                    col_idx * pixel_w
                    ,row_idx * pixel_h
                    ,pixel_w
                    ,pixel_h
                ))
        return surface
