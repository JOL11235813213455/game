"""Combat arousal FSM mixin — Phase 7 of FSM adoption.

Five-state FSM tracking a creature's psychophysiological state
around combat:

  calm ──hostile_seen──► alert ──damage/attack──► engaged
   ▲                       │                          │
   │               no-threat│                 no-combat│
   │                      timer                     timer
   │                        ▼                          ▼
   └── timeout ── recovering ◄── cooling_down ◄────────┘
                     ▲                │
                     │    timer       │
                     └────────────────┘

State modulates:
  * stats via the ``arousal_mods`` layer (narrow focus: AGL/PER/INT;
    STR/VIT stay equipment-driven per the revised Q7.2 decision)
  * action availability via the compute_dynamic_mask hook (Q7.8)
  * fatigue/hunger/regen rates read arousal_state at their tick

Event-driven triggers:
  * calm → alert:     perception.hostile_seen (event from perception)
  * alert → engaged:  damage.dealt / damage.taken / attack.initiated
  * alert → calm:     expiry timer (no new threat for N sec)
  * engaged → cooling_down: expiry timer (no combat events for N sec)
  * cooling_down → recovering: expiry timer
  * recovering → calm: expiry timer

All expiry events fire through the shared ScheduledEventQueue.
"ur"
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


AROUSAL_STATES = ['calm', 'alert', 'engaged', 'cooling_down', 'recovering']
AROUSAL_STATE_IDX = {s: i for i, s in enumerate(AROUSAL_STATES)}

# Timeout windows for expiry-driven state decays (ms).
AROUSAL_TIMEOUTS = {
    'alert_to_calm':             10_000,   # 10s quiet → calm
    'engaged_to_cooling':         5_000,   # 5s no combat → cooling_down
    'cooling_to_recovering':     30_000,   # 30s → recovering
    'recovering_to_calm':       120_000,   # 2m → calm
}


def _arousal_stat_deltas(state: str) -> list[tuple]:
    """Stat modifiers per arousal state — narrow focus per Q7.2."""
    from classes.stats import Stat
    if state == 'alert':
        return [(Stat.PER, +2)]
    if state == 'engaged':
        return [(Stat.AGL, +1), (Stat.PER, -1), (Stat.INT, -1)]
    if state == 'cooling_down':
        return [(Stat.AGL, -1), (Stat.STR, -1)]
    if state == 'recovering':
        return [(Stat.INT, +1)]
    # calm → baseline (no mods)
    return []


# Action gating by arousal state (Q7.8). Each key is an Action enum
# member; the value is the set of arousal states in which that action
# is permitted. Actions not listed are permitted in all states
# (backwards-compat default).
def _build_action_gates():
    """Return {Action: frozenset(state_names)} from the Action enum.

    Built lazily because Action imports pull the dispatcher.
    """
    from classes.actions import Action
    calm_only  = frozenset({'calm'})
    calm_rec   = frozenset({'calm', 'recovering'})
    safe_set   = frozenset({'calm', 'cooling_down', 'recovering'})
    non_engaged = frozenset({'calm', 'alert', 'cooling_down', 'recovering'})
    alert_eng  = frozenset({'alert', 'engaged'})

    gates: dict = {}
    # Calm-only: mating is deliberate + vulnerable (Q7.8 headline rule)
    if hasattr(Action, 'PAIR'):
        gates[Action.PAIR] = calm_only
    # Calm-only: inviting to your crew isn't something you do mid-combat.
    if hasattr(Action, 'INVITE_TO_PARTY'):
        gates[Action.INVITE_TO_PARTY] = calm_only
    # Calm + recovering: deliberative actions
    for name in ('CRAFT', 'TRADE', 'SLEEP', 'PRAY'):
        if hasattr(Action, name):
            gates[getattr(Action, name)] = calm_rec
    # Calm / cooling_down / recovering: eat (crashing animals eat
    # ravenously; engaged tunnel-vision blocks it)
    if hasattr(Action, 'EAT'):
        gates[Action.EAT] = safe_set
    # All non-engaged: healing (emergency medic still blocked by
    # engaged tunnel vision)
    for name in ('HEAL_SELF', 'HEAL_OTHER'):
        if hasattr(Action, name):
            gates[getattr(Action, name)] = non_engaged
    # alert + engaged only: combat spells require focus mode
    if hasattr(Action, 'CAST_COMBAT_SPELL'):
        gates[Action.CAST_COMBAT_SPELL] = alert_eng
    return gates


_ACTION_GATES_CACHE: dict | None = None


def get_action_gates():
    global _ACTION_GATES_CACHE
    if _ACTION_GATES_CACHE is None:
        _ACTION_GATES_CACHE = _build_action_gates()
    return _ACTION_GATES_CACHE


class ArousalMixin:
    """Combat arousal FSM + stat/action modulation."""

    # ------------------------------------------------------------------
    # FSM lifecycle
    # ------------------------------------------------------------------
    @property
    def arousal_state(self) -> str:
        fsm = getattr(self, '_arousal_fsm', None)
        return fsm.current if fsm is not None else 'calm'

    def _ensure_arousal_fsm(self):
        fsm = getattr(self, '_arousal_fsm', None)
        if fsm is not None:
            return fsm
        from classes.fsm import StateMachine, Transition
        self._arousal_fsm = StateMachine(
            owner=self, initial='calm',
            states=AROUSAL_STATES,
            transitions=[
                Transition('calm',          'hostile_seen', 'alert'),
                Transition('alert',         'combat',       'engaged'),
                Transition('alert',         'quiet_timeout','calm'),
                Transition('engaged',       'combat',       'engaged'),   # self-loop (reset timer)
                Transition('engaged',       'no_combat_timeout', 'cooling_down'),
                Transition('cooling_down',  'cool_timeout', 'recovering'),
                Transition('cooling_down',  'combat',       'engaged'),
                Transition('recovering',    'recover_timeout','calm'),
                Transition('recovering',    'combat',       'engaged'),
                # Emergency re-escalation from any lower state
                Transition('calm',          'combat',       'engaged'),
            ],
        )
        return self._arousal_fsm

    def _arousal_apply_stat_mods(self, state: str) -> None:
        self.stats.mods = [m for m in self.stats.mods
                            if m.get('source') != 'arousal_mods']
        for stat, amount in _arousal_stat_deltas(state):
            self.stats.mods.append({
                'stat': stat, 'amount': amount,
                'source': 'arousal_mods', 'stackable': False,
            })
        self.stats._mod_cache = None

    def _arousal_transition(self, sim, trigger: str) -> bool:
        """Trigger a transition + refresh mods + reschedule timers."""
        fsm = self._ensure_arousal_fsm()
        old = fsm.current
        now = getattr(sim, 'now', 0) if sim is not None else 0
        if not fsm.trigger(trigger, now=now):
            return False
        new = fsm.current
        self._arousal_apply_stat_mods(new)
        # Cancel any outstanding arousal timer — new state may have
        # its own timer or none at all
        if getattr(self, '_arousal_ticket', None) is not None and sim is not None:
            sim.events.cancel(self._arousal_ticket)
            self._arousal_ticket = None
        # Schedule the next auto-transition if this state decays
        if sim is not None:
            next_timer = {
                'alert':         ('quiet_timeout',   AROUSAL_TIMEOUTS['alert_to_calm']),
                'engaged':       ('no_combat_timeout', AROUSAL_TIMEOUTS['engaged_to_cooling']),
                'cooling_down':  ('cool_timeout',    AROUSAL_TIMEOUTS['cooling_to_recovering']),
                'recovering':    ('recover_timeout', AROUSAL_TIMEOUTS['recovering_to_calm']),
            }.get(new)
            if next_timer is not None:
                self._arousal_ticket = sim.events.schedule(
                    now + next_timer[1], 'arousal_timer',
                    (self.uid, next_timer[0]))
        return True

    # ------------------------------------------------------------------
    # Public triggers — to be called from perception / combat code.
    # ------------------------------------------------------------------
    def arousal_on_hostile_seen(self, sim) -> None:
        """Perception noticed a hostile — wake up to alert."""
        self._arousal_transition(sim, 'hostile_seen')

    def arousal_on_combat(self, sim) -> None:
        """Damage dealt/taken or attack initiated — engaged."""
        self._arousal_transition(sim, 'combat')

    # ------------------------------------------------------------------
    # Sim handler (dispatched from 'arousal_timer' event drain)
    # ------------------------------------------------------------------
    def on_arousal_timer(self, sim, trigger: str) -> None:
        """Timer expiry — fire the given trigger if still relevant."""
        self._ensure_arousal_fsm()
        # Just attempt the trigger — StateMachine silently no-ops if
        # the creature has since moved to a different state.
        self._arousal_transition(sim, trigger)

    # ------------------------------------------------------------------
    # Action-gating hook — read by actions.compute_dynamic_mask
    # ------------------------------------------------------------------
    def arousal_action_allowed(self, action) -> bool:
        """Return True if the action is allowed in the current arousal state.

        Actions absent from the gate table are allowed in all states
        (backwards-compat default). Currently-calm creatures behave
        identically to pre-Phase-7 creatures.
        """
        gates = get_action_gates()
        allowed = gates.get(action)
        if allowed is None:
            return True
        return self.arousal_state in allowed
