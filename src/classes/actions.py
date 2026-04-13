"""
Action space for the creature RL system.

Each action is an enum value that maps to a creature method call.
The dispatcher takes a creature, action index, and context, then
executes the action and returns an outcome dict.

Movement uses 8 directional MOVE actions. The locomotion mode
(walk/run/sneak) is determined as:
  - Sneak: if creature.movement_mode == 'sneak' (toggled by SET_SNEAK)
  - Run:   auto-selected when a hostile creature is within sight and
           stamina is sufficient
  - Walk:  default (free, no stamina cost)
"""
from __future__ import annotations
from enum import IntEnum


class Action(IntEnum):
    # Movement (0-7: 8 directions, mode auto-selected)
    MOVE_N  = 0
    MOVE_NE = 1
    MOVE_E  = 2
    MOVE_SE = 3
    MOVE_S  = 4
    MOVE_SW = 5
    MOVE_W  = 6
    MOVE_NW = 7

    # Movement mode toggle
    SET_SNEAK = 8    # toggles sneak on/off; walk vs run is automatic

    # Combat
    MELEE_ATTACK = 9
    RANGED_ATTACK = 10
    GRAPPLE = 11
    CAST_SPELL = 12

    # Social
    INTIMIDATE = 13
    DECEIVE = 14
    TRADE = 15
    BRIBE = 16
    STEAL = 17
    SHARE_RUMOR = 18
    TALK = 19

    # Utility
    PICKUP = 20
    DROP = 21
    USE_ITEM = 22
    WAIT = 23
    GUARD = 24
    SEARCH = 25
    FLEE = 26
    FOLLOW = 27
    CALL_BACKUP = 28
    SLEEP = 29
    SET_TRAP = 30

    # Stances
    BLOCK_STANCE = 31
    EXIT_BLOCK = 32
    EXIT_GUARD = 33

    # Economy
    DIG = 34
    PUSH = 35
    CRAFT = 36
    DISASSEMBLE = 37
    HARVEST = 38
    JOB = 39
    FARM = 40
    PROCESS = 41

    # Reproduction
    PAIR = 42


NUM_ACTIONS = len(Action)

# Tile purposes — what a tile is designated for
TILE_PURPOSES = (
    'trading', 'farming', 'hunting', 'worship', 'eating',
    'sleeping', 'pairing', 'crafting', 'mining', 'fishing',
    'gathering', 'training', 'healing', 'guarding', 'socializing',
    'gossiping', 'exploring',
)
NUM_PURPOSES = len(TILE_PURPOSES)

# Action → tile purpose alignment
ACTION_PURPOSE = {
    Action.TRADE: 'trading',
    Action.BRIBE: 'trading',
    Action.STEAL: 'trading',
    Action.MELEE_ATTACK: 'hunting',
    Action.RANGED_ATTACK: 'hunting',
    Action.GRAPPLE: 'hunting',
    Action.CAST_SPELL: 'training',
    Action.INTIMIDATE: 'socializing',
    Action.DECEIVE: 'socializing',
    Action.TALK: 'socializing',
    Action.SHARE_RUMOR: 'gossiping',
    Action.SLEEP: 'sleeping',
    Action.GUARD: 'guarding',
    Action.SEARCH: 'gathering',
    Action.PICKUP: 'gathering',
    Action.DIG: 'mining',
    Action.CRAFT: 'crafting',
    Action.DISASSEMBLE: 'crafting',
    Action.HARVEST: 'farming',
    Action.FARM: 'farming',
    Action.JOB: None,
    Action.PROCESS: 'crafting',
    Action.PAIR: 'pairing',
    Action.USE_ITEM: 'eating',
    Action.SET_TRAP: 'hunting',
}


def action_aligned_with_tile(action: int, tile, zone_purposes: set = None) -> bool:
    """Return True if the action matches the tile's purpose or zone purposes."""
    aligned_purpose = ACTION_PURPOSE.get(action)
    if aligned_purpose is None:
        return False
    if zone_purposes and aligned_purpose in zone_purposes:
        return True
    purpose = getattr(tile, 'purpose', None)
    return purpose == aligned_purpose


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
    Action.DIG: 'dig', Action.PUSH: 'push',
    Action.CRAFT: 'craft', Action.DISASSEMBLE: 'disassemble',
    Action.HARVEST: 'harvest',
    Action.JOB: 'job', Action.FARM: 'farm',
    Action.PROCESS: 'process',
    Action.PAIR: 'pair',
    Action.SET_SNEAK: 'set_sneak',
    Action.EXIT_BLOCK: 'exit_block', Action.EXIT_GUARD: 'exit_guard',
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


