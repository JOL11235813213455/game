"""
Jobs and schedules for creatures.

A `Job` is a small data record describing what a creature does for a
living — which tile purpose counts as "work," when they're expected
to be working, and what they get paid per successful tick.

A `Schedule` is a mapping from hour-of-day band to a high-level
activity label: ``sleep``, ``work``, or ``open``. During ``work``
bands, jobbed creatures earn wages; during ``sleep`` bands, SLEEP
restores more; during ``open`` bands, the creature is free.

Key design notes:
  * There is ONE :class:`~classes.actions.Action.JOB` action for every
    profession. The action dispatches to :meth:`Creature.do_job`,
    which reads ``creature.job`` and runs the right effect. This keeps
    the action space compact and lets a creature switch jobs without
    retraining a new action head.
  * Wanderers have ``creature.job = None`` and a minimal schedule with
    only ``sleep`` and ``open`` bands. They're free to do any action.
  * Schedules live on the creature, not on the job. The job provides a
    template at assignment, but per-creature variation (night owls,
    early risers) is allowed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from classes.stats import Stat


# Activity labels used across schedules. Keep this list tight — the
# observation one-hot depends on it.
ACTIVITIES = ('sleep', 'work', 'open')


@dataclass
class Schedule:
    """A creature's daily schedule.

    ``bands`` is a dict ``{activity: [(start_hour, end_hour), ...]}``.
    Hour ranges use 0..24 floats and may wrap midnight (start > end).
    Any hour not covered by an explicit band defaults to ``'open'``.
    """
    bands: dict = field(default_factory=dict)

    def activity_at(self, hour: float) -> str:
        """Return the activity label for a given hour. Falls back to 'open'."""
        for activity, ranges in self.bands.items():
            for (start, end) in ranges:
                if start <= end:
                    if start <= hour < end:
                        return activity
                else:  # wraps midnight
                    if hour >= start or hour < end:
                        return activity
        return 'open'

    def in_work_hours(self, hour: float) -> bool:
        return self.activity_at(hour) == 'work'

    def in_sleep_hours(self, hour: float) -> bool:
        return self.activity_at(hour) == 'sleep'

    def in_open_hours(self, hour: float) -> bool:
        return self.activity_at(hour) == 'open'


# ---------------------------------------------------------------------------
# Default schedules
# ---------------------------------------------------------------------------
# Day worker: typical 08–17 work, 22–06 sleep, meals & leisure in between
DAY_WORKER = Schedule(bands={
    'sleep': [(22.0, 6.0)],
    'work':  [(8.0, 12.0), (13.0, 17.0)],   # split shift with midday break
    'open':  [(6.0, 8.0), (12.0, 13.0), (17.0, 22.0)],
})

# Wanderer: no work, long active day
WANDERER = Schedule(bands={
    'sleep': [(22.0, 6.0)],
    'open':  [(6.0, 22.0)],
})

# Night worker (guards, watchmen): active dusk to dawn
NIGHT_WORKER = Schedule(bands={
    'sleep': [(8.0, 16.0)],
    'work':  [(18.0, 24.0), (0.0, 6.0)],
    'open':  [(16.0, 18.0), (6.0, 8.0)],
})


# ---------------------------------------------------------------------------
# Job definitions
# ---------------------------------------------------------------------------
@dataclass
class Job:
    """A profession assigned to a creature.

    Attributes:
        name: display name
        purpose: tile purpose this job aligns with (one of TILE_PURPOSES)
        schedule: default schedule template; copied into ``creature.schedule``
            when the job is assigned
        wage_per_tick: gold paid per successful JOB tick during work hours
        required_stat: stat gated at ``required_level`` to qualify
        required_level: minimum stat value
        workplace_purposes: tuple of purposes that count as "at work" —
            usually just ``(purpose,)`` but some jobs work across tile types
    """
    name: str
    purpose: str
    schedule: Schedule
    wage_per_tick: float = 1.0
    required_stat: Stat = Stat.STR
    required_level: int = 8
    workplace_purposes: tuple = ()

    def __post_init__(self):
        if not self.workplace_purposes:
            self.workplace_purposes = (self.purpose,)


# The default job catalog. Arena generator draws from this.
DEFAULT_JOBS = {
    'farmer':  Job('farmer',  'farming',  DAY_WORKER,   wage_per_tick=1.0,
                   required_stat=Stat.VIT, required_level=8),
    'miner':   Job('miner',   'mining',   DAY_WORKER,   wage_per_tick=1.5,
                   required_stat=Stat.STR, required_level=10),
    'guard':   Job('guard',   'guarding', NIGHT_WORKER, wage_per_tick=1.2,
                   required_stat=Stat.STR, required_level=10),
    'trader':  Job('trader',  'trading',  DAY_WORKER,   wage_per_tick=1.3,
                   required_stat=Stat.CHR, required_level=10),
    'crafter': Job('crafter', 'crafting', DAY_WORKER,   wage_per_tick=1.2,
                   required_stat=Stat.INT, required_level=10),
    'hunter':  Job('hunter',  'hunting',  DAY_WORKER,   wage_per_tick=1.1,
                   required_stat=Stat.PER, required_level=10),
    'healer':  Job('healer',  'healing',  DAY_WORKER,   wage_per_tick=1.4,
                   required_stat=Stat.INT, required_level=12),
}


def qualifies_for(creature, job: Job) -> bool:
    """Check whether a creature meets the stat requirements for a job."""
    stat_val = creature.stats.active[job.required_stat]()
    return stat_val >= job.required_level


def best_job_for(creature, catalog: dict = None) -> Job | None:
    """Return the highest-paying job this creature qualifies for. None if
    no job matches (creature becomes a wanderer)."""
    catalog = catalog or DEFAULT_JOBS
    eligible = [j for j in catalog.values() if qualifies_for(creature, j)]
    if not eligible:
        return None
    return max(eligible, key=lambda j: j.wage_per_tick)
