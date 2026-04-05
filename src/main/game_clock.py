"""
Game clock that maps real time to a 24-hour day cycle.

1 real minute = 1 game hour  →  24 real minutes = 1 full day.

The sun rises at 06:00 in the east and sets at 18:00 in the west.
The moon mirrors the same arc from 18:00 to 06:00.

Moon phase: 28-day cycle.  Day 0 = full moon (brightest night),
day 14 = new moon (darkest night).
"""

import math

# 1 real minute = 1 game hour → 60 real seconds per game hour
SECONDS_PER_GAME_HOUR = 60.0

SUNRISE    = 6.0    # 06:00
SUNSET     = 18.0   # 18:00
LUNAR_DAYS = 28.0   # days per lunar cycle


class GameClock:

    def __init__(self, start_hour: float = 8.0):
        self._elapsed: float = 0.0          # real seconds elapsed
        self._start_hour: float = start_hour

    def update(self, dt_seconds: float):
        """Advance clock by real-time delta (seconds)."""
        self._elapsed += dt_seconds

    @property
    def total_hours(self) -> float:
        """Total game hours elapsed since start."""
        return self._start_hour + self._elapsed / SECONDS_PER_GAME_HOUR

    @property
    def hour(self) -> float:
        """Current game hour as a float (0.0 – 24.0)."""
        return self.total_hours % 24.0

    @property
    def day(self) -> int:
        """Current game day (0-based)."""
        return int(self.total_hours // 24.0)

    @property
    def is_day(self) -> bool:
        return SUNRISE <= self.hour < SUNSET

    @property
    def sun_elevation(self) -> float:
        """Sun elevation in radians.  0 = horizon, π/2 = zenith.
        Returns 0 when the sun is below the horizon."""
        h = self.hour
        if h < SUNRISE or h >= SUNSET:
            return 0.0
        # Fraction of daylight elapsed: 0 at sunrise, 1 at sunset
        t = (h - SUNRISE) / (SUNSET - SUNRISE)
        return math.sin(t * math.pi)  # peaks at 1.0 (≡ π/2 elevation) at noon

    @property
    def moon_elevation(self) -> float:
        """Moon elevation, same curve but for the night half."""
        h = self.hour
        if SUNRISE <= h < SUNSET:
            return 0.0
        # Map night hours to 0..1
        if h >= SUNSET:
            t = (h - SUNSET) / (24.0 - SUNSET + SUNRISE)
        else:
            t = (h + 24.0 - SUNSET) / (24.0 - SUNSET + SUNRISE)
        return math.sin(t * math.pi)

    @property
    def moon_phase(self) -> float:
        """Moon phase as 0.0–1.0.  0.0 = full moon, 0.5 = new moon, 1.0 = full again."""
        return (self.total_hours / 24.0 % LUNAR_DAYS) / LUNAR_DAYS

    @property
    def moon_brightness(self) -> float:
        """0.0 (new moon, darkest) to 1.0 (full moon, brightest).
        Cosine curve: full at phase 0, new at phase 0.5."""
        return (math.cos(self.moon_phase * 2.0 * math.pi) + 1.0) / 2.0

    @property
    def moon_phase_name(self) -> str:
        p = self.moon_phase
        if p < 0.0625 or p >= 0.9375:
            return 'Full Moon'
        if p < 0.1875:
            return 'Waning Gibbous'
        if p < 0.3125:
            return 'Third Quarter'
        if p < 0.4375:
            return 'Waning Crescent'
        if p < 0.5625:
            return 'New Moon'
        if p < 0.6875:
            return 'Waxing Crescent'
        if p < 0.8125:
            return 'First Quarter'
        return 'Waxing Gibbous'

    @property
    def sun_direction(self) -> tuple[float, float]:
        """Unit vector (dx, dy) for shadow casting on the ground plane.
        East = +x, West = -x.  Shadow falls opposite the sun.
        At sunrise dx = -1 (shadow points west), at noon dx = 0 (straight down),
        at sunset dx = +1 (shadow points east).
        dy is always positive (shadow falls "towards the viewer" in 3/4 view)."""
        h = self.hour
        if h < SUNRISE or h >= SUNSET:
            return (0.0, 0.0)
        t = (h - SUNRISE) / (SUNSET - SUNRISE)  # 0..1 over the day
        # Sun azimuth goes east→south→west.
        # Shadow direction is opposite: west→north→east
        # In screen space: east = +x, south = +y for 3/4 top-down
        # Shadow dx: -cos(π*t)  → -1 at sunrise, 0 at noon, +1 at sunset
        # Shadow dy: we want a slight forward component (toward viewer = +y)
        #            Use a small fixed amount scaled by elevation
        dx = -math.cos(math.pi * t)
        dy = 0.3  # constant slight downward lean for 3/4 perspective
        length = math.sqrt(dx * dx + dy * dy)
        return (dx / length, dy / length)

    @property
    def shadow_length_factor(self) -> float:
        """Multiplier for shadow offset distance.
        Long shadows at dawn/dusk (low elevation), short at noon.
        Returns 0 at night."""
        elev = self.sun_elevation
        if elev <= 0:
            return 0.0
        # At low elevation (elev→0): long shadow.  At zenith (elev→1): short.
        # shadow length ∝ 1/tan(elevation_angle), but we use elev as sin(angle)
        # so tan ≈ sin/cos.  We clamp to avoid infinity.
        clamped = max(elev, 0.15)
        cos_e = math.sqrt(1.0 - clamped * clamped)
        return cos_e / clamped  # ~6.5 at dawn, ~0.0 at noon

    def format_time(self) -> str:
        """Return 'HH:MM' string for display."""
        h = self.hour
        hh = int(h) % 24
        mm = int((h - int(h)) * 60)
        return f'{hh:02d}:{mm:02d}'

    def format_period(self) -> str:
        """Return a human-readable period name."""
        h = self.hour
        if 5.0 <= h < 7.0:
            return 'Dawn'
        if 7.0 <= h < 12.0:
            return 'Morning'
        if 12.0 <= h < 14.0:
            return 'Noon'
        if 14.0 <= h < 17.0:
            return 'Afternoon'
        if 17.0 <= h < 19.0:
            return 'Dusk'
        if 19.0 <= h < 22.0:
            return 'Evening'
        return 'Night'