def _should_run(creature, context) -> bool:
    """Auto-select run mode when a hostile is in sight and stamina allows."""
    from classes.stats import Stat
    if creature.stats.active[Stat.CUR_STAMINA]() < 3:
        return False
    from classes.relationship_graph import GRAPH
    from classes.stats import Stat
    sight = creature.stats.active[Stat.SIGHT_RANGE]()
    cx, cy = creature.location.x, creature.location.y
    rels = GRAPH.edges_from(creature.uid)
    if not rels:
        return False
    from classes.world_object import WorldObject
    from classes.creature import Creature as _C
    for obj in WorldObject.on_map(creature.current_map):
        if not isinstance(obj, _C) or obj is creature or not obj.is_alive:
            continue
        dist = abs(cx - obj.location.x) + abs(cy - obj.location.y)
        if dist > sight:
            continue
        rel = rels.get(obj.uid)
        if rel and rel[0] < -5:
            return True
    return False


def dispatch(creature, action: int, context: dict) -> dict:
    """Execute an action for a creature."""
    result = _dispatch_inner(creature, action, context)
    succeeded = result.get('success', result.get('hit', False))
    if succeeded:
        _record_god_action(action)
        _emit_action_sound(creature, action, context)
    else:
        creature.failed_actions = getattr(creature, 'failed_actions', 0) + 1
    return result


def _emit_action_sound(creature, action: int, context: dict):
    from classes.sound import emit_sound

    if 0 <= action <= 7:
        emit_sound(creature, 'footstep', tick=context.get('now', 0))
        return

    if action in (Action.MELEE_ATTACK, Action.RANGED_ATTACK,
                   Action.GRAPPLE, Action.CAST_SPELL):
        emit_sound(creature, 'combat', tick=context.get('now', 0))
        return

    if action in (Action.TALK, Action.INTIMIDATE, Action.DECEIVE,
                   Action.SHARE_RUMOR, Action.TRADE, Action.BRIBE):
        emit_sound(creature, 'speech', tick=context.get('now', 0))
        return

    if action in (Action.HARVEST, Action.FARM, Action.PROCESS, Action.JOB):
        emit_sound(creature, 'harvest', tick=context.get('now', 0))
        return

    if action in (Action.DROP, Action.PICKUP):
        emit_sound(creature, 'drop', tick=context.get('now', 0))
        return

    if action == Action.PUSH:
        emit_sound(creature, 'struggle', tick=context.get('now', 0))
        return


