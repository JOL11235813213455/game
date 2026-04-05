from __future__ import annotations
from typing import TYPE_CHECKING
from classes.trackable import Trackable
from classes.animation import AnimationState

if TYPE_CHECKING:
    from classes.maps import Map


class WorldObject(Trackable):
    sprite_name: str  = None
    z_index: int      = 0
    tile_scale: float = 1.0
    collision: bool   = False

    def __init__(self, current_map: Map = None, location=None):
        super().__init__()
        self.current_map = current_map
        if location is None:
            from classes.maps import MapKey
            location = MapKey()
        self.location = location
        self.anim = AnimationState()

    def play_animation(self, behavior: str, fallback: str = 'idle'):
        """Look up and play an animation for this object's species/type + behavior."""
        from data.db import ANIM_BINDINGS, ANIMATIONS
        target = getattr(self, 'species', None) or self.sprite_name
        if target is None:
            return
        anim_name = ANIM_BINDINGS.get((target, behavior))
        if anim_name is None and behavior != fallback:
            anim_name = ANIM_BINDINGS.get((target, fallback))
        if anim_name is None:
            self.anim.stop()
            return
        anim = ANIMATIONS.get(anim_name)
        if anim is None or not anim['frames']:
            self.anim.stop()
            return
        self.anim.play(anim_name, anim['frames'])

    def _resolve_sprite_name(self) -> str | None:
        """Return current sprite: animated frame if playing, else static."""
        if self.anim.is_playing:
            return self.anim.current_sprite
        return self.sprite_name

    def make_surface(self, block_size: int):
        """Return (surface, (blit_dx, blit_dy)) or None.

        blit_dx/blit_dy are the offset from the tile's top-left pixel so that
        the sprite's action point (or its center, if none is set) lands on the
        tile's center.
        """
        name = self._resolve_sprite_name()
        if name is None:
            return None
        import pygame
        from data.db import SPRITE_DATA
        data = SPRITE_DATA.get(name)
        if data is None:
            return None
        pixels  = data['pixels']
        palette = data['palette']
        cols    = len(pixels[0])
        rows    = len(pixels)
        w = int(cols * (block_size / 32) * self.tile_scale)
        h = int(rows * (block_size / 32) * self.tile_scale)
        native = pygame.Surface((cols, rows), pygame.SRCALPHA)
        for row_idx, row in enumerate(pixels):
            for col_idx, char in enumerate(row):
                if char == '.' or char not in palette:
                    continue
                native.set_at((col_idx, row_idx), palette[char])
        surface = pygame.transform.scale(native, (w, h))

        # Compute blit offset so the action point lands on the tile center.
        # action_point is stored as (x, y) in sprite-pixel coordinates.
        from main.config import TILE_HEIGHT
        tile_cx = block_size // 2
        tile_cy = TILE_HEIGHT // 2    # feet at tile center (3/4 convention)
        ap = data.get('action_point')
        if ap is not None:
            ap_sx = int(ap[0] * w / cols)
            ap_sy = int(ap[1] * h / rows)
        else:
            ap_sx = w // 2
            ap_sy = h              # sprite bottom = feet
        blit_dx = tile_cx - ap_sx
        blit_dy = tile_cy - ap_sy

        return surface, (blit_dx, blit_dy)
