"""Status effect / condition management mixin for Creature.

Owns:
  * ``self.conditions``: dict of active Condition instances (parallel FSMs)
  * ``self.action_state``: compound StateMachine (normal/stunned/sleeping/dead)
  * apply_condition / remove_condition / has_condition API
  * condition_tick / condition_expired handlers (called from sim events)

The sim schedules per-condition expiry and (for DoTs) periodic tick
events. When those fire, sim dispatch routes them back here via UID
lookup.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from classes.conditions import Condition, ConditionSpec


# Mapping from condition name → action_state it forces.
_ACTION_STATE_FOR = {
    'stunned':  'stunned',
    'sleeping': 'sleeping',
}


class ConditionsMixin:
    """Status effect condition management."""

    # ------------------------------------------------------------------
    # action_state FSM (compound: normal/stunned/sleeping/dead)
    # ------------------------------------------------------------------
    def _ensure_action_state(self):
        """Lazily build the compound action-state FSM.

        Built on first use rather than in __init__ so constructing a
        creature stays pickle-safe (StateMachine holds closures bound
        to the creature, which are owner-specific).
        """
        if self.action_state is not None:
            return
        from classes.fsm import StateMachine, Transition
        self.action_state = StateMachine(
            owner=self,
            initial='normal',
            states=['normal', 'stunned', 'sleeping', 'dead'],
            transitions=[
                # Condition-driven transitions
                Transition('normal',   'stun',     'stunned'),
                Transition('stunned',  'unstun',   'normal'),
                Transition('normal',   'sleep',    'sleeping'),
                Transition('sleeping', 'wake',     'normal'),
                # Sleep is dispelled by damage (handled via apply_damage hook)
                Transition('sleeping', 'damaged',  'normal'),
                # Death is universal (wildcard from_state)
                Transition('*',        'died',     'dead'),
            ],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def has_condition(self, name: str) -> bool:
        return name in self.conditions

    def get_condition(self, name: str):
        return self.conditions.get(name)

    def can_act(self) -> bool:
        """True if the action_state FSM currently permits action selection."""
        self._ensure_action_state()
        return self.action_state.current == 'normal'

    def apply_condition(self, sim, name: str,
                         severity: int = 1,
                         applied_by_uid: int | None = None,
                         duration_ms: int | None = None,
                         skip_resist: bool = False) -> bool:
        """Apply a condition to this creature.

        Returns True on successful application, False on resistance.

        Stacking (Q1.4): if the condition is already active, refresh
        duration to ``max(remaining, new)`` and take max severity. No
        additive stacking.

        Resistance (Q1.5): unless ``skip_resist`` is set, a d20 contest
        fires via conditions.resist_condition(); buffs auto-apply.
        """
        from classes.conditions import (CONDITION_SPECS, Condition,
                                         _stat_mods_for, resist_condition)

        # Curriculum gate: early stages disable conditions entirely.
        # Checked first so resistance rolls aren't wasted on no-ops.
        if not getattr(sim, 'conditions_enabled', True):
            return False

        spec = CONDITION_SPECS.get(name)
        if spec is None:
            return False

        # Resistance contest (skipped for self-cast buffs etc.)
        if not skip_resist:
            from classes.creature import Creature as _C
            source = _C.by_uid(applied_by_uid) if applied_by_uid else None
            if resist_condition(self, source, spec, severity):
                return False

        severity = max(1, min(spec.max_severity, severity))
        duration = duration_ms if duration_ms is not None else spec.default_duration_ms
        now = getattr(sim, 'now', 0)
        expires_at = now + duration

        # Stacking: refresh + take max severity
        existing = self.conditions.get(name)
        if existing is not None:
            new_severity = max(existing.severity, severity)
            new_expires = max(existing.expires_at, expires_at)
            # Stat mods: rebuild if severity changed
            if new_severity != existing.severity:
                self._remove_condition_stat_mods(name)
                existing.severity = new_severity
                self._add_condition_stat_mods(name, new_severity)
            existing.expires_at = new_expires
            # Reschedule expiry — cancel old ticket, schedule new one
            if existing.expire_ticket is not None:
                sim.events.cancel(existing.expire_ticket)
            existing.expire_ticket = sim.events.schedule(
                new_expires, 'condition_expired', (self.uid, name))
            return True

        # Fresh application
        cond = Condition(
            name=name, severity=severity,
            applied_by_uid=applied_by_uid,
            applied_at_tick=now, expires_at=expires_at,
        )
        self.conditions[name] = cond

        # Stat modifiers via Stats.mods layer
        self._add_condition_stat_mods(name, severity)

        # Action-state gating (stun/sleep)
        action_state = _ACTION_STATE_FOR.get(name)
        if action_state is not None:
            self._ensure_action_state()
            trigger = 'stun' if action_state == 'stunned' else 'sleep'
            self.action_state.trigger(trigger, now=now)

        # Schedule expiry
        cond.expire_ticket = sim.events.schedule(
            expires_at, 'condition_expired', (self.uid, name))

        # Schedule first periodic tick if this condition ticks
        if spec.tick_interval_ms is not None:
            first_tick = now + spec.tick_interval_ms
            cond.tick_ticket = sim.events.schedule(
                first_tick, 'condition_tick', (self.uid, name))

        return True

    def remove_condition(self, sim, name: str) -> bool:
        """Remove a condition and clean up any scheduled events.

        Returns True if the condition was present. Callers wanting
        the "expire naturally" path should let sim.events drain;
        this method is for cures / damage-wakes / instant removals.
        """
        cond = self.conditions.pop(name, None)
        if cond is None:
            return False
        if cond.expire_ticket is not None:
            sim.events.cancel(cond.expire_ticket)
        if cond.tick_ticket is not None:
            sim.events.cancel(cond.tick_ticket)
        self._remove_condition_stat_mods(name)

        # Undo action-state gating
        action_state = _ACTION_STATE_FOR.get(name)
        if action_state is not None and self.action_state is not None:
            now = getattr(sim, 'now', 0)
            if action_state == 'stunned':
                self.action_state.trigger('unstun', now=now)
            elif action_state == 'sleeping':
                self.action_state.trigger('wake', now=now)
        return True

    # ------------------------------------------------------------------
    # Stat mod helpers
    # ------------------------------------------------------------------
    def _add_condition_stat_mods(self, name: str, severity: int) -> None:
        from classes.conditions import _stat_mods_for
        mods = _stat_mods_for(name, severity)
        if not mods:
            return
        src = f'condition:{name}'
        for stat, amount in mods:
            self.stats.mods.append({
                'stat': stat, 'amount': amount, 'source': src,
                'stackable': False,
            })
        self.stats._mod_cache = None

    def _remove_condition_stat_mods(self, name: str) -> None:
        src = f'condition:{name}'
        self.stats.mods = [m for m in self.stats.mods if m.get('source') != src]
        self.stats._mod_cache = None

    # ------------------------------------------------------------------
    # Handlers called from Simulation event dispatch
    # ------------------------------------------------------------------
    def on_condition_tick(self, sim, name: str) -> None:
        """One periodic tick of a DoT/HoT condition.

        Applies damage_for_tick (positive = damage, negative = heal),
        routes kill credit via applied_by_uid, and reschedules the
        next tick unless the condition has expired.
        """
        from classes.conditions import CONDITION_SPECS, damage_for_tick
        from classes.stats import Stat
        cond = self.conditions.get(name)
        if cond is None or not self.is_alive:
            return
        delta = damage_for_tick(cond)
        if delta != 0:
            if delta > 0:
                # Damage path routes through apply_damage for blame tracking
                attacker_uid = cond.applied_by_uid
                from classes.creature import Creature as _C
                attacker = _C.by_uid(attacker_uid) if attacker_uid else None
                if hasattr(self, 'apply_damage'):
                    self.apply_damage(delta, attacker=attacker,
                                       damage_type=f'condition:{name}')
                else:
                    self.stats.base[Stat.HP_CURR] -= delta
                # Phase 2: if the DoT lethal, route through the dying
                # window so mourning fires + allies can heal in time.
                # Guarded by lifecycle_state presence — only FSM-enabled
                # creatures take this path.
                if (self.stats.base.get(Stat.HP_CURR, 0) <= 0
                        and hasattr(self, 'enter_dying')
                        and self.lifecycle_state not in ('dying', 'dead')):
                    self.remove_condition(sim, name)   # stop further ticks
                    self.enter_dying(sim)
                    return
                # Special clearing: bleeding stops when HP fully restored
                # (paralleled by the natural expiry).
                if name == 'bleeding':
                    hp_cur = self.stats.active[Stat.HP_CURR]()
                    hp_max = max(1, self.stats.active[Stat.HP_MAX]())
                    if hp_cur >= hp_max:
                        self.remove_condition(sim, 'bleeding')
                        return
            else:
                hp_cur = self.stats.active[Stat.HP_CURR]()
                hp_max = self.stats.active[Stat.HP_MAX]()
                self.stats.base[Stat.HP_CURR] = min(hp_max, hp_cur - delta)

        # Reschedule next tick if still active and hasn't expired.
        spec = CONDITION_SPECS[name]
        if spec.tick_interval_ms is not None:
            next_tick = sim.now + spec.tick_interval_ms
            if next_tick < cond.expires_at:
                cond.tick_ticket = sim.events.schedule(
                    next_tick, 'condition_tick', (self.uid, name))
            else:
                cond.tick_ticket = None

    def on_condition_expired(self, sim, name: str) -> None:
        """Called when a condition's expiry fires. Just clears it."""
        if name in self.conditions:
            self.remove_condition(sim, name)
