"""World cycles — Phase 3 of the FSM adoption plan.

Two independent FSMs owned by a Trackable singleton:

  * TimeOfDay FSM — 4 states (dawn / day / dusk / night), driven
    deterministically by GameClock.hour.
  * Weather FSM — 6 states (clear / overcast / rain / storm / fog
    / snow) with semi-Markov transitions. Expiry-driven via the
    shared ScheduledEventQueue. Biome bias will be added when the
    weather_transitions DB table lands; the MVP uses uniform
    transition weights across a small default palette.

Effects are surfaced through ``WorldCycles``:
  * light_level    — 0.0 (deep night) to 1.0 (noon)
  * visibility_mult — multiplier on perception ranges
  * sound_mult      — multiplier on hearing ranges

Creatures / rendering / observations read these values rather than
poking at FSM internals, per the Q3.5 decision.
"""
from __future__ import annotations

import random
from classes.trackable import Trackable
from classes.fsm import StateMachine, Transition


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIME_OF_DAY_STATES = ['dawn', 'day', 'dusk', 'night']
TIME_OF_DAY_IDX = {s: i for i, s in enumerate(TIME_OF_DAY_STATES)}

# Hour ranges (inclusive start, exclusive end). Anything outside = night.
TIME_OF_DAY_HOURS: dict[str, tuple[float, float]] = {
    'dawn':  (5.0, 7.0),
    'day':   (7.0, 19.0),
    'dusk':  (19.0, 21.0),
    # 'night' is the implicit complement: 21.0–24.0 plus 0.0–5.0
}


WEATHER_STATES = ['clear', 'overcast', 'rain', 'storm', 'fog', 'snow']
WEATHER_IDX = {s: i for i, s in enumerate(WEATHER_STATES)}

# Baseline visibility/sound multipliers per weather state. The
# creature SIGHT_RANGE / HEARING_RANGE formulas multiply the stat
# output by these when reading from WorldCycles.
WEATHER_EFFECTS = {
    'clear':    dict(visibility=1.00, sound=1.00),
    'overcast': dict(visibility=0.80, sound=1.00),
    'rain':     dict(visibility=0.70, sound=0.80),
    'storm':    dict(visibility=0.50, sound=0.80),
    'fog':      dict(visibility=0.40, sound=1.00),
    'snow':     dict(visibility=0.70, sound=0.90),
}

# Simple Markov transition probabilities keyed (from, to). Uniform
# baseline — biome bias will replace this when the DB table is
# seeded. Rows must sum to ≤ 1; missing mass stays in the current
# state (self-loop).
WEATHER_TRANSITIONS: dict[str, dict[str, float]] = {
    'clear':    {'overcast': 0.35, 'fog': 0.05},
    'overcast': {'clear': 0.30, 'rain': 0.25, 'snow': 0.05},
    'rain':     {'overcast': 0.30, 'storm': 0.15, 'clear': 0.10},
    'storm':    {'rain': 0.50, 'overcast': 0.20},
    'fog':      {'overcast': 0.35, 'clear': 0.25},
    'snow':     {'overcast': 0.40, 'clear': 0.15},
}

# Durations (in game-seconds ≈ sim ticks × tick_ms). Mean is the
# target; each transition schedules a random duration around this.
WEATHER_MEAN_DURATION_MS: dict[str, int] = {
    'clear':    90_000,
    'overcast': 60_000,
    'rain':     45_000,
    'storm':    20_000,
    'fog':      40_000,
    'snow':     60_000,
}


# ---------------------------------------------------------------------------
# Time-of-day helpers
# ---------------------------------------------------------------------------

def _time_of_day_for_hour(hour: float) -> str:
    """Return the time-of-day state that contains the given hour."""
    for state, (lo, hi) in TIME_OF_DAY_HOURS.items():
        if lo <= hour < hi:
            return state
    return 'night'


def _light_level_for_hour(hour: float) -> float:
    """Continuous light level, 0.0 (pre-dawn) to 1.0 (noon).

    Smooth ramp across dawn and dusk; flat at day/night maxima.
    """
    if hour < 5.0 or hour >= 21.0:
        return 0.2               # night base
    if 5.0 <= hour < 7.0:
        t = (hour - 5.0) / 2.0   # dawn ramp 0.3 → 1.0
        return 0.3 + 0.7 * t
    if 7.0 <= hour < 19.0:
        return 1.0
    # 19.0 → 21.0 dusk
    t = (hour - 19.0) / 2.0
    return 1.0 - 0.7 * t


