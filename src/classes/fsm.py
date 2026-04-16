"""Finite State Machine foundation + scheduled event queue.

Shared infrastructure for the FSM adoption plan (status effects,
lifecycle, pack states, weather, arousal). Two classes:

  * StateMachine: generic string-keyed state machine with guarded
    transitions, entry/exit hooks, event-driven triggers. Picklable
    (state is plain strings + ints). Owner-pattern: never extends
    Trackable; the owning game object (Creature, Pack, Simulation)
    saves via its own pickle and calls ``_resubscribe_events`` on
    load to rebuild any external hooks.

  * ScheduledEventQueue: min-heap of (expiry_tick, ticket, tag,
    payload). Owners schedule expiries via ``schedule(...)`` and
    drain fired events from the sim tick loop via ``drain(now)``.
    Cancellation by ticket id. Pure Python; upgrade to Cython only
    if profiling demands.

Neither class is a Trackable — they live inside their owner.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Transition:
    """One edge in a StateMachine's graph.

    ``guard`` is an optional zero-arg callable returning bool. If
    present and returns False, the transition is skipped silently
    and the machine stays in its current state.

    ``effect`` is an optional zero-arg callable run on successful
    transition, after ``on_exit(from_state)`` and before
    ``on_enter(to_state)``.
    """
    from_state: str
    trigger: str
    to_state: str
    guard: Callable[[], bool] | None = None
    effect: Callable[[], None] | None = None


class StateMachine:
    """Generic string-keyed FSM.

    Usage::

        sm = StateMachine(
            owner=creature,
            initial='normal',
            states=['normal', 'stunned', 'sleeping', 'dead'],
            transitions=[
                Transition('normal', 'stun', 'stunned'),
                Transition('stunned', 'stun_expired', 'normal'),
                Transition('*', 'hp_zero', 'dead'),  # wildcard from
            ],
            on_enter={'dead': lambda: creature._on_death()},
        )

        sm.trigger('stun')          # event-driven transition
        sm.current                   # -> 'stunned'
        sm.time_in_state(now_tick)   # ms since last entry

    Wildcard ``'*'`` in ``from_state`` means "from any state" —
    useful for universal transitions like "hp_zero → dead".

    State is picklable (plain strings + ints). External event
    subscriptions (if any) are the owner's responsibility to
    rebuild after load.
    """

    def __init__(self, owner, initial: str, states: list[str],
                 transitions: list[Transition],
                 on_enter: dict[str, Callable[[], None]] | None = None,
                 on_exit: dict[str, Callable[[], None]] | None = None):
        if initial not in states:
            raise ValueError(f'initial state {initial!r} not in states {states!r}')
        self.owner = owner
        self._states = set(states)
        self._transitions: dict[tuple[str, str], Transition] = {}
        self._wild_transitions: dict[str, Transition] = {}
        for t in transitions:
            if t.to_state not in self._states:
                raise ValueError(f'to_state {t.to_state!r} not in states')
            if t.from_state == '*':
                self._wild_transitions[t.trigger] = t
            else:
                if t.from_state not in self._states:
                    raise ValueError(f'from_state {t.from_state!r} not in states')
                self._transitions[(t.from_state, t.trigger)] = t
        self._on_enter = on_enter or {}
        self._on_exit = on_exit or {}
        self._current = initial
        self._entered_at = 0
        self._prev: str | None = None

    @property
    def current(self) -> str:
        return self._current

    @property
    def previous(self) -> str | None:
        return self._prev

    def time_in_state(self, now: int) -> int:
        """Milliseconds elapsed since the current state was entered."""
        return max(0, now - self._entered_at)

    def trigger(self, event: str, now: int = 0) -> bool:
        """Fire an event. Returns True if a transition occurred.

        Lookup order: (current_state, event) → wildcard[event] →
        no match (silent false). Guard is evaluated after lookup;
        a failing guard still counts as "no transition" (false).
        """
        t = self._transitions.get((self._current, event))
        if t is None:
            t = self._wild_transitions.get(event)
        if t is None:
            return False
        if t.guard is not None and not t.guard():
            return False
        self._perform(t, now)
        return True

    def force(self, to_state: str, now: int = 0) -> None:
        """Hard-set the state without a transition lookup.

        Use sparingly — e.g., save/load restoration or admin.
        Runs exit/enter hooks but skips guards and effects.
        """
        if to_state not in self._states:
            raise ValueError(f'unknown state {to_state!r}')
        if to_state == self._current:
            return
        self._exit_current()
        self._prev = self._current
        self._current = to_state
        self._entered_at = now
        self._enter_current()

    def _perform(self, t: Transition, now: int) -> None:
        self._exit_current()
        if t.effect is not None:
            t.effect()
        self._prev = self._current
        self._current = t.to_state
        self._entered_at = now
        self._enter_current()

    def _exit_current(self) -> None:
        fn = self._on_exit.get(self._current)
        if fn is not None:
            fn()

    def _enter_current(self) -> None:
        fn = self._on_enter.get(self._current)
        if fn is not None:
            fn()

    # ------------------------------------------------------------------
    # Pickle support
    # ------------------------------------------------------------------
    def __getstate__(self) -> dict:
        # Drop transitions/hooks — those reference callables/closures
        # tied to the owner. The owner is responsible for rebuilding
        # this StateMachine's graph in __setstate__ / post-load and
        # calling ``restore_state(current, entered_at)`` to pin the
        # saved state back in.
        return {
            'current': self._current,
            'entered_at': self._entered_at,
            'prev': self._prev,
        }

    def __setstate__(self, state: dict) -> None:
        # Partial restore: just the dynamic fields. Owner must call
        # rebuild() or construct a fresh graph and then restore_state().
        self._current = state['current']
        self._entered_at = state['entered_at']
        self._prev = state.get('prev')
        self._states = set()
        self._transitions = {}
        self._wild_transitions = {}
        self._on_enter = {}
        self._on_exit = {}
        self.owner = None

    def restore_state(self, current: str, entered_at: int,
                       prev: str | None = None) -> None:
        """Pin a saved state back in after owner rebuilds the graph."""
        if current not in self._states:
            raise ValueError(f'unknown state {current!r} during restore')
        self._current = current
        self._entered_at = entered_at
        self._prev = prev


@dataclass(order=True)
class _ScheduledItem:
    expiry: int
    ticket: int
    tag: str = field(compare=False)
    payload: Any = field(compare=False)


class ScheduledEventQueue:
    """Min-heap scheduler for expiry-driven events.

    Owners (typically the Simulation) call ``schedule(expiry_tick,
    tag, payload)`` to register an event. Each tick the sim calls
    ``drain(now)`` which pops every item whose expiry <= now and
    returns them as (tag, payload) pairs. Cancelled tickets are
    silently dropped during drain.

    Not thread-safe. Pickle-friendly: heap is a list of picklable
    items.
    """

    def __init__(self):
        self._heap: list[_ScheduledItem] = []
        self._cancelled: set[int] = set()
        self._next_id: int = 0

    def __len__(self) -> int:
        return len(self._heap)

    def schedule(self, expiry_tick: int, tag: str,
                  payload: Any = None) -> int:
        """Schedule an event to fire at or after ``expiry_tick``.

        Returns a ticket id usable with ``cancel()``.
        """
        ticket = self._next_id
        self._next_id += 1
        heapq.heappush(
            self._heap,
            _ScheduledItem(expiry=int(expiry_tick), ticket=ticket,
                            tag=tag, payload=payload),
        )
        return ticket

    def cancel(self, ticket: int) -> None:
        """Mark a ticket as cancelled. No-op if already fired."""
        self._cancelled.add(ticket)

    def drain(self, now: int) -> list[tuple[str, Any]]:
        """Pop every event whose expiry <= now. Caller dispatches."""
        fired: list[tuple[str, Any]] = []
        while self._heap and self._heap[0].expiry <= now:
            item = heapq.heappop(self._heap)
            if item.ticket in self._cancelled:
                self._cancelled.discard(item.ticket)
                continue
            fired.append((item.tag, item.payload))
        return fired

    def peek_next_expiry(self) -> int | None:
        """When does the next non-cancelled event fire? (None if empty.)

        Skips cancelled items at the head but does not pop them.
        """
        while self._heap and self._heap[0].ticket in self._cancelled:
            item = heapq.heappop(self._heap)
            self._cancelled.discard(item.ticket)
        return self._heap[0].expiry if self._heap else None

    def clear(self) -> None:
        self._heap.clear()
        self._cancelled.clear()
