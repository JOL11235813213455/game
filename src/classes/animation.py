"""
Runtime animation state for WorldObjects.

Each animated object holds an AnimationState that tracks the current
animation name, frame index, and elapsed time.  Each tick, the caller
advances time; when enough ms have passed the frame advances.

The animation data itself lives in data.db.ANIMATIONS / ANIM_BINDINGS.
"""


class AnimationState:

    def __init__(self):
        self._anim_name: str | None = None
        self._frames: list[dict] = []   # [{sprite_name, duration_ms}, ...]
        self._frame_idx: int = 0
        self._elapsed_ms: float = 0.0
        self._looping: bool = True

    @property
    def current_sprite(self) -> str | None:
        """Return the sprite_name for the current frame, or None if no animation."""
        if not self._frames:
            return None
        return self._frames[self._frame_idx]['sprite_name']

    @property
    def animation_name(self) -> str | None:
        return self._anim_name

    @property
    def is_playing(self) -> bool:
        return bool(self._frames)

    def play(self, anim_name: str, frames: list[dict], loop: bool = True):
        """Start a new animation.  If already playing this animation, do nothing."""
        if self._anim_name == anim_name:
            return
        self._anim_name = anim_name
        self._frames = frames
        self._frame_idx = 0
        self._elapsed_ms = 0.0
        self._looping = loop

    def stop(self):
        """Stop the current animation and reset."""
        self._anim_name = None
        self._frames = []
        self._frame_idx = 0
        self._elapsed_ms = 0.0

    def update(self, dt_ms: float):
        """Advance animation time by dt_ms.  Advances frames as needed."""
        if not self._frames:
            return
        self._elapsed_ms += dt_ms
        dur = self._frames[self._frame_idx]['duration_ms']
        while self._elapsed_ms >= dur:
            self._elapsed_ms -= dur
            self._frame_idx += 1
            if self._frame_idx >= len(self._frames):
                if self._looping:
                    self._frame_idx = 0
                else:
                    self._frame_idx = len(self._frames) - 1
                    self._elapsed_ms = 0.0
                    return
            dur = self._frames[self._frame_idx]['duration_ms']
