from __future__ import annotations
import weakref
from collections import defaultdict
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

    # Per-map spatial index: map_id → WeakSet of WorldObjects on that map
    _by_map: dict[int, weakref.WeakSet] = defaultdict(weakref.WeakSet)

    @classmethod
    def on_map(cls, game_map) -> list['WorldObject']:
        """Return all WorldObjects on the given map. O(1) lookup."""
        return list(cls._by_map.get(id(game_map), []))

    @classmethod
    def colliders_on_map(cls, game_map) -> list['WorldObject']:
        """Return WorldObjects with collision=True on the given map."""
        return [o for o in cls._by_map.get(id(game_map), [])
                if o.collision]

    def __init__(self, current_map: Map = None, location=None):
        super().__init__()
        self._current_map = None
        if location is None:
            from classes.maps import MapKey
            location = MapKey()
        self.location = location
        self.anim = AnimationState()
        # Set via property to register in _by_map
        self.current_map = current_map

    @property
    def current_map(self):
        return self._current_map

    @current_map.setter
    def current_map(self, new_map):
        old = self._current_map
        if old is not None:
            by = WorldObject._by_map.get(id(old))
            if by is not None:
                by.discard(self)
        self._current_map = new_map
        if new_map is not None:
            WorldObject._by_map[id(new_map)].add(self)

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

        from data.db import SPRITE_DATA
        from main.sprite_cache import get_scaled

        data = SPRITE_DATA.get(name)
        if data is None:
            return None

        cols = data['width']
        rows = len(data['pixels'])
        w = int(cols * (block_size / 32) * self.tile_scale)
        h = int(rows * (block_size / 32) * self.tile_scale)

        surface = get_scaled(name, w, h, block_size)
        if surface is None:
            return None

        # Compute blit offset so the action point lands on the tile center.
        from main.config import get_tile_height
        tile_cx = block_size // 2
        tile_cy = get_tile_height() // 2
        ap = data.get('action_point')
        if ap is not None:
            ap_sx = int(ap[0] * w / cols)
            ap_sy = int(ap[1] * h / rows)
        else:
            ap_sx = w // 2
            ap_sy = h
        blit_dx = tile_cx - ap_sx
        blit_dy = tile_cy - ap_sy

        return surface, (blit_dx, blit_dy)

    def _make_composite_surface(self, block_size: int):
        """Get cached composite surface, using pre-rendered animation frames when available."""
        from main.sprite_cache import get_composite, get_composite_anim_frame

        # Build variant key from current state (for variant overrides)
        variant_key = getattr(self, '_variant_overrides', ())

        # If a composite animation is playing, use pre-rendered frames
        comp_anim = getattr(self, '_composite_anim', None)
        if comp_anim is not None:
            import pygame
            time_ms = pygame.time.get_ticks() - getattr(self, '_composite_anim_start', 0)
            result = get_composite_anim_frame(
                self.composite_name, comp_anim, time_ms,
                block_size, self.tile_scale)
            if result:
                return result

        # Static composite pose (cached)
        return get_composite(self.composite_name, block_size,
                             self.tile_scale, variant_key)

    def play_composite_anim(self, anim_name: str):
        """Start playing a pre-rendered composite animation."""
        import pygame
        self._composite_anim = anim_name
        self._composite_anim_start = pygame.time.get_ticks()

    def stop_composite_anim(self):
        """Stop composite animation, return to static pose."""
        self._composite_anim = None

    def set_variant(self, layer_name: str, sprite_name: str):
        """Override a layer's sprite (e.g. swap face to 'happy')."""
        overrides = dict(getattr(self, '_variant_overrides', ()))
        overrides[layer_name] = sprite_name
        self._variant_overrides = tuple(sorted(overrides.items()))

    def clear_variants(self):
        """Reset all variant overrides to defaults."""
        self._variant_overrides = ()
