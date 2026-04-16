"""Game-mode FSM — Phase 5 of FSM adoption.

Hierarchical two-level state machine tracking the player-facing
game mode. Top-level: main_menu → playing → quit. While in
``playing``, an overlay stack layers modal sub-states (paused,
inventory, dialogue, map_view, trade) with most-recently-pushed
on top.

This module ships the FSM + input-router infrastructure. The
one-pass refactor that replaces the boolean flags scattered
throughout src/main.py is a separate commit.

Constraints per Phase 5 design:
  * Max overlay stack depth ≈ 3 — push beyond that = silent ignore.
  * ``paused`` is a parallel flag, not on the stack — you can pause
    while inventory is open, then unpause into inventory.
  * Each sub-state declares ``freezes_sim`` so sim tick advancement
    queries one flag, not a big conditional.
  * Input routing is per-state via a keybind → action dict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TopState(Enum):
    MAIN_MENU = 'main_menu'
    PLAYING   = 'playing'
    QUIT      = 'quit'


class SubState(Enum):
    NORMAL    = 'normal'
    INVENTORY = 'inventory'
    DIALOGUE  = 'dialogue'
    MAP_VIEW  = 'map_view'
    TRADE     = 'trade'


# Which sub-states block sim tick advancement.
_FREEZES_SIM = {
    SubState.NORMAL:    False,
    SubState.INVENTORY: True,
    SubState.DIALOGUE:  True,
    SubState.MAP_VIEW:  False,
    SubState.TRADE:     True,
}

MAX_STACK_DEPTH = 3


@dataclass
class InputRouter:
    """Keybind → action mapping for one state.

    ``bindings`` is {pygame_key_code: action_name_string}. Higher-level
    code resolves action names into actual handler functions — keeps
    this module pygame-agnostic so it imports cleanly in tests.
    """
    bindings: dict = field(default_factory=dict)

    def handle(self, key_code: int) -> str | None:
        """Return the action name for a key, or None if unbound."""
        return self.bindings.get(key_code)


@dataclass
class GameModeFSM:
    """Two-level game mode FSM with push-down overlay stack.

    Fields:
      top:           current TopState
      overlay_stack: list of SubState, deepest first (e.g., on index 0).
                     The top of stack — index -1 — is the ACTIVE overlay.
                     Empty stack = normal gameplay.
      paused:        parallel boolean flag; not on the stack.
      routers:       dict[SubState, InputRouter] — per-state keybinds.
                     TopState keys (MAIN_MENU, QUIT) also accepted.
    """
    top: TopState = TopState.MAIN_MENU
    overlay_stack: list = field(default_factory=list)
    paused: bool = False
    routers: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Top-level transitions
    # ------------------------------------------------------------------
    def start_game(self) -> None:
        self.top = TopState.PLAYING
        self.overlay_stack.clear()
        self.paused = False

    def quit(self) -> None:
        self.top = TopState.QUIT
        self.overlay_stack.clear()

    def return_to_main_menu(self) -> None:
        self.top = TopState.MAIN_MENU
        self.overlay_stack.clear()
        self.paused = False

    # ------------------------------------------------------------------
    # Overlay stack (only meaningful while top == PLAYING)
    # ------------------------------------------------------------------
    @property
    def current_sub(self) -> SubState:
        return self.overlay_stack[-1] if self.overlay_stack else SubState.NORMAL

    def push(self, sub: SubState) -> bool:
        """Push an overlay. Returns False if stack is at MAX_STACK_DEPTH."""
        if self.top != TopState.PLAYING:
            return False
        if len(self.overlay_stack) >= MAX_STACK_DEPTH:
            return False
        self.overlay_stack.append(sub)
        return True

    def pop(self) -> SubState | None:
        """Pop the top overlay, returning it (or None if empty)."""
        if not self.overlay_stack:
            return None
        return self.overlay_stack.pop()

    def replace(self, sub: SubState) -> None:
        """Pop the current overlay (if any) and push a new one."""
        if self.overlay_stack:
            self.overlay_stack.pop()
        self.push(sub)

    # ------------------------------------------------------------------
    # Sim gating
    # ------------------------------------------------------------------
    def freezes_sim(self) -> bool:
        """True if the sim tick should be suspended this frame.

        Main menu + quit freeze (no sim exists); playing checks pause +
        the current sub-state's freezes_sim flag.
        """
        if self.top != TopState.PLAYING:
            return True
        if self.paused:
            return True
        return _FREEZES_SIM.get(self.current_sub, False)

    # ------------------------------------------------------------------
    # Input routing
    # ------------------------------------------------------------------
    def handle_key(self, key_code: int) -> str | None:
        """Dispatch a key event to the current state's router.

        Returns the action name (or None). Caller dispatches the
        action — the router doesn't know about the handler world.
        """
        key = self.current_sub if self.top == TopState.PLAYING else self.top
        router = self.routers.get(key)
        if router is None:
            return None
        return router.handle(key_code)
