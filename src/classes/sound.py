"""
Sound event system.

Sounds are lightweight, per-tick events that propagate through the
world without per-tile diffusion math. Emission writes a SoundEvent
into the map's per-tick sound buffer; perception is checked at query
time by computing whether the listener's distance to the source is
within the source volume minus an attenuation factor.

The point of this system is **gameplay perception**, not audio. The
NN observation gets a "I heard fighting east" signal that lets it
respond to events outside its visual range. Real audio output is
out of scope and would be added later.

**Sound types** are a small enum:
  - footstep    (volume 1.5) — emitted by movement actions
  - speech      (volume 4.0) — emitted by talk/share_rumor
  - combat      (volume 8.0) — emitted by melee/ranged/grapple
  - harvest     (volume 2.5) — emitted by harvest/farm/process
  - death_cry   (volume 12.0) — emitted on death
  - hatch       (volume 3.0) — emitted on egg hatch
  - drop        (volume 1.0) — emitted on drop
  - struggle    (volume 6.0) — emitted on failed grapple/forced action

**Per-creature hearing buffer** is a deque of recent SoundEvents
the creature heard, with their tick stamp. The observation function
reads from it to build the hearing section. Buffer size 16 events,
oldest dropped on overflow, decays after ~5 ticks.

**Map.sound_events** is the per-tick scratch buffer. Cleared at the
start of each Simulation.step before action dispatch fires. Events
emitted during the tick are stored here, and the perception pass at
the end of the tick reads them and distributes to listeners.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass


# Sound type catalog. Volume is the source intensity in tile units —
# the sound is heard by listeners within (volume - listener_attenuation)
# Manhattan distance.
SOUND_TYPES = (
    'footstep', 'speech', 'combat', 'harvest', 'death_cry',
    'hatch', 'drop', 'struggle',
)
SOUND_TYPE_INDEX = {t: i for i, t in enumerate(SOUND_TYPES)}
NUM_SOUND_TYPES = len(SOUND_TYPES)

DEFAULT_VOLUME = {
    'footstep':  1.5,
    'speech':    4.0,
    'combat':    8.0,
    'harvest':   2.5,
    'death_cry': 12.0,
    'hatch':     3.0,
    'drop':      1.0,
    'struggle':  6.0,
}


@dataclass
class SoundEvent:
    source_uid: int
    source_x: int
    source_y: int
    source_z: int
    type: str
    volume: float
    tick: int


HEARING_BUFFER_MAX = 16
HEARING_DECAY_TICKS = 5  # events older than this get pruned on read


def emit_sound(creature, sound_type: str, volume: float = None, tick: int = 0):
    """Record a sound event from ``creature``.

    Stores the event in the map's per-tick sound buffer; listeners
    pick it up in their observation pass via ``deliver_sounds``.
    No-op if the creature isn't on a map.
    """
    if creature.current_map is None:
        return
    if volume is None:
        volume = DEFAULT_VOLUME.get(sound_type, 2.0)
    if not hasattr(creature.current_map, '_sound_events'):
        creature.current_map._sound_events = []
    ev = SoundEvent(
        source_uid=creature.uid,
        source_x=creature.location.x,
        source_y=creature.location.y,
        source_z=creature.location.z,
        type=sound_type,
        volume=volume,
        tick=tick,
    )
    creature.current_map._sound_events.append(ev)
    creature._noise_emitted = getattr(creature, '_noise_emitted', 0.0) + volume


def clear_sounds(game_map):
    """Empty the per-tick sound buffer. Called at the top of each step."""
    if hasattr(game_map, '_sound_events'):
        game_map._sound_events.clear()


def deliver_sounds(creature, tick: int):
    """Walk the map's current sound buffer and add audible events to
    the creature's hearing buffer. Called once per creature per step,
    after action dispatch but before observation build.
    """
    game_map = creature.current_map
    if game_map is None or not hasattr(game_map, '_sound_events'):
        return
    if not hasattr(creature, '_hearing_buffer'):
        creature._hearing_buffer = deque(maxlen=HEARING_BUFFER_MAX)

    cx, cy, cz = creature.location.x, creature.location.y, creature.location.z
    for ev in game_map._sound_events:
        if ev.source_uid == creature.uid:
            continue  # don't hear yourself
        if ev.source_z != cz:
            continue  # different map level
        d = abs(cx - ev.source_x) + abs(cy - ev.source_y)
        if d <= ev.volume:
            creature._hearing_buffer.append(ev)


def prune_old(creature, tick: int):
    """Drop sound events from the hearing buffer that are older than
    the decay window."""
    if not hasattr(creature, '_hearing_buffer'):
        return
    cutoff = tick - HEARING_DECAY_TICKS
    while creature._hearing_buffer and creature._hearing_buffer[0].tick < cutoff:
        creature._hearing_buffer.popleft()


def hearing_observation(creature, tick: int) -> list[float]:
    """Return the 12-float hearing section for ``creature``.

    Layout (matches HEARING_OBS_SIZE constant):
      [0]    loudest_volume_norm        max recent sound volume / 12.0
      [1]    loudest_dx                 unit-vector x to loudest source
      [2]    loudest_dy                 unit-vector y to loudest source
      [3]    loudest_recency            (1 - age/decay) of loudest sound
      [4-11] count of each sound type heard recently (8 floats), one
              per SOUND_TYPES entry, normalized to count/5.0 capped
              at 1.0
    """
    prune_old(creature, tick)
    out = [0.0] * HEARING_OBS_SIZE
    if not hasattr(creature, '_hearing_buffer') or not creature._hearing_buffer:
        return out

    cx = creature.location.x
    cy = creature.location.y

    # Find loudest event
    loudest = None
    loudest_score = -1.0
    counts = [0] * NUM_SOUND_TYPES
    for ev in creature._hearing_buffer:
        score = ev.volume
        if score > loudest_score:
            loudest_score = score
            loudest = ev
        idx = SOUND_TYPE_INDEX.get(ev.type)
        if idx is not None:
            counts[idx] += 1

    if loudest is not None:
        dx = loudest.source_x - cx
        dy = loudest.source_y - cy
        mag = max(1, abs(dx) + abs(dy))
        out[0] = min(1.0, loudest.volume / 12.0)
        out[1] = dx / mag
        out[2] = dy / mag
        out[3] = max(0.0, 1.0 - (tick - loudest.tick) / HEARING_DECAY_TICKS)

    for i in range(NUM_SOUND_TYPES):
        out[4 + i] = min(1.0, counts[i] / 5.0)

    return out


HEARING_OBS_SIZE = 4 + NUM_SOUND_TYPES  # 4 metadata + 8 type counts = 12
