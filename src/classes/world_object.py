from __future__ import annotations
from typing import TYPE_CHECKING
from classes.trackable import Trackable
from classes.animation import AnimationState

if TYPE_CHECKING:
    from classes.maps import Map


class WorldObject(Trackable):
    sprite_name: str    = None
    composite_name: str = None
    z_index: int        = 0
    tile_scale: float   = 1.0
    collision: bool     = False

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
        # Try composite rendering first
        if self.composite_name:
            result = self._make_composite_surface(block_size)
            if result:
                return result

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
        from main.config import get_tile_height
        tile_cx = block_size // 2
        tile_cy = get_tile_height() // 2    # feet at tile center (3/4 convention)
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

    def _make_composite_surface(self, block_size: int):
        """Assemble all layers of a composite sprite into one surface."""
        import pygame
        from data.db import COMPOSITES, SPRITE_DATA

        comp = COMPOSITES.get(self.composite_name)
        if not comp or not comp['layers']:
            return None

        root = comp['root_layer']
        scale = block_size / 32 * self.tile_scale

        # Resolve layer positions in native pixel coords
        positions = {}

        def resolve(layer_name, depth=0):
            if layer_name in positions or depth > 20:
                return
            if layer_name == root:
                positions[layer_name] = (0, 0)
            else:
                conn = comp['connections'].get(layer_name)
                if not conn:
                    positions[layer_name] = (0, 0)
                    return
                parent = conn['parent_layer']
                resolve(parent, depth + 1)
                pp = positions.get(parent, (0, 0))
                sx, sy = conn['parent_socket']
                ax, ay = conn['child_anchor']
                positions[layer_name] = (pp[0] + sx - ax, pp[1] + sy - ay)

        for lname in comp['layers']:
            resolve(lname)

        # Find bounding box
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for lname, layer in comp['layers'].items():
            data = SPRITE_DATA.get(layer['default_sprite'] or '')
            if not data:
                continue
            px, py = positions.get(lname, (0, 0))
            w = data['width']
            h = len(data['pixels'])
            min_x = min(min_x, px)
            min_y = min(min_y, py)
            max_x = max(max_x, px + w)
            max_y = max(max_y, py + h)

        if min_x == float('inf'):
            return None

        total_w = max_x - min_x
        total_h = max_y - min_y
        if total_w <= 0 or total_h <= 0:
            return None

        # Create native-resolution surface and blit layers sorted by z_layer
        native = pygame.Surface((total_w, total_h), pygame.SRCALPHA)
        sorted_layers = sorted(comp['layers'].items(),
                               key=lambda x: x[1]['z_layer'])
        for lname, layer in sorted_layers:
            data = SPRITE_DATA.get(layer['default_sprite'] or '')
            if not data:
                continue
            px, py = positions.get(lname, (0, 0))
            pixels = data['pixels']
            palette = data['palette']
            for row_idx, row_str in enumerate(pixels):
                for col_idx, ch in enumerate(row_str):
                    if ch == '.' or ch not in palette:
                        continue
                    native.set_at((px - min_x + col_idx, py - min_y + row_idx),
                                  palette[ch])

        # Scale to game size
        sw = int(total_w * scale)
        sh = int(total_h * scale)
        surface = pygame.transform.scale(native, (sw, sh))

        # Blit offset: center-bottom of composite on tile center
        from main.config import get_tile_height
        tile_cx = block_size // 2
        tile_cy = get_tile_height() // 2
        blit_dx = tile_cx - sw // 2
        blit_dy = tile_cy - sh

        return surface, (blit_dx, blit_dy)
