"""
Cached sprite surface rendering.

Converts character-grid pixel data to pygame Surfaces using NumPy arrays
instead of per-pixel set_at() calls, and caches results so unchanged
sprites are never re-rendered.

Cache is invalidated on zoom changes (block_size change).
"""
import numpy as np
import pygame


# {(sprite_name, block_size): Surface}  — native-res sprites scaled to game size
_surface_cache: dict[tuple, pygame.Surface] = {}

# {sprite_name: Surface}  — native-resolution (unscaled) sprites
_native_cache: dict[str, pygame.Surface] = {}

_last_block_size: int = 0


def invalidate():
    """Clear all caches (call on zoom change)."""
    _surface_cache.clear()
    _native_cache.clear()


def _check_zoom(block_size: int):
    """Clear scaled cache if zoom changed."""
    global _last_block_size
    if block_size != _last_block_size:
        _surface_cache.clear()
        _last_block_size = block_size


def get_native(sprite_name: str) -> pygame.Surface | None:
    """Get or build the native-resolution surface for a sprite (no scaling)."""
    if sprite_name in _native_cache:
        return _native_cache[sprite_name]

    from data.db import SPRITE_DATA
    data = SPRITE_DATA.get(sprite_name)
    if data is None:
        return None

    pixels = data['pixels']
    palette = data['palette']
    rows = len(pixels)
    cols = len(pixels[0]) if rows else 0
    if rows == 0 or cols == 0:
        return None

    # Build RGBA array via NumPy — much faster than set_at()
    arr = np.zeros((rows, cols, 4), dtype=np.uint8)
    for char, color in palette.items():
        if char == '.':
            continue
        if isinstance(color, (list, tuple)):
            r, g, b = color[:3]
        else:
            continue
        for row_idx, row_str in enumerate(pixels):
            for col_idx, ch in enumerate(row_str):
                if ch == char:
                    arr[row_idx, col_idx] = (r, g, b, 255)

    surface = pygame.image.frombuffer(arr.tobytes(), (cols, rows), 'RGBA')
    surface = surface.convert_alpha()
    _native_cache[sprite_name] = surface
    return surface


def get_scaled(sprite_name: str, target_w: int, target_h: int,
               block_size: int) -> pygame.Surface | None:
    """Get a sprite surface scaled to target dimensions. Cached."""
    _check_zoom(block_size)
    key = (sprite_name, target_w, target_h)
    if key in _surface_cache:
        return _surface_cache[key]

    native = get_native(sprite_name)
    if native is None:
        return None

    if native.get_size() == (target_w, target_h):
        _surface_cache[key] = native
        return native

    scaled = pygame.transform.scale(native, (target_w, target_h))
    _surface_cache[key] = scaled
    return scaled


def get_tiled(sprite_name: str, target_w: int, target_h: int,
              block_size: int) -> pygame.Surface | None:
    """Get a sprite tiled to fill target dimensions. Used for tiles."""
    _check_zoom(block_size)
    key = ('tiled', sprite_name, target_w, target_h)
    if key in _surface_cache:
        return _surface_cache[key]

    native = get_native(sprite_name)
    if native is None:
        return None

    nw, nh = native.get_size()
    if nw >= target_w and nh >= target_h:
        scaled = pygame.transform.scale(native, (target_w, target_h))
        _surface_cache[key] = scaled
        return scaled

    # Tile the native surface to fill target
    tiled = pygame.Surface((target_w, target_h), pygame.SRCALPHA)
    for tx in range(0, target_w, nw):
        for ty in range(0, target_h, nh):
            tiled.blit(native, (tx, ty))
    _surface_cache[key] = tiled
    return tiled
