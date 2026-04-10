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
    purpose: str        = None   # purpose this object projects (trading, crafting, etc.)
    purpose_distance: float = 0.5  # 0-1 fraction of viewer's sight range

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
        self._location = None  # raw storage for the property
        if location is None:
            from classes.maps import MapKey
            location = MapKey()
        self.anim = AnimationState()
        self._composite_anim = None
        self._composite_anim_start = 0
        self._composite_flip_h = False
        # Set current_map BEFORE location so the location setter can
        # register with the map's spatial grid on first assignment.
        self.current_map = current_map
        self.location = location

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, new_loc):
        """Base WorldObject setter: just stores the value.

        Creature overrides this to also update the map's spatial grid
        on every change, so sight queries can use cell buckets instead
        of scanning every creature on the map.
        """
        self._location = new_loc

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
        """Look up and play an animation for this object's species/type + behavior.

        For composite objects, checks composite_anim_bindings first.
        Falls back to simple frame animations if no composite binding exists.
        """
        target = getattr(self, 'species', None) or self.sprite_name
        if target is None:
            return

        # Try composite animation bindings first
        if self.composite_name:
            from data.db import COMPOSITE_ANIM_BINDINGS
            binding = COMPOSITE_ANIM_BINDINGS.get((target, behavior))
            if binding is None and behavior != fallback:
                binding = COMPOSITE_ANIM_BINDINGS.get((target, fallback))
            if binding is not None:
                anim_name = binding['animation_name']
                self._composite_flip_h = binding['flip_h']
                if self._composite_anim != anim_name:
                    self.play_composite_anim(anim_name)
                return
            # No composite binding — show static pose
            self.stop_composite_anim()
            self._composite_flip_h = False
            return

        # Simple frame animation fallback
        from data.db import ANIM_BINDINGS, ANIMATIONS
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
                return self._apply_composite_flip(result)

        # Static composite pose (cached)
        result = get_composite(self.composite_name, block_size,
                               self.tile_scale, variant_key)
        if result:
            return self._apply_composite_flip(result)
        return result

    def _apply_composite_flip(self, result):
        """Horizontally flip a composite surface + offset if flip_h is set."""
        if not self._composite_flip_h:
            return result
        import pygame
        surface, (blit_dx, blit_dy) = result
        flipped = pygame.transform.flip(surface, True, False)
        # Mirror the x offset: the surface width stays the same,
        # but the blit offset needs to reflect around tile center
        from main.config import get_block_size
        tile_cx = get_block_size() // 2
        new_dx = 2 * tile_cx - blit_dx - surface.get_width()
        return flipped, (new_dx, blit_dy)

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