# ---------------------------------------------------------------------------
# WorldCycles Trackable
# ---------------------------------------------------------------------------

class WorldCycles(Trackable):
    """Single globally-findable Trackable with two cycle FSMs.

    Attached to the Simulation at init. Rendering, perception, and
    observation code read from this (``sim.world_cycles``) or find
    it via ``WorldCycles.all()[0]``. Per Phase 3 Q3.5.
    """

    def __init__(self, game_clock=None):
        super().__init__()
        self.game_clock = game_clock
        # Both FSMs — use StateMachine so save/load path is uniform.
        self.time_of_day = StateMachine(
            owner=self, initial='day',
            states=TIME_OF_DAY_STATES,
            transitions=[
                # No triggers — deterministic advance via force() in tick()
            ],
        )
        self.weather = StateMachine(
            owner=self, initial='clear',
            states=WEATHER_STATES,
            transitions=[
                # No triggers — transitions happen via force() in tick()
                # driven by the expiry queue.
            ],
        )
        # Current derived values, cached each tick.
        self.light_level = 1.0
        self.visibility_mult = 1.0
        self.sound_mult = 1.0
        # Scheduled ticket id for the current weather transition.
        self._weather_ticket = None

    # ------------------------------------------------------------------
    def tick(self, sim) -> None:
        """Update time-of-day from game_clock and cache derived values.

        Weather is expiry-driven (transitions fire from sim.events)
        so this doesn't advance weather itself — only reads its
        current state to refresh visibility/sound multipliers.
        """
        if self.game_clock is None:
            return
        hour = self.game_clock.hour
        desired = _time_of_day_for_hour(hour)
        if desired != self.time_of_day.current:
            now = getattr(sim, 'now', 0) if sim is not None else 0
            old = self.time_of_day.current
            self.time_of_day.force(desired, now=now)
            # Emit time-of-day event for any subscribers.
            if sim is not None:
                for h in sim._event_handlers.get(f'time_of_day.{desired}', ()):
                    try:
                        h((old, desired))
                    except Exception:
                        pass
        self.light_level = _light_level_for_hour(hour)
        eff = WEATHER_EFFECTS[self.weather.current]
        self.visibility_mult = self.light_level * eff['visibility']
        self.sound_mult = eff['sound']

    # ------------------------------------------------------------------
    def seed_weather_schedule(self, sim, rng: random.Random | None = None) -> None:
        """Schedule the first weather transition.

        Called once by the Simulation after init. Subsequent
        transitions reschedule themselves in the expiry handler.
        """
        rng = rng or random
        now = getattr(sim, 'now', 0)
        mean = WEATHER_MEAN_DURATION_MS[self.weather.current]
        # Jitter 50%..150% of mean
        duration = int(mean * rng.uniform(0.5, 1.5))
        self._weather_ticket = sim.events.schedule(
            now + duration, 'weather_transition', None)

    def on_weather_transition(self, sim, rng: random.Random | None = None) -> None:
        """Pick and apply the next weather state, reschedule next change."""
        rng = rng or random
        probs = WEATHER_TRANSITIONS.get(self.weather.current, {})
        # Roll once: if outcome lands in a weighted slot, take it;
        # otherwise stay in the current state.
        roll = rng.random()
        cumulative = 0.0
        chosen = self.weather.current
        for state, p in probs.items():
            cumulative += p
            if roll < cumulative:
                chosen = state
                break
        old = self.weather.current
        if chosen != old:
            now = getattr(sim, 'now', 0)
            self.weather.force(chosen, now=now)
            # Emit event
            if sim is not None:
                for h in sim._event_handlers.get(f'weather.{chosen}', ()):
                    try:
                        h((old, chosen))
                    except Exception:
                        pass
        # Reschedule the next transition
        self.seed_weather_schedule(sim, rng=rng)
        # Refresh cached multipliers immediately
        self.tick(sim)
