"""Lifecycle FSM mixin — Phase 2 of FSM adoption.

Seven states: egg, gestating, juvenile, adult, elder, dying, dead.

Transitions are event-driven or expiry-driven via the shared
ScheduledEventQueue:
  egg        → gestating     (expiry: gestation period starts)
  gestating  → juvenile      (expiry: hatch)
  juvenile   → adult         (expiry: age threshold)
  adult      → elder         (expiry: age threshold, optional)
  *          → dying         (event: hp_zero — call enter_dying(sim))
  dying      → dead          (expiry: death timer) OR
                               (event: killing_blow — force finalize)
  dying      → prior_state   (event: healed above 0 — abort timer)

The dying window is the key feature: instead of instant death,
a creature lingers in the 'dying' state for a short timer window
during which it can be rescued (heal) or finished (additional
damage). Mourning subscribes to lifecycle.dying and lifecycle.dead
externally — nothing in this mixin knows mourning exists.

Scope for MVP:
  * FSM infrastructure, transitions, events, stat mods
  * Observation slots (self)
  * enter_dying(sim) available but not yet hooked into all death
    paths — combat / regen / movement still call die() directly.
    Migrating those is a follow-up.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.fsm import StateMachine


LIFECYCLE_STATES = ['egg', 'gestating', 'juvenile', 'adult', 'elder',
                    'dying', 'dead']
LIFECYCLE_STATE_IDX = {s: i for i, s in enumerate(LIFECYCLE_STATES)}

# Default dying-window duration. Can be overridden per-species or
# per-instance; the spec captures that this is the baseline.
DEFAULT_DYING_WINDOW_MS = 3000

# Per-species overrides for the dying window. Tanky species (bosses,
# large monsters) linger longer; frail species die faster.
SPECIES_DYING_WINDOW_MS: dict[str, int] = {
    # Populated as content expands. Defaults to DEFAULT_DYING_WINDOW_MS.
}

# Stat modifiers applied via the Stats.mods layer with source
# 'lifecycle_mods'. Keys are states; values are {Stat: delta}.
# juvenile / elder are the meaningful variants — adult is the
# zero baseline, egg / gestating / dying / dead don't modulate
# stats meaningfully (they block actions instead).
def _lifecycle_stat_deltas(state: str) -> list[tuple]:
    from classes.stats import Stat
    if state == 'juvenile':
        return [(Stat.STR, -4), (Stat.AGL, +2), (Stat.INT, -2)]
    if state == 'elder':
        return [(Stat.STR, -2), (Stat.AGL, -2), (Stat.INT, +3)]
    return []


class LifecycleMixin:
    """Age + life/death FSM on Creature.

    Lazy: FSM is built on first use via ``_ensure_lifecycle_fsm()``
    to keep Creature construction pickle-safe.
    """

    # ------------------------------------------------------------------
    # Initialization / accessors
    # ------------------------------------------------------------------
    @property
    def lifecycle_state(self) -> str:
        """Current lifecycle state name.

        Returns 'adult' as the default before the FSM is built. This
        matches the observation default so pre-FSM creatures behave
        like healthy adults from the NN's perspective.
        """
        fsm = getattr(self, '_lifecycle_fsm', None)
        return fsm.current if fsm is not None else 'adult'

    @property
    def lifecycle_fsm(self):
        return getattr(self, '_lifecycle_fsm', None)

    def _ensure_lifecycle_fsm(self, initial: str = 'adult'):
        """Build the FSM the first time lifecycle state is touched."""
        fsm = getattr(self, '_lifecycle_fsm', None)
        if fsm is not None:
            return fsm
        from classes.fsm import StateMachine, Transition
        self._lifecycle_fsm = StateMachine(
            owner=self,
            initial=initial,
            states=LIFECYCLE_STATES,
            transitions=[
                Transition('egg',       'gestate', 'gestating'),
                Transition('gestating', 'hatch',   'juvenile'),
                Transition('juvenile',  'mature',  'adult'),
                Transition('adult',     'age',     'elder'),
                # * → dying for any living creature that loses HP.
                Transition('juvenile',  'enter_dying', 'dying'),
                Transition('adult',     'enter_dying', 'dying'),
                Transition('elder',     'enter_dying', 'dying'),
                # Dying resolutions
                Transition('dying',     'healed',        'adult'),   # simplified: always → adult on recovery
                Transition('dying',     'death_confirmed','dead'),
                Transition('dying',     'killing_blow',  'dead'),
                # Wildcard death for non-dying states (e.g., egg destroyed)
                Transition('egg',       'death_confirmed', 'dead'),
                Transition('gestating', 'death_confirmed', 'dead'),
            ],
        )
        return self._lifecycle_fsm

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------
    def transition_lifecycle(self, trigger: str, sim=None) -> bool:
        """Generic trigger with event emission + stat-mod refresh.

        Returns True if a transition occurred. Emits
        'lifecycle.<new_state>' events on sim (if provided), with
        payload=(creature_uid, old_state, new_state).
        """
        fsm = self._ensure_lifecycle_fsm()
        old = fsm.current
        now = getattr(sim, 'now', 0) if sim is not None else 0
        ok = fsm.trigger(trigger, now=now)
        if not ok:
            return False
        new = fsm.current
        # Rebuild stat mods for the new state
        self._apply_lifecycle_stat_mods(new)
        # Emit a generic lifecycle event + a state-specific one so
        # subscribers can listen narrowly or broadly. Payload carries
        # (uid, old_state, new_state, creature_ref) — the ref lets
        # lifecycle.dead handlers find the creature even when
        # Creature.by_uid(uid) returns None (dying → dead transitions
        # have HP=0 so by_uid filters them out).
        if sim is not None:
            payload = (self.uid, old, new, self)
            for handler in sim._event_handlers.get(f'lifecycle.{new}', ()):
                try:
                    handler(payload)
                except Exception:
                    pass
            for handler in sim._event_handlers.get('lifecycle.any', ()):
                try:
                    handler(payload)
                except Exception:
                    pass
        return True

    def _apply_lifecycle_stat_mods(self, state: str) -> None:
        """Rebuild the lifecycle_mods layer for the current state."""
        self.stats.mods = [m for m in self.stats.mods
                            if m.get('source') != 'lifecycle_mods']
        for stat, amount in _lifecycle_stat_deltas(state):
            self.stats.mods.append({
                'stat': stat, 'amount': amount,
                'source': 'lifecycle_mods', 'stackable': False,
            })
        self.stats._mod_cache = None

    # ------------------------------------------------------------------
    # Dying window
    # ------------------------------------------------------------------
    def enter_dying(self, sim, window_ms: int | None = None,
                     from_killing_blow: bool = False) -> None:
        """Enter the dying state and schedule a death timer.

        If ``from_killing_blow`` is True, bypass the window and
        transition directly to dead. Used by melee_attack killing
        strikes so finishing blows are decisive.
        """
        fsm = self._ensure_lifecycle_fsm()
        if fsm.current == 'dead' or fsm.current == 'dying':
            # Already dying/dead — idempotent.
            return
        if from_killing_blow:
            # Skip the window entirely.
            self.transition_lifecycle('enter_dying', sim=sim)
            self.transition_lifecycle('killing_blow', sim=sim)
            return

        self.transition_lifecycle('enter_dying', sim=sim)

        # Determine window from species override or default.
        if window_ms is None:
            window_ms = SPECIES_DYING_WINDOW_MS.get(
                self.species, DEFAULT_DYING_WINDOW_MS)

        now = getattr(sim, 'now', 0) if sim is not None else 0
        if sim is not None:
            self._dying_ticket = sim.events.schedule(
                now + window_ms, 'lifecycle_death_expire', self.uid)

    def resolve_dying(self, sim, outcome: str) -> None:
        """Resolve a dying creature.

        outcome: 'heal' → back to adult (or previous living state);
                 'finish' → immediate death.
        """
        fsm = self._ensure_lifecycle_fsm()
        if fsm.current != 'dying':
            return
        if getattr(self, '_dying_ticket', None) is not None and sim is not None:
            sim.events.cancel(self._dying_ticket)
            self._dying_ticket = None
        if outcome == 'heal':
            self.transition_lifecycle('healed', sim=sim)
        elif outcome == 'finish':
            self.transition_lifecycle('killing_blow', sim=sim)
