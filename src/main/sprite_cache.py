"""
Cached sprite surface rendering.

- Native sprites: character-grid → NumPy RGBA → pygame Surface (built once)
- Scaled sprites: native scaled to game size, cached by (name, w, h)
- Tiled sprites: small sprites tiled to fill larger areas (ground tiles)
- Composite sprites: assembled from cached native layers, cached by pose
- Pre-rendered composite animations: baked frame lists at load time

Cache invalidates on zoom change (block_size change).
"""
import numpy as np
import pygame


# -- simple sprite caches --

# {sprite_name: Surface} — native resolution, unscaled
_native_cache: dict[str, pygame.Surface] = {}

# {(sprite_name, w, h): Surface} — scaled to game size
_surface_cache: dict[tuple, pygame.Surface] = {}

# -- composite caches --

# {(composite_name, variant_key, block_size, tile_scale): (Surface, (blit_dx, blit_dy))}
_composite_cache: dict[tuple, tuple] = {}

# {(composite_name, anim_name, variant_key, block_size, tile_scale): [Surface, ...]}
_composite_anim_cache: dict[tuple, list] = {}

_last_block_size: int = 0


def invalidate():
    """Clear all caches (call on zoom change or data reload)."""
    _native_cache.clear()
    _surface_cache.clear()
    _composite_cache.clear()
    _composite_anim_cache.clear()


def _check_zoom(block_size: int):
    global _last_block_size
    if block_size != _last_block_size:
        _surface_cache.clear()
        _composite_cache.clear()
        _composite_anim_cache.clear()
        _last_block_size = block_size


# ---------------------------------------------------------------------------
# Native sprite rendering (character grid → Surface via NumPy)
# ---------------------------------------------------------------------------

def get_native(sprite_name: str) -> pygame.Surface | None:
    """Get or build the native-resolution surface for a sprite."""
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

    # Build RGBA array via NumPy
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
    """Get a sprite tiled to fill target dimensions. Used for ground tiles."""
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

    tiled = pygame.Surface((target_w, target_h), pygame.SRCALPHA)
    for tx in range(0, target_w, nw):
        for ty in range(0, target_h, nh):
            tiled.blit(native, (tx, ty))
    _surface_cache[key] = tiled
    return tiled


# ---------------------------------------------------------------------------
# Composite sprite assembly
# ---------------------------------------------------------------------------

def _resolve_composite_positions(comp):
    """Compute layer positions in native pixel coords. Returns {name: (x,y)}."""
    root = comp['root_layer']
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
            resolve(conn['parent_layer'], depth + 1)
            pp = positions.get(conn['parent_layer'], (0, 0))
            sx, sy = conn['parent_socket']
            ax, ay = conn['child_anchor']
            positions[layer_name] = (pp[0] + sx - ax, pp[1] + sy - ay)

    for lname in comp['layers']:
        resolve(lname)
    return positions


def _assemble_composite_native(comp, positions, sprite_overrides=None,
                                offset_overrides=None):
    """
    Blit cached native layer surfaces into a single unscaled Surface.
    sprite_overrides: {layer_name: sprite_name} — replace default sprite
    offset_overrides: {layer_name: (dx, dy)} — pixel offset from connection point
    Returns (Surface, min_x, min_y) or None.
    """
    sprite_overrides = sprite_overrides or {}
    offset_overrides = offset_overrides or {}

    # Gather layer surfaces and compute bounding box
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')
    layer_data = []  # [(layer_name, surface, px, py)]

    for lname, layer in sorted(comp['layers'].items(),
                                key=lambda x: x[1]['z_layer']):
        spr = sprite_overrides.get(lname, layer['default_sprite'])
        if not spr:
            continue
        native = get_native(spr)
        if native is None:
            continue
        px, py = positions.get(lname, (0, 0))
        ox, oy = offset_overrides.get(lname, (0, 0))
        px += ox
        py += oy
        nw, nh = native.get_size()
        min_x = min(min_x, px)
        min_y = min(min_y, py)
        max_x = max(max_x, px + nw)
        max_y = max(max_y, py + nh)
        layer_data.append((native, px, py))

    if min_x == float('inf'):
        return None

    total_w = max_x - min_x
    total_h = max_y - min_y
    if total_w <= 0 or total_h <= 0:
        return None

    composite = pygame.Surface((total_w, total_h), pygame.SRCALPHA)
    for native, px, py in layer_data:
        composite.blit(native, (px - min_x, py - min_y))

    return composite, min_x, min_y


def get_composite(composite_name: str, block_size: int,
                  tile_scale: float = 1.0,
                  variant_key: tuple = ()) -> tuple | None:
    """
    Get a cached composite surface + blit offset.
    variant_key: tuple of (layer_name, sprite_name) overrides, hashable.
    Returns (Surface, (blit_dx, blit_dy)) or None.
    """
    _check_zoom(block_size)
    cache_key = (composite_name, variant_key, block_size, tile_scale)
    if cache_key in _composite_cache:
        return _composite_cache[cache_key]

    from data.db import COMPOSITES
    comp = COMPOSITES.get(composite_name)
    if not comp or not comp['layers']:
        return None

    positions = _resolve_composite_positions(comp)
    sprite_overrides = dict(variant_key) if variant_key else None

    result = _assemble_composite_native(comp, positions, sprite_overrides)
    if result is None:
        return None

    native_surf, _, _ = result
    scale = block_size / 32 * tile_scale
    nw, nh = native_surf.get_size()
    sw = max(1, int(nw * scale))
    sh = max(1, int(nh * scale))
    surface = pygame.transform.scale(native_surf, (sw, sh))

    from main.config import get_tile_height
    tile_cx = block_size // 2
    tile_cy = get_tile_height() // 2
    blit_dx = tile_cx - sw // 2
    blit_dy = tile_cy - sh

    entry = (surface, (blit_dx, blit_dy))
    _composite_cache[cache_key] = entry
    return entry


