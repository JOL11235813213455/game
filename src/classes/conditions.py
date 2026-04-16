"""Status effect conditions — Phase 1 of the FSM adoption plan.

Eight canonical conditions, implemented as lightweight classes rather
than rows in a DB table. Each condition:

  * applies stat modifiers via the existing Stats.mods layer (with
    source='condition:<name>' for clean attribution and removal)
  * optionally ticks damage or healing at a fixed interval
  * optionally gates actions by driving Creature.action_state
    (the compound FSM: normal/stunned/sleeping/dead)
  * stores applied_by_uid for kill-credit routing through the
    reward system (see Q1.8 decision)
  * expires at an absolute tick via sim.events

Stacking rule (Q1.4): applying the same condition again refreshes
duration and takes max severity. No additive stacking. Buffs never
stack — a second Blessed just refreshes duration.

Resistance rule (Q1.5): d20 contest on application, VIT for physical
/ INT for mental. Auto-success for buffs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.creature import Creature


# ---------------------------------------------------------------------------
# Registry / metadata
# ---------------------------------------------------------------------------

# Category drives which stat is rolled for resistance, and whether the
# condition gates actions through the compound action_state FSM.
_PHYSICAL = 'physical'
_MENTAL = 'mental'
_BUFF = 'buff'


@dataclass
class ConditionSpec:
    """Static metadata for a condition type."""
    name: str
    category: str
    max_severity: int = 3
    default_duration_ms: int = 10_000
    tick_interval_ms: int | None = None   # None = no periodic tick
    gates_action: bool = False            # True → drives action_state
    is_buff: bool = False                 # True → no resistance check
    description: str = ''


# The canonical set. Matches the Phase 1 Q1.1 decision exactly.
CONDITION_SPECS: dict[str, ConditionSpec] = {
    'poisoned': ConditionSpec(
        'poisoned', _PHYSICAL, max_severity=3,
        default_duration_ms=10_000, tick_interval_ms=2_000,
        description='DoT via tick damage; VIT-resistable.'),
    'bleeding': ConditionSpec(
        'bleeding', _PHYSICAL, max_severity=3,
        default_duration_ms=15_000, tick_interval_ms=3_000,
        description='DoT; cleared by healing above 50% HP.'),
    'burning': ConditionSpec(
        'burning', _PHYSICAL, max_severity=3,
        default_duration_ms=8_000, tick_interval_ms=1_500,
        description='DoT; terrain spread is a future extension.'),
    'stunned': ConditionSpec(
        'stunned', _PHYSICAL, max_severity=2,
        default_duration_ms=3_000, gates_action=True,
        description='Blocks action selection; short duration.'),
    'sleeping': ConditionSpec(
        'sleeping', _MENTAL, max_severity=2,
        default_duration_ms=30_000, gates_action=True,
        description='Blocks action selection; dispelled by damage.'),
    'afraid': ConditionSpec(
        'afraid', _MENTAL, max_severity=3,
        default_duration_ms=12_000,
        description='Weakens the creature; NN learns to flee via obs.'),
    'blessed': ConditionSpec(
        'blessed', _BUFF, max_severity=3,
        default_duration_ms=20_000, is_buff=True,
        description='Flat boost to contests while active.'),
    'regenerating': ConditionSpec(
        'regenerating', _BUFF, max_severity=3,
        default_duration_ms=10_000, tick_interval_ms=2_000,
        is_buff=True,
        description='Heals over time.'),
}

# Canonical order — observation vector relies on this being stable.
CONDITION_ORDER: list[str] = [
    'poisoned', 'bleeding', 'burning', 'stunned',
    'sleeping', 'afraid', 'blessed', 'regenerating',
]
assert len(CONDITION_ORDER) == len(CONDITION_SPECS)


# ---------------------------------------------------------------------------
# Stat modifier tables — per condition, per severity
# ---------------------------------------------------------------------------
#
# All values are flat integer deltas applied through Stats.mods. Kept
# small (±1..±3 at max severity) to play nicely with the D&D-style
# (base-10)//2 modifier math.

def _stat_mods_for(name: str, severity: int) -> list[tuple[str, int]]:
    from classes.stats import Stat
    sev = max(1, min(3, severity))
    if name == 'afraid':
        return [(Stat.STR, -sev), (Stat.AGL, -1)]
    if name == 'burning':
        # The heat is distracting — minor PER penalty regardless of sev.
        return [(Stat.PER, -1)]
    if name == 'blessed':
        # Generic contest boost: a touch of everything the contest rolls use.
        return [(Stat.STR, sev), (Stat.AGL, sev), (Stat.VIT, sev)]
    # Poisoned / Bleeding / Stunned / Sleeping / Regenerating: no stat mods
    # (their effect is HP tick or action gating, not stat manipulation).
    return []


# ---------------------------------------------------------------------------
# Runtime condition instance
# ---------------------------------------------------------------------------

@dataclass
class Condition:
    """Active condition on a creature.

    Not a Trackable — lives in ``creature.conditions`` dict, serialized
    via the creature's pickle. Tickets for scheduled events are
    stored on the instance so they can be cancelled if the condition
    is removed early (e.g. cure, damage waking a sleeper).
    """
    name: str
    severity: int = 1
    applied_by_uid: int | None = None
    applied_at_tick: int = 0
    expires_at: int = 0
    # Scheduled-event tickets for cleanup
    expire_ticket: int | None = None
    tick_ticket: int | None = None

    @property
    def spec(self) -> ConditionSpec:
        return CONDITION_SPECS[self.name]


# ---------------------------------------------------------------------------
# Damage-per-tick resolution
# ---------------------------------------------------------------------------

def damage_for_tick(cond: Condition) -> int:
    """HP delta inflicted (or healed) on a single tick of a ticking
    condition. Positive = damage, negative = healing.

    Poisoned:   severity * 1
    Bleeding:   severity * 2 (gnarlier, but shorter window)
    Burning:    severity * 3 (even gnarlier)
    Regenerating: -(severity * 2)   (healing)
    Other:      0
    """
    sev = max(1, cond.severity)
    if cond.name == 'poisoned':
        return sev * 1
    if cond.name == 'bleeding':
        return sev * 2
    if cond.name == 'burning':
        return sev * 3
    if cond.name == 'regenerating':
        return -(sev * 2)
    return 0


# ---------------------------------------------------------------------------
# Resistance contest
# ---------------------------------------------------------------------------

def resist_condition(target: 'Creature', source: 'Creature | None',
                     spec: ConditionSpec, severity: int) -> bool:
    """Return True if the target SUCCESSFULLY RESISTS the condition.

    Buffs always succeed (no resistance — you can't fail to be blessed).
    Physical conditions contest on VIT, mental on INT. Severity boosts
    the attacker's roll.
    """
    if spec.is_buff:
        return False   # buffs apply automatically
    if source is None:
        # Environmental / unsourced: 50/50 roll against severity.
        import random
        return random.randint(1, 20) > severity * 4
    # Two d20 rolls with stat modifiers. Target wins ties (resists).
    import random
    from classes.stats import Stat
    stat = Stat.VIT if spec.category == _PHYSICAL else Stat.INT
    t_mod = (target.stats.active[stat]() - 10) // 2
    a_mod = (source.stats.active[Stat.STR if spec.category == _PHYSICAL
                                  else Stat.CHR]() - 10) // 2 + severity
    t_roll = random.randint(1, 20) + t_mod
    a_roll = random.randint(1, 20) + a_mod
    return t_roll >= a_roll