def _dispatch_inner(creature, action: int, context: dict) -> dict:
    """Inner dispatch — actual action execution."""
    cols = context.get('cols', 0)
    rows = context.get('rows', 0)
    target = context.get('target')
    item = context.get('item')
    now = context.get('now', 0)

    # Decay social context TTL — TALK/TRADE set a 2-tick window
    # during which DECEIVE can fire as a follow-up action.
    ttl = getattr(creature, '_social_context_ttl', 0)
    if ttl > 0 and action != Action.DECEIVE:
        creature._social_context_ttl = ttl - 1
        if creature._social_context_ttl <= 0:
            creature._active_social_target = None

    combat_enabled = context.get('combat_enabled', True)
    if not combat_enabled and action in (Action.MELEE_ATTACK, Action.RANGED_ATTACK,
                                          Action.GRAPPLE, Action.CAST_SPELL):
        return {'success': False, 'reason': 'combat_disabled'}

    # -- Movement (auto walk/run/sneak) --
    if 0 <= action <= 7:
        dx, dy = _DIRS[action]
        mode = getattr(creature, 'movement_mode', 'walk')
        if mode == 'sneak':
            return {'success': creature.sneak(dx, dy, cols, rows)}
        elif _should_run(creature, context):
            return {'success': creature.run(dx, dy, cols, rows)}
        else:
            old = creature.location
            creature.move(dx, dy, cols, rows)
            return {'success': creature.location != old}

    # -- Sneak toggle --
    if action == Action.SET_SNEAK:
        current = getattr(creature, 'movement_mode', 'walk')
        creature.movement_mode = 'walk' if current == 'sneak' else 'sneak'
        return {'success': True}

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
            from data.db import SPELLS
            known = creature.get_known_spells()
            for sk in known:
                if sk in SPELLS:
                    spell = SPELLS[sk]
                    break
            if spell is None:
                return {'success': False, 'reason': 'no_spell'}
        return creature.cast_spell(spell, target, now)

    if action == Action.TRADE:
        if target is None:
            from classes.world_object import WorldObject
            from classes.creature import Creature as _Creature
            target = next(
                (o for o in WorldObject.on_map(creature.current_map)
                 if isinstance(o, _Creature) and o is not creature
                 and o.is_alive
                 and abs(o.location.x - creature.location.x) +
                     abs(o.location.y - creature.location.y) <= 1),
                None
            )
            if target is None:
                return {'success': False, 'reason': 'no_partner'}
        result = creature.auto_trade(target)
        if result.get('success'):
            creature._active_social_target = target
            creature._social_context_ttl = 2
            creature._check_deceit_revelation(target)
            target._check_deceit_revelation(creature)
        return result

    # -- Social (requires sentient target) --
    if Action.INTIMIDATE <= action <= Action.TALK:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        if not getattr(target, 'sentient', True):
            return {'success': False, 'reason': 'not_sentient'}

    if action == Action.INTIMIDATE:
        return creature.intimidate(target)

    if action == Action.DECEIVE:
        active = getattr(creature, '_active_social_target', None)
        if active is None:
            return {'success': False, 'reason': 'no_social_context'}
        result = creature.deceive(active)
        creature._active_social_target = None
        creature._social_context_ttl = 0
        return result

    if action == Action.BRIBE:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        items = context.get('items', [])
        return creature.bribe(target, items)

    if action == Action.STEAL:
        if target is None:
            from classes.world_object import WorldObject
            from classes.creature import Creature as _Creature
            target = next(
                (o for o in WorldObject.on_map(creature.current_map)
                 if isinstance(o, _Creature) and o is not creature
                 and o.is_alive
                 and abs(o.location.x - creature.location.x) +
                     abs(o.location.y - creature.location.y) <= 1),
                None
            )
            if target is None:
                return {'success': False, 'reason': 'no_target'}
        return creature.steal(target, item)

    if action == Action.SHARE_RUMOR:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        subject_uid = context.get('subject_uid', 0)
        sentiment = context.get('sentiment', 0.0)
        tick = context.get('tick', now)
        success = creature.share_rumor(target, subject_uid, sentiment, tick)
        if success:
            creature._check_deceit_revelation(target)
            target._check_deceit_revelation(creature)
        return {'success': success}

    if action == Action.TALK:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        conv = context.get('conversation')
        roots = creature.start_conversation(target, conv)
        success = len(roots) > 0
        if success:
            creature._active_social_target = target
            creature._social_context_ttl = 2
            creature._check_deceit_revelation(target)
            target._check_deceit_revelation(creature)
        return {'success': success, 'roots': roots}

    # -- Utility --
    if action == Action.PICKUP:
        tile = creature.current_map.tiles.get(creature.location)
        has_gold = getattr(tile, 'gold', 0) > 0 if tile else False
        has_items = bool(tile and tile.inventory.items)
        if not has_gold and not has_items and item is None:
            return {'success': True, 'reason': 'nothing_here'}
        gold_picked = creature.pickup_gold()
        if item is None:
            if has_items:
                item = tile.inventory.items[0]
            elif gold_picked > 0:
                creature._pickups = getattr(creature, '_pickups', 0) + 1
                return {'success': True, 'gold_picked': gold_picked}
            else:
                return {'success': True, 'reason': 'nothing_here'}
        result = creature.pickup(item)
        if result or gold_picked > 0:
            creature._pickups = getattr(creature, '_pickups', 0) + 1
        return {'success': result or gold_picked > 0, 'gold_picked': gold_picked}

    if action == Action.DROP:
        if item is None:
            return {'success': creature.smart_drop()}
        return {'success': creature.drop(item)}

    if action == Action.USE_ITEM:
        if item is None:
            from classes.inventory import Consumable
            for inv_item in creature.inventory.items:
                if isinstance(inv_item, Consumable):
                    item = inv_item
                    break
            if item is None:
                return {'success': True, 'reason': 'no_consumable'}
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
            for inv_item in creature.inventory.items:
                if getattr(inv_item, 'is_trap', False):
                    item = inv_item
                    break
            if item is None:
                return {'success': False, 'reason': 'no_trap_item'}
        dc = getattr(item, 'trap_dc', None) or context.get('trap_dc', 10)
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

    # -- Dig / Push --
    if action == Action.DIG:
        return creature.dig()

    if action == Action.PUSH:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        dx = target.location.x - creature.location.x
        dy = target.location.y - creature.location.y
        return creature.push(target, dx, dy, cols, rows)

    if action == Action.CRAFT:
        return creature.craft()

    if action == Action.DISASSEMBLE:
        if item is None:
            from classes.inventory import ItemFrame as _IF
            for inv_item in creature.inventory.items:
                if isinstance(inv_item, _IF) and inv_item.ingredients.items:
                    item = inv_item
                    break
            if item is None:
                return {'success': False, 'reason': 'nothing_to_disassemble'}
        return creature.disassemble(item)

    if action == Action.HARVEST:
        return creature.harvest()

    if action == Action.FARM:
        return creature.farm()

    if action == Action.JOB:
        return creature.do_job(context.get('now', 0))

    if action == Action.PROCESS:
        return creature.process()

    if action == Action.PAIR:
        if target is None:
            from classes.world_object import WorldObject
            from classes.creature import Creature as _Creature
            target = next(
                (o for o in WorldObject.on_map(creature.current_map)
                 if isinstance(o, _Creature) and o is not creature
                 and o.is_alive
                 and o.sex != creature.sex
                 and o.species == creature.species
                 and abs(o.location.x - creature.location.x) +
                     abs(o.location.y - creature.location.y) <= 1),
                None
            )
            if target is None:
                return {'success': False, 'reason': 'no_partner'}
        if creature.sex == 'male':
            return creature.propose_pairing(target, now)
        return target.propose_pairing(creature, now)

    return {'success': False, 'reason': 'unknown_action'}