# ---------------------------------------------------------------------------
# Pre-rendered composite animations
# ---------------------------------------------------------------------------

def _lerp(a, b, t):
    return a + (b - a) * t


def _interp_keyframes(keyframes, time_ms):
    """Interpolate offset_x, offset_y, rotation_deg, variant_name at time_ms."""
    if not keyframes:
        return 0, 0, 0.0, None
    if len(keyframes) == 1:
        k = keyframes[0]
        return k['offset_x'], k['offset_y'], k['rotation_deg'], k.get('variant_name')
    prev = keyframes[0]
    nxt = prev
    for kf in keyframes:
        if kf['time_ms'] > time_ms:
            nxt = kf
            break
        prev = kf
    else:
        return prev['offset_x'], prev['offset_y'], prev['rotation_deg'], prev.get('variant_name')
    if prev['time_ms'] == nxt['time_ms']:
        return prev['offset_x'], prev['offset_y'], prev['rotation_deg'], prev.get('variant_name')
    t = (time_ms - prev['time_ms']) / (nxt['time_ms'] - prev['time_ms'])
    return (_lerp(prev['offset_x'], nxt['offset_x'], t),
            _lerp(prev['offset_y'], nxt['offset_y'], t),
            _lerp(prev['rotation_deg'], nxt['rotation_deg'], t),
            prev.get('variant_name') or nxt.get('variant_name'))


def pre_render_composite_anim(composite_name: str, anim_name: str,
                               block_size: int, tile_scale: float = 1.0,
                               frame_interval_ms: int = 33) -> list | None:
    """
    Pre-render a composite animation into a flat list of (Surface, (dx, dy)).
    Each entry corresponds to one frame_interval_ms step.
    Returns the list, also caches it.
    """
    _check_zoom(block_size)
    from data.db import COMPOSITES, COMPOSITE_ANIMS

    anim = COMPOSITE_ANIMS.get(anim_name)
    if not anim or not anim['keyframes']:
        return None

    comp = COMPOSITES.get(composite_name)
    if not comp or not comp['layers']:
        return None

    duration = anim['duration_ms']
    if duration <= 0:
        return None

    # Build a variant_key for cache (all default variants from keyframes)
    # We bake one version per distinct variant combination
    positions = _resolve_composite_positions(comp)
    scale = block_size / 32 * tile_scale

    frames = []
    step = max(1, frame_interval_ms)
    num_frames = max(1, duration // step)

    for i in range(num_frames):
        t = i * step
        sprite_overrides = {}
        offset_overrides = {}

        for layer_name, kfs in anim['keyframes'].items():
            ox, oy, rot, var = _interp_keyframes(kfs, t)
            offset_overrides[layer_name] = (int(ox), int(oy))
            if var:
                var_sprites = comp['variants'].get(layer_name, {})
                spr = var_sprites.get(var)
                if spr:
                    sprite_overrides[layer_name] = spr

        result = _assemble_composite_native(comp, positions,
                                             sprite_overrides,
                                             offset_overrides)
        if result is None:
            frames.append(None)
            continue

        native_surf, _, _ = result
        nw, nh = native_surf.get_size()
        sw = max(1, int(nw * scale))
        sh = max(1, int(nh * scale))
        surface = pygame.transform.scale(native_surf, (sw, sh))

        from main.config import get_tile_height
        tile_cx = block_size // 2
        tile_cy = get_tile_height() // 2
        blit_dx = tile_cx - sw // 2
        blit_dy = tile_cy - sh

        frames.append((surface, (blit_dx, blit_dy)))

    # Build a hashable variant key from the animation's variant references
    variant_key = tuple(sorted(
        (ln, var)
        for ln, kfs in anim['keyframes'].items()
        for kf in kfs
        if (var := kf.get('variant_name'))
    ))
    cache_key = (composite_name, anim_name, variant_key,
                 block_size, tile_scale)
    _composite_anim_cache[cache_key] = frames
    return frames


def get_composite_anim_frame(composite_name: str, anim_name: str,
                              time_ms: int, block_size: int,
                              tile_scale: float = 1.0,
                              frame_interval_ms: int = 33) -> tuple | None:
    """
    Get a pre-rendered frame for a composite animation at the given time.
    Lazily pre-renders on first access.
    Returns (Surface, (blit_dx, blit_dy)) or None.
    """
    _check_zoom(block_size)
    from data.db import COMPOSITE_ANIMS

    anim = COMPOSITE_ANIMS.get(anim_name)
    if not anim:
        return None

    duration = anim['duration_ms']
    if duration <= 0:
        return None

    # Find or build the cached frame list
    # Build variant key from animation definition
    variant_key = tuple(sorted(
        (ln, var)
        for ln, kfs in anim['keyframes'].items()
        for kf in kfs
        if (var := kf.get('variant_name'))
    ))
    cache_key = (composite_name, anim_name, variant_key,
                 block_size, tile_scale)

    frames = _composite_anim_cache.get(cache_key)
    if frames is None:
        frames = pre_render_composite_anim(
            composite_name, anim_name, block_size, tile_scale,
            frame_interval_ms)
        if frames is None:
            return None

    if not frames:
        return None

    # Map time_ms to frame index
    step = max(1, frame_interval_ms)
    if anim['loop']:
        t = time_ms % duration
    else:
        t = min(time_ms, duration - 1)
    idx = min(t // step, len(frames) - 1)
    return frames[idx]
