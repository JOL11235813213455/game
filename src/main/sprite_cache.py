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

def _rotate_point(px, py, cx, cy, angle_deg):
    """Rotate point (px,py) around center (cx,cy) by angle_deg degrees."""
    import math
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    return (cx + dx * cos_a - dy * sin_a,
            cy + dx * sin_a + dy * cos_a)


def _resolve_composite_positions(comp, offset_overrides=None,
                                  rotation_overrides=None):
    """Compute layer positions in native pixel coords.
    Returns {name: (x, y)} and cumulative_rotations {name: degrees}.
    offset_overrides and rotation_overrides applied during resolution
    so children inherit parent movement and rotation.
    rotation_overrides: {layer_name: degrees} — rotation around connection point.
    """
    root = comp['root_layer']
    offsets = offset_overrides or {}
    rotations = rotation_overrides or {}
    positions = {}
    cumulative_rot = {}  # layer_name → total inherited rotation in degrees

    def resolve(layer_name, depth=0):
        if layer_name in positions or depth > 20:
            return
        if layer_name == root:
            positions[layer_name] = (0, 0)
            cumulative_rot[layer_name] = rotations.get(layer_name, 0.0)
        else:
            conn = comp['connections'].get(layer_name)
            if not conn:
                positions[layer_name] = (0, 0)
                cumulative_rot[layer_name] = rotations.get(layer_name, 0.0)
                return
            parent = conn['parent_layer']
            resolve(parent, depth + 1)
            pp = positions.get(parent, (0, 0))
            sx, sy = conn['parent_socket']
            ax, ay = conn['child_anchor']
            # Socket in world coords
            sock_wx = pp[0] + sx
            sock_wy = pp[1] + sy
            # If parent has cumulative rotation, rotate the socket around
            # the parent's anchor point
            parent_cum_rot = cumulative_rot.get(parent, 0.0)
            if parent_cum_rot:
                parent_conn = comp['connections'].get(parent)
                if parent_conn:
                    pcx = pp[0] + parent_conn['child_anchor'][0]
                    pcy = pp[1] + parent_conn['child_anchor'][1]
                else:
                    pcx, pcy = pp[0], pp[1]
                sock_wx, sock_wy = _rotate_point(
                    sock_wx, sock_wy, pcx, pcy, parent_cum_rot)
            positions[layer_name] = (sock_wx - ax, sock_wy - ay)
            # This layer's cumulative rotation = parent's cumulative + own
            cumulative_rot[layer_name] = parent_cum_rot + rotations.get(layer_name, 0.0)

        # Apply offset after resolving
        ox, oy = offsets.get(layer_name, (0, 0))
        if ox or oy:
            px, py = positions[layer_name]
            positions[layer_name] = (px + ox, py + oy)

    for lname in comp['layers']:
        resolve(lname)
    return positions, cumulative_rot


