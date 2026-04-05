"""
Day/night lighting overlay and per-sprite shadow/highlight effects.

All functions work with the GameClock's hour value (0.0–24.0).
The overlay is a single full-screen blit per frame — very cheap.
"""

import math
import pygame

from main.game_clock import SUNRISE, SUNSET


# ---- ambient overlay --------------------------------------------------------

# Keyframes: (hour, (R, G, B, A)) — linearly interpolated between neighbours.
# These define the tint colour multiplied onto the scene.
# A=0 means no tint (full brightness); higher A dims and colours the scene.
_AMBIENT_KEYS = [
    ( 0.0, ( 15,  20,  60, 140)),  # midnight — deep blue, fairly dark
    ( 3.0, ( 10,  15,  50, 150)),  # deepest night
    ( 5.0, ( 40,  30,  50, 130)),  # pre-dawn — purple hint
    ( 6.0, ( 90,  60,  30,  80)),  # dawn — warm orange
    ( 7.5, ( 40,  35,  20,  30)),  # early morning — faint warm
    (12.0, (  0,   0,   0,   0)),  # noon — no tint
    (16.5, ( 30,  25,  10,  20)),  # late afternoon — slight warm
    (18.0, ( 90,  50,  20,  80)),  # dusk — orange
    (19.0, ( 50,  30,  60, 110)),  # twilight — purple
    (20.0, ( 20,  25,  65, 130)),  # night — blue
    (24.0, ( 15,  20,  60, 140)),  # wraps to midnight
]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ambient_color(hour: float, moon_brightness: float = 1.0) -> tuple[int, int, int, int]:
    """Return (R, G, B, A) tint for the given game hour.

    moon_brightness (0.0–1.0) modulates nighttime alpha:
      1.0 = full moon (base night values),
      0.0 = new moon (night alpha increased by up to 50%).
    Daytime keyframes (alpha near 0) are unaffected.
    """
    hour = hour % 24.0
    prev = _AMBIENT_KEYS[0]
    for kf in _AMBIENT_KEYS[1:]:
        if hour <= kf[0]:
            t = (hour - prev[0]) / max(kf[0] - prev[0], 0.001)
            rgba = [int(_lerp(prev[1][i], kf[1][i], t)) for i in range(4)]
            break
        prev = kf
    else:
        rgba = list(_AMBIENT_KEYS[-1][1])

    # Modulate: when base alpha is significant (nighttime), darken on new moon.
    # Extra darkness at new moon: up to 50% more alpha.
    if rgba[3] > 20:
        extra = int(rgba[3] * 0.5 * (1.0 - moon_brightness))
        rgba[3] = min(rgba[3] + extra, 220)

    return tuple(rgba)


_overlay_cache: dict[tuple, pygame.Surface] = {}


def draw_ambient_overlay(surface: pygame.Surface, hour: float,
                         moon_brightness: float = 1.0):
    """Blit a full-screen tint onto the scene.  Cached per RGBA value."""
    rgba = ambient_color(hour, moon_brightness)
    if rgba[3] == 0:
        return
    sw, sh = surface.get_size()
    key = (sw, sh, rgba)
    if key not in _overlay_cache:
        ov = pygame.Surface((sw, sh), pygame.SRCALPHA)
        ov.fill(rgba)
        _overlay_cache[key] = ov
        if len(_overlay_cache) > 32:
            oldest = next(iter(_overlay_cache))
            del _overlay_cache[oldest]
    surface.blit(_overlay_cache[key], (0, 0))


# ---- per-sprite shadow ------------------------------------------------------

def make_shadow(sprite_surface: pygame.Surface,
                sun_dir: tuple[float, float],
                shadow_len: float,
                block_size: int) -> tuple[pygame.Surface, int, int] | None:
    """Create a shadow surface for a sprite.

    The shadow is a flat ellipse locked to the sprite's feet.
    It never moves vertically — only stretches horizontally
    in the direction opposite the sun.
    """
    if shadow_len <= 0 or (sun_dir[0] == 0 and sun_dir[1] == 0):
        return None

    w, h = sprite_surface.get_size()
    if w == 0 or h == 0:
        return None

    # Shadow base size proportional to sprite dimensions.
    # Width starts at sprite width, stretches with sun angle.
    # Height is a fraction of sprite height to keep it flat on the ground.
    stretch = 1.0 + min(shadow_len, 2.5) * 0.5  # 1.0x at noon → ~2.25x at dawn
    shadow_w = max(int(w * stretch), 1)
    shadow_h = max(int(h * 0.2), 1)

    shadow = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow, (0, 0, 0, 45),
                        (0, 0, shadow_w, shadow_h))

    # Horizontal shift: shadow extends away from the sun.
    # sun_dir[0] points away from sun, so shadow shifts in that direction.
    shift_px = int(sun_dir[0] * (shadow_w - w) * 0.5)

    # ox: center under sprite, then shift with sun
    ox = (w - shadow_w) // 2 + shift_px
    # oy: locked to sprite feet (bottom of sprite), vertically centered on the ellipse
    oy = h - shadow_h // 2

    return shadow, ox, oy


# ---- per-sprite top highlight -----------------------------------------------

_gradient_cache: dict[tuple, tuple[pygame.Surface, pygame.Surface]] = {}


def _get_gradient(w: int, h: int, bucket: int, intensity: float):
    """Return cached (brighten, darken) gradient surfaces for a given size + intensity."""
    key = (w, h, bucket)
    if key in _gradient_cache:
        return _gradient_cache[key]

    brighten = pygame.Surface((w, h), pygame.SRCALPHA)
    darken   = pygame.Surface((w, h), pygame.SRCALPHA)
    for row in range(h):
        t = 1.0 - row / max(h - 1, 1)
        b = int(intensity * t)
        d = int(intensity * (1.0 - t) * 0.6)
        if b > 0:
            pygame.draw.line(brighten, (b, b, b, b), (0, row), (w - 1, row))
        if d > 0:
            pygame.draw.line(darken, (d, d, d, d), (0, row), (w - 1, row))

    _gradient_cache[key] = (brighten, darken)
    if len(_gradient_cache) > 64:
        oldest = next(iter(_gradient_cache))
        del _gradient_cache[oldest]

    return brighten, darken


def apply_top_highlight(sprite_surface: pygame.Surface,
                        sun_elevation: float) -> pygame.Surface:
    """Return a copy with a smooth vertical lighting gradient.

    Top rows are gently brightened, bottom rows gently darkened,
    simulating top-down light.  Intensity scales with sun elevation.
    """
    if sun_elevation <= 0.05:
        return sprite_surface

    w, h = sprite_surface.get_size()
    if w == 0 or h == 0:
        return sprite_surface

    bucket = int(sun_elevation * 8)
    intensity = sun_elevation * 18

    brighten, darken = _get_gradient(w, h, bucket, intensity)

    result = sprite_surface.copy()
    result.blit(brighten, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
    result.blit(darken,   (0, 0), special_flags=pygame.BLEND_RGB_SUB)
    return result
