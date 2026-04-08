"""
Action space for the creature RL system.

Each action is an enum value that maps to a creature method call.
The dispatcher takes a creature, action index, and context, then
executes the action and returns an outcome dict.
"""
from __future__ import annotations
from enum import IntEnum


class Action(IntEnum):
    # Movement (0-7: 8 directions)
    MOVE_N  = 0
    MOVE_NE = 1
    MOVE_E  = 2
    MOVE_SE = 3
    MOVE_S  = 4
    MOVE_SW = 5
    MOVE_W  = 6
    MOVE_NW = 7

    # Movement variants
    RUN_N   = 8
    RUN_NE  = 9
    RUN_E   = 10
    RUN_SE  = 11
    RUN_S   = 12
    RUN_SW  = 13
    RUN_W   = 14
    RUN_NW  = 15

    SNEAK_N  = 16
    SNEAK_NE = 17
    SNEAK_E  = 18
    SNEAK_SE = 19
    SNEAK_S  = 20
    SNEAK_SW = 21
    SNEAK_W  = 22
    SNEAK_NW = 23

    # Combat
    MELEE_ATTACK = 24
    RANGED_ATTACK = 25
    GRAPPLE = 26
    CAST_SPELL = 27

    # Social
    INTIMIDATE = 28
    DECEIVE = 29
    TRADE = 30
    BRIBE = 31
    STEAL = 32
    SHARE_RUMOR = 33
    TALK = 34

    # Utility
    PICKUP = 35
    DROP = 36
    USE_ITEM = 37
    WAIT = 38
    GUARD = 39
    SEARCH = 40
    FLEE = 41
    FOLLOW = 42
    CALL_BACKUP = 43
    SLEEP = 44
    SET_TRAP = 45

    # Stances
    BLOCK_STANCE = 46
    EXIT_BLOCK = 47
    EXIT_GUARD = 48


NUM_ACTIONS = len(Action)

# Action → god-tracking name
ACTION_NAMES = {
    Action.MELEE_ATTACK: 'melee_attack', Action.RANGED_ATTACK: 'ranged_attack',
    Action.GRAPPLE: 'grapple', Action.CAST_SPELL: 'cast_spell',
    Action.INTIMIDATE: 'intimidate', Action.DECEIVE: 'deceive',
    Action.TRADE: 'trade', Action.BRIBE: 'bribe',
    Action.STEAL: 'steal', Action.SHARE_RUMOR: 'share_rumor',
    Action.TALK: 'talk', Action.PICKUP: 'pickup', Action.DROP: 'drop',
    Action.USE_ITEM: 'use_item', Action.WAIT: 'wait',
    Action.GUARD: 'guard', Action.SEARCH: 'search',
    Action.FLEE: 'flee', Action.FOLLOW: 'follow',
    Action.CALL_BACKUP: 'call_backup', Action.SLEEP: 'sleep',
    Action.SET_TRAP: 'set_trap', Action.BLOCK_STANCE: 'block_stance',
}


def _record_god_action(action: int):
    """Record an action in the WorldData god counters (if WorldData exists)."""
    action_name = ACTION_NAMES.get(action)
    if action_name is None:
        return
    try:
        from classes.gods import WorldData
        from classes.trackable import Trackable
        for obj in Trackable.all_instances():
            if isinstance(obj, WorldData):
                obj.record_action(action_name)
                break
    except Exception:
        pass


# Direction vectors for movement actions
_DIRS = {
    0: (0, -1),   # N
    1: (1, -1),   # NE
    2: (1, 0),    # E
    3: (1, 1),    # SE
    4: (0, 1),    # S
    5: (-1, 1),   # SW
    6: (-1, 0),   # W
    7: (-1, -1),  # NW
}


def dispatch(creature, action: int, context: dict) -> dict:
    """Execute an action for a creature. Records action in god counters."""
    result = _dispatch_inner(creature, action, context)
    # Record in god system
    if result.get('success', result.get('hit', False)):
        _record_god_action(action)
    return result