def _assemble_composite_native(comp, positions, sprite_overrides=None,
                                layer_opacity=None, layer_tint=None,
                                layer_rotation=None):
    """
    Blit cached native layer surfaces into a single unscaled Surface.
    sprite_overrides: {layer_name: sprite_name} — replace default sprite
    layer_opacity: {layer_name: float 0..1} — per-layer opacity
    layer_tint: {layer_name: (r, g, b)} — per-layer color tint
    layer_rotation: {layer_name: degrees} — cumulative rotation (own + ancestors).
        Used to visually rotate each layer's sprite.
    Positions should already include any animation offsets (with orbiting
    from ancestor rotations already baked in).
    Returns (Surface, min_x, min_y) or None.
    """
    sprite_overrides = sprite_overrides or {}
    layer_opacity = layer_opacity or {}
    layer_tint = layer_tint or {}
    layer_rotation = layer_rotation or {}

    # Gather layer surfaces, apply rotation, compute bounding box
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')
    layer_data = []  # [(layer_name, surface, blit_x, blit_y)]

    for lname, layer in sorted(comp['layers'].items(),
                                key=lambda x: x[1]['z_layer']):
        spr = sprite_overrides.get(lname, layer['default_sprite'])
        if not spr:
            continue
        native = get_native(spr)
        if native is None:
            continue
        px, py = positions.get(lname, (0, 0))
        rot = layer_rotation.get(lname, 0.0)
        surf = native
        bx, by = px, py

        if rot:
            # Visually rotate this layer's sprite.
            # positions[] already accounts for orbital movement from ancestor
            # rotations, so we just need to rotate the sprite in place around
            # its connection anchor and adjust the blit offset accordingly.
            conn = comp['connections'].get(lname)
            if conn:
                ax, ay = conn['child_anchor']
            else:
                ax = native.get_width() // 2
                ay = native.get_height() // 2

            ow, oh = native.get_size()
            rotated = pygame.transform.rotate(native, -rot)  # pygame uses CCW
            rw, rh = rotated.get_size()
            import math
            rad = math.radians(-rot)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            dx, dy = ax - ow / 2, ay - oh / 2
            new_ax = rw / 2 + dx * cos_a - dy * sin_a
            new_ay = rh / 2 + dx * sin_a + dy * cos_a
            # Anchor should land at (px + ax, py + ay) in world space
            bx = px + ax - new_ax
            by = py + ay - new_ay
            surf = rotated

        sw, sh = surf.get_size()
        min_x = min(min_x, bx)
        min_y = min(min_y, by)
        max_x = max(max_x, bx + sw)
        max_y = max(max_y, by + sh)
        layer_data.append((lname, surf, bx, by))

    if min_x == float('inf'):
        return None

    total_w = int(max_x - min_x) + 1
    total_h = int(max_y - min_y) + 1
    if total_w <= 0 or total_h <= 0:
        return None

    composite = pygame.Surface((total_w, total_h), pygame.SRCALPHA)
    for lname, surf, bx, by in layer_data:
        opacity = layer_opacity.get(lname)
        tint = layer_tint.get(lname)
        if tint or (opacity is not None and opacity < 1.0):
            surf = surf.copy()
            if tint:
                tint_overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
                tint_overlay.fill((*tint, 64))
                surf.blit(tint_overlay, (0, 0),
                          special_flags=pygame.BLEND_RGBA_ADD)
            if opacity is not None and opacity < 1.0:
                alpha_factor = max(0, min(255, int(opacity * 255)))
                alpha_overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
                alpha_overlay.fill((255, 255, 255, alpha_factor))
                surf.blit(alpha_overlay, (0, 0),
                          special_flags=pygame.BLEND_RGBA_MULT)
        composite.blit(surf, (int(bx - min_x), int(by - min_y)))

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

    positions, _ = _resolve_composite_positions(comp)
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
    """Interpolate offset_x, offset_y, rotation_deg, variant_name, tint, opacity at time_ms."""
    if not keyframes:
        return 0, 0, 0.0, None, None, 1.0
    if len(keyframes) == 1:
        k = keyframes[0]
        return (k['offset_x'], k['offset_y'], k['rotation_deg'],
                k.get('variant_name'), k.get('tint'), k.get('opacity', 1.0))
    prev = keyframes[0]
    nxt = prev
    for kf in keyframes:
        if kf['time_ms'] > time_ms:
            nxt = kf
            break
        prev = kf
    else:
        return (prev['offset_x'], prev['offset_y'], prev['rotation_deg'],
                prev.get('variant_name'), prev.get('tint'),
                prev.get('opacity', 1.0))
    if prev['time_ms'] == nxt['time_ms']:
        return (prev['offset_x'], prev['offset_y'], prev['rotation_deg'],
                prev.get('variant_name'), prev.get('tint'),
                prev.get('opacity', 1.0))
    t = (time_ms - prev['time_ms']) / (nxt['time_ms'] - prev['time_ms'])
    # Interpolate tint
    tint = None
    pt, nt = prev.get('tint'), nxt.get('tint')
    if pt and nt:
        tint = (int(_lerp(pt[0], nt[0], t)),
                int(_lerp(pt[1], nt[1], t)),
                int(_lerp(pt[2], nt[2], t)))
    elif pt:
        tint = pt
    elif nt:
        tint = nt
    return (_lerp(prev['offset_x'], nxt['offset_x'], t),
            _lerp(prev['offset_y'], nxt['offset_y'], t),
            _lerp(prev['rotation_deg'], nxt['rotation_deg'], t),
            prev.get('variant_name') or nxt.get('variant_name'),
            tint,
            _lerp(prev.get('opacity', 1.0), nxt.get('opacity', 1.0), t))


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

    scale = block_size / 32 * tile_scale

    frames = []
    step = max(1, frame_interval_ms)
    num_frames = max(1, duration // step)

    for i in range(num_frames):
        t = i * step
        sprite_overrides = {}
        offset_overrides = {}

        layer_opacity = {}
        layer_tint = {}
        rotation_overrides = {}
        for layer_name, kfs in anim['keyframes'].items():
            ox, oy, rot, var, tint, opacity = _interp_keyframes(kfs, t)
            offset_overrides[layer_name] = (int(ox), int(oy))
            if rot:
                rotation_overrides[layer_name] = rot
            if opacity < 1.0:
                layer_opacity[layer_name] = max(0.0, min(1.0, opacity))
            if tint:
                layer_tint[layer_name] = tint
            if var:
                var_sprites = comp['variants'].get(layer_name, {})
                spr = var_sprites.get(var)
                if spr:
                    sprite_overrides[layer_name] = spr

        # Resolve positions with offsets and rotations so children
        # inherit parent movement and rotation
        positions, cumulative_rot = _resolve_composite_positions(
            comp, offset_overrides, rotation_overrides)
        result = _assemble_composite_native(comp, positions,
                                             sprite_overrides,
                                             layer_opacity,
                                             layer_tint,
                                             cumulative_rot)
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

    # Apply time_scale: >1.0 speeds up, <1.0 slows down
    time_scale = anim.get('time_scale', 1.0)
    scaled_time = int(time_ms * time_scale) if time_scale != 1.0 else time_ms

    # Map scaled time to frame index
    step = max(1, frame_interval_ms)
    if anim['loop']:
        t = scaled_time % duration
    else:
        t = min(scaled_time, duration - 1)
    idx = min(t // step, len(frames) - 1)
    return frames[idx]