def _dispatch_inner(creature, action: int, context: dict) -> dict:
    """Inner dispatch — actual action execution.

    Args:
        creature: the Creature performing the action
        action: Action enum value (int)
        context: dict with keys depending on action:
            cols, rows: map dimensions (required for movement)
            target: target Creature (for combat/social)
            item: target Item (for pickup/drop/use/steal/trap)
            items: list of Items (for trade/bribe)
            requested: list of Items (for trade)
            now: current timestamp (for combat/sleep)

    Returns:
        dict with 'success' (bool) and action-specific keys
    """
    cols = context.get('cols', 0)
    rows = context.get('rows', 0)
    target = context.get('target')
    item = context.get('item')
    now = context.get('now', 0)

    # -- Movement --
    if 0 <= action <= 7:
        dx, dy = _DIRS[action]
        old = creature.location
        creature.move(dx, dy, cols, rows)
        return {'success': creature.location != old}

    if 8 <= action <= 15:
        dx, dy = _DIRS[action - 8]
        return {'success': creature.run(dx, dy, cols, rows)}

    if 16 <= action <= 23:
        dx, dy = _DIRS[action - 16]
        return {'success': creature.sneak(dx, dy, cols, rows)}

    # -- Combat --
    if action == Action.MELEE_ATTACK:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        return creature.melee_attack(target, now)

    if action == Action.RANGED_ATTACK:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        return creature.ranged_attack(target, now)

    if action == Action.GRAPPLE:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        return creature.grapple(target)

    if action == Action.CAST_SPELL:
        spell = context.get('spell')
        if spell is None:
            # Auto-select first known spell
            from data.db import SPELLS
            known = creature.get_known_spells()
            for sk in known:
                if sk in SPELLS:
                    spell = SPELLS[sk]
                    break
            if spell is None:
                return {'success': False, 'reason': 'no_spell'}
        return creature.cast_spell(spell, target, now)

    # -- Social --
    if action == Action.INTIMIDATE:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        return creature.intimidate(target)

    if action == Action.DECEIVE:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        return creature.deceive(target)

    if action == Action.TRADE:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        offered = context.get('items', [])
        requested = context.get('requested', [])
        return creature.propose_trade(target, offered, requested)

    if action == Action.BRIBE:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        items = context.get('items', [])
        return creature.bribe(target, items)

    if action == Action.STEAL:
        if target is None or item is None:
            return {'success': False, 'reason': 'no_target'}
        return creature.steal(target, item)

    if action == Action.SHARE_RUMOR:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        subject_uid = context.get('subject_uid', 0)
        sentiment = context.get('sentiment', 0.0)
        tick = context.get('tick', now)
        return {'success': creature.share_rumor(target, subject_uid, sentiment, tick)}

    if action == Action.TALK:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        conv = context.get('conversation')
        roots = creature.start_conversation(target, conv)
        return {'success': len(roots) > 0, 'roots': roots}

    # -- Utility --
    if action == Action.PICKUP:
        if item is None:
            # Auto-pickup: grab first item on tile
            tile = creature.current_map.tiles.get(creature.location)
            if tile and tile.inventory.items:
                item = tile.inventory.items[0]
            else:
                return {'success': False, 'reason': 'nothing_here'}
        return {'success': creature.pickup(item)}

    if action == Action.DROP:
        if item is None:
            if creature.inventory.items:
                item = creature.inventory.items[0]
            else:
                return {'success': False, 'reason': 'nothing_to_drop'}
        return {'success': creature.drop(item)}

    if action == Action.USE_ITEM:
        if item is None:
            # Use first consumable
            from classes.inventory import Consumable
            for inv_item in creature.inventory.items:
                if isinstance(inv_item, Consumable):
                    item = inv_item
                    break
            if item is None:
                return {'success': False, 'reason': 'no_consumable'}
        return {'success': creature.use_item(item)}

    if action == Action.WAIT:
        return {'success': creature.wait()}

    if action == Action.GUARD:
        return {'success': creature.guard(cols, rows)}

    if action == Action.SEARCH:
        return creature.search_tile()

    if action == Action.FLEE:
        if target is None:
            return {'success': False, 'reason': 'no_threat'}
        return {'success': creature.flee(target, cols, rows)}

    if action == Action.FOLLOW:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        return {'success': creature.follow(target, cols, rows)}

    if action == Action.CALL_BACKUP:
        responders = creature.call_backup()
        return {'success': len(responders) > 0, 'responders': responders}

    if action == Action.SLEEP:
        return {'success': creature.sleep(now)}

    if action == Action.SET_TRAP:
        if item is None:
            return {'success': False, 'reason': 'no_trap_item'}
        dc = context.get('trap_dc', 10)
        return {'success': creature.set_trap(item, dc)}

    # -- Stances --
    if action == Action.BLOCK_STANCE:
        return {'success': creature.enter_block_stance()}

    if action == Action.EXIT_BLOCK:
        creature.exit_block_stance()
        return {'success': True}

    if action == Action.EXIT_GUARD:
        creature.stop_guard()
        return {'success': True}

    return {'success': False, 'reason': 'unknown_action'}
