"""
Action space for the creature RL system.

32 actions organized by category. Movement is a single MOVE action
that auto-resolves direction toward the creature's goal target.
Locomotion mode (walk/run/sneak) is auto-selected:
  - Sneak: if creature.movement_mode == 'sneak' (toggled by SET_SNEAK)
  - Run:   auto-selected when a hostile creature is within sight
  - Walk:  default

Dynamic action masking: compute_dynamic_mask() returns a per-tick
binary array based on creature state. Combined with the static
curriculum mask via AND to prevent impossible actions.
"""
from __future__ import annotations
from enum import IntEnum
import numpy as np


class Action(IntEnum):
    # Movement
    MOVE = 0             # auto-direction toward goal, auto walk/run/sneak
    SET_SNEAK = 1        # toggle sneak mode
    FLEE = 2             # move away from nearest threat
    FOLLOW = 3           # move toward target creature

    # Combat
    MELEE_ATTACK = 4
    RANGED_ATTACK = 5
    GRAPPLE = 6
    CAST_SPELL = 7

    # Social
    INTIMIDATE = 8
    DECEIVE = 9          # gated on active social context (TALK/TRADE first)
    TRADE = 10
    STEAL = 11
    TALK = 12            # auto-shares rumor on success

    # Utility
    PICKUP = 13
    DROP = 14
    USE_ITEM = 15
    WAIT = 16
    GUARD = 17           # toggle: re-select to exit guard stance
    SEARCH = 18
    SLEEP = 19
    SET_TRAP = 20
    BLOCK_STANCE = 21    # toggle: re-select to exit block stance
    CALL_BACKUP = 22

    # Economy
    DIG = 23
    PUSH = 24
    CRAFT = 25
    DISASSEMBLE = 26
    HARVEST = 27
    FARM = 28
    PROCESS = 29

    # Reproduction
    PAIR = 30

    # Debt
    REPAY_LOAN = 31


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
    Action.STEAL: 'trading',
    Action.MELEE_ATTACK: 'hunting',
    Action.RANGED_ATTACK: 'hunting',
    Action.GRAPPLE: 'hunting',
    Action.CAST_SPELL: 'training',
    Action.INTIMIDATE: 'socializing',
    Action.DECEIVE: 'socializing',
    Action.TALK: 'socializing',
    Action.SLEEP: 'sleeping',
    Action.GUARD: 'guarding',
    Action.SEARCH: 'gathering',
    Action.PICKUP: 'gathering',
    Action.DIG: 'mining',
    Action.CRAFT: 'crafting',
    Action.DISASSEMBLE: 'crafting',
    Action.HARVEST: 'farming',
    Action.FARM: 'farming',
    Action.PROCESS: 'crafting',
    Action.PAIR: 'pairing',
    Action.USE_ITEM: 'eating',
    Action.SET_TRAP: 'hunting',
    Action.REPAY_LOAN: 'trading',
}


def action_aligned_with_tile(action: int, tile, zone_purposes: set = None) -> bool:
    aligned_purpose = ACTION_PURPOSE.get(action)
    if aligned_purpose is None:
        return False
    if zone_purposes and aligned_purpose in zone_purposes:
        return True
    purpose = getattr(tile, 'purpose', None)
    return purpose == aligned_purpose


# Action → god-tracking name
ACTION_NAMES = {a: a.name.lower() for a in Action}


_world_data_cache = None

def _get_world_data():
    global _world_data_cache
    if _world_data_cache is not None:
        return _world_data_cache
    try:
        from classes.gods import WorldData
        instances = WorldData.all()
        if instances:
            _world_data_cache = instances[-1]
            return _world_data_cache
    except Exception:
        pass
    return None

def _record_god_action(action: int):
    action_name = ACTION_NAMES.get(action)
    if action_name is None:
        return
    wd = _get_world_data()
    if wd:
        wd.record_action(action_name)


# Direction vectors for 8-dir movement (used by FLEE, FOLLOW, sleepwalk)
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
    from classes.stats import Stat
    if creature.stats.active[Stat.CUR_STAMINA]() < 3:
        return False
    from classes.relationship_graph import GRAPH
    rels = GRAPH.edges_from(creature.uid)
    if not rels:
        return False
    for obj in creature.nearby():
        rel = rels.get(obj.uid)
        if rel and rel[0] < -5:
            return True
    return False


def _do_move(creature, dx, dy, cols, rows, context):
    """Execute one movement step with auto walk/run/sneak."""
    mode = getattr(creature, 'movement_mode', 'walk')
    if mode == 'sneak':
        return creature.sneak(dx, dy, cols, rows)
    elif _should_run(creature, context):
        return creature.run(dx, dy, cols, rows)
    else:
        old = creature.location
        creature.move(dx, dy, cols, rows)
        return creature.location != old


def _auto_work(creature, now: int):
    job = getattr(creature, 'job', None)
    if job is None or getattr(creature, '_occupation', None) is not None:
        return
    tile = creature.current_map.tiles.get(creature.location) if creature.current_map else None
    if tile is None:
        return
    tile_purpose = getattr(tile, 'purpose', None)
    if not tile_purpose or tile_purpose not in job.workplace_purposes:
        return
    schedule = getattr(creature, 'schedule', None)
    if schedule is None:
        return
    from classes.creature._utility import _current_hour
    if schedule.in_work_hours(_current_hour(now)):
        creature.do_job(now)


def _auto_share_rumor(creature, target, now):
    """Auto-share a rumor during TALK if creature has gossip."""
    from classes.relationship_graph import GRAPH
    import random as _rng
    rels = GRAPH.edges_from(creature.uid)
    candidates = [(uid, r[0]) for uid, r in rels.items()
                  if uid != target.uid and abs(r[0]) > 3 and r[1] >= 2]
    if candidates:
        subject_uid, sentiment = _rng.choice(candidates)
        confidence = min(1.0, abs(sentiment) / 20.0)
        creature.share_rumor(target, subject_uid, sentiment, now)

    # Auto-share a death rumor if the creature is carrying one.
    # Runs regardless of whether peer-rumor gossip fired.
    try:
        from classes.mourning import share_death_news
        share_death_news(creature, target, now)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Dynamic action mask
# ---------------------------------------------------------------------------

def compute_dynamic_mask(creature, context: dict = None) -> np.ndarray:
    """Compute a per-tick binary mask based on creature state.

    Returns a NUM_ACTIONS-length array where 1 = available, 0 = impossible.
    This is ANDed with the static curriculum mask before action selection.
    """
    from classes.stats import Stat
    from classes.inventory import Consumable, Weapon, Equippable, Slot
    from classes.inventory import ItemFrame as _IF

    mask = np.ones(NUM_ACTIONS, dtype=np.float32)

    # Context
    has_adjacent = False
    has_visible = False
    has_hostile_visible = False
    if creature.current_map:
        from classes.relationship_graph import GRAPH
        cx, cy = creature.location.x, creature.location.y
        rels = GRAPH.edges_from(creature.uid)
        for obj in creature.nearby():
            d = abs(cx - obj.location.x) + abs(cy - obj.location.y)
            if d <= 1:
                has_adjacent = True
            has_visible = True
            rel = rels.get(obj.uid)
            if rel and rel[0] < -5:
                has_hostile_visible = True

    tile = creature.current_map.tiles.get(creature.location) if creature.current_map else None

    # Combat: need adjacent/visible targets
    if not has_adjacent:
        mask[Action.MELEE_ATTACK] = 0
        mask[Action.GRAPPLE] = 0
        mask[Action.PUSH] = 0
    if not has_visible:
        mask[Action.RANGED_ATTACK] = 0
        mask[Action.INTIMIDATE] = 0
        mask[Action.TALK] = 0
        mask[Action.FOLLOW] = 0
    if not has_hostile_visible:
        mask[Action.FLEE] = 0
    if not has_adjacent:
        mask[Action.STEAL] = 0
        mask[Action.TRADE] = 0
        mask[Action.PAIR] = 0

    # Ranged: need weapon + ammo
    weapon = creature.equipment.get(Slot.HAND_R) or creature.equipment.get(Slot.HAND_L)
    if not (weapon and isinstance(weapon, Weapon) and weapon.range > 1):
        mask[Action.RANGED_ATTACK] = 0

    # Spell: need known spells + mana
    if not (hasattr(creature, 'get_known_spells') and creature.get_known_spells()):
        mask[Action.CAST_SPELL] = 0

    # Deceive: need social context
    if getattr(creature, '_active_social_target', None) is None:
        mask[Action.DECEIVE] = 0

    # Inventory
    has_consumable = any(isinstance(i, Consumable) for i in creature.inventory.items)
    has_trap = any(getattr(i, 'is_trap', False) for i in creature.inventory.items)
    has_frame_complete = any(isinstance(i, _IF) and hasattr(i, 'is_complete') and i.is_complete
                            for i in creature.inventory.items)
    has_frame_ingredients = any(isinstance(i, _IF) and i.ingredients.items
                               for i in creature.inventory.items)

    if not has_consumable:
        mask[Action.USE_ITEM] = 0
    if not creature.inventory.items:
        mask[Action.DROP] = 0
    if not has_trap:
        mask[Action.SET_TRAP] = 0
    if not has_frame_complete:
        mask[Action.CRAFT] = 0
    if not has_frame_ingredients:
        mask[Action.DISASSEMBLE] = 0

    # Tile-based
    tile_has_items = tile and (tile.inventory.items or getattr(tile, 'gold', 0) > 0)
    tile_has_resource = tile and getattr(tile, 'resource_type', None) and getattr(tile, 'resource_amount', 0) > 0
    tile_has_buried = tile and getattr(tile, 'buried_gold', 0) > 0
    has_shovel = any(getattr(i, 'name', '') == 'Shovel' for i in creature.inventory.items) or \
                 any(getattr(e, 'name', '') == 'Shovel' for e in creature.equipment.values() if e)

    if not tile_has_items:
        mask[Action.PICKUP] = 0
    if not tile_has_resource:
        mask[Action.HARVEST] = 0
        mask[Action.FARM] = 0
    if not (tile_has_buried and has_shovel):
        mask[Action.DIG] = 0
    if not (tile and getattr(tile, 'purpose', None) == 'crafting'):
        mask[Action.PROCESS] = 0

    # Stances (toggle: if already active, allow to toggle off; mask if no weapon for block)
    if getattr(creature, '_guarding', False):
        pass  # allow GUARD to toggle off
    elif creature.stats.active[Stat.CUR_STAMINA]() < 2:
        mask[Action.GUARD] = 0

    blocking = getattr(creature, 'is_blocking', False)
    if not blocking:
        hand_r = creature.equipment.get(Slot.HAND_R)
        hand_l = creature.equipment.get(Slot.HAND_L)
        if not (hand_r or hand_l):
            mask[Action.BLOCK_STANCE] = 0

    # Sleep: already sleeping
    if getattr(creature, '_sleeping', False):
        mask[Action.SLEEP] = 0

    # Pair: cooldown, not fertile, no eligible adjacent
    if getattr(creature, '_pair_cooldown', 0) > 0 or not creature.is_fertile:
        mask[Action.PAIR] = 0

    # Debt
    if not creature.loans or creature.gold <= 0:
        mask[Action.REPAY_LOAN] = 0

    # Phase 7 arousal gating — some actions are only valid in
    # certain arousal states (calm pair, no combat-spells while calm).
    # Skipped entirely when the creature's arousal FSM hasn't been
    # built (equivalent to 'calm' default; only listed actions that
    # require non-calm states would be blocked).
    if hasattr(creature, 'arousal_action_allowed'):
        from classes.creature._arousal import get_action_gates
        for act, _allowed in get_action_gates().items():
            if not creature.arousal_action_allowed(act):
                mask[act] = 0

    # Phase 1 compound action_state gating — stunned/sleeping/dead
    # creatures can't select any action except WAIT. (WAIT left open
    # so sampling has at least one valid action; blocking the whole
    # mask would break action-distribution sampling.) Only fires when
    # the FSM has been built — pre-FSM creatures behave unchanged.
    _action_fsm = getattr(creature, 'action_state', None)
    if _action_fsm is not None and _action_fsm.current != 'normal':
        mask[:] = 0
        mask[Action.WAIT] = 1

    # Phase 2 lifecycle gating — creatures not in a living, active
    # lifecycle state (egg/gestating/dying/dead) can't act beyond
    # WAIT. Runs AFTER arousal/action_state gates so the most
    # restrictive check wins.
    _lc = getattr(creature, 'lifecycle_state', 'adult')
    if _lc in ('egg', 'gestating', 'dying', 'dead'):
        mask[:] = 0
        mask[Action.WAIT] = 1

    return mask


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(creature, action: int, context: dict) -> dict:
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
    tick = context.get('now', 0)

    if action == Action.MOVE:
        emit_sound(creature, 'footstep', tick=tick)
    elif action in (Action.MELEE_ATTACK, Action.RANGED_ATTACK,
                    Action.GRAPPLE, Action.CAST_SPELL):
        emit_sound(creature, 'combat', tick=tick)
    elif action in (Action.TALK, Action.INTIMIDATE, Action.DECEIVE,
                    Action.TRADE):
        emit_sound(creature, 'speech', tick=tick)
    elif action in (Action.HARVEST, Action.FARM, Action.PROCESS):
        emit_sound(creature, 'harvest', tick=tick)
    elif action in (Action.DROP, Action.PICKUP):
        emit_sound(creature, 'drop', tick=tick)
    elif action == Action.PUSH:
        emit_sound(creature, 'struggle', tick=tick)


def _dispatch_inner(creature, action: int, context: dict) -> dict:
    cols = context.get('cols', 0)
    rows = context.get('rows', 0)
    target = context.get('target')
    item = context.get('item')
    now = context.get('now', 0)

    # Decay social context TTL
    ttl = getattr(creature, '_social_context_ttl', 0)
    if ttl > 0 and action != Action.DECEIVE:
        creature._social_context_ttl = ttl - 1
        if creature._social_context_ttl <= 0:
            creature._active_social_target = None

    # -- Auto-triggers --
    # Forced sleep at fatigue level 4 (collapse)
    if getattr(creature, '_fatigue_level', 0) >= 4 and not getattr(creature, '_sleeping', False):
        creature.sleep(now)
        return {'success': True, 'reason': 'collapse'}

    # Auto-eat at extreme hunger
    hunger = getattr(creature, 'hunger', 0.0)
    if hunger < -0.8 and getattr(creature, '_occupation', None) is None:
        from classes.inventory import Consumable
        food = next((i for i in creature.inventory.items
                     if isinstance(i, Consumable) and getattr(i, 'is_food', False)), None)
        if food:
            creature.use_item(food)
            if hasattr(creature, 'eat'):
                creature.eat(0.3)
            return {'success': True, 'reason': 'auto_eat'}

    # -- Occupation intercept --
    occupation = getattr(creature, '_occupation', None)
    if occupation == 'sleep':
        interrupt = creature._tick_sleep(now)
        if interrupt is None:
            return {'success': True, 'reason': 'sleeping'}
        kind, reason = interrupt
        creature.wake()
        if kind == 'sleepwalk':
            import random as _rng
            dx, dy = _DIRS[_rng.randint(0, 7)]
            creature.move(dx, dy, cols, rows)
            creature.sleep(now)
            return {'success': True, 'reason': 'sleepwalk'}
    elif occupation == 'work':
        if not creature._check_work_interrupt(now):
            creature._tick_work(now)
            return {'success': True, 'reason': 'working'}

    combat_enabled = context.get('combat_enabled', True)
    if not combat_enabled and action in (Action.MELEE_ATTACK, Action.RANGED_ATTACK,
                                          Action.GRAPPLE, Action.CAST_SPELL):
        return {'success': False, 'reason': 'combat_disabled'}

    # -- MOVE: auto-direction toward goal --
    if action == Action.MOVE:
        dx, dy = creature.direction_to_goal()
        if dx == 0 and dy == 0:
            import random as _rng
            dx, dy = _DIRS[_rng.randint(0, 7)]
        moved = _do_move(creature, dx, dy, cols, rows, context)
        if moved:
            _auto_work(creature, now)
        return {'success': moved}

    if action == Action.SET_SNEAK:
        current = getattr(creature, 'movement_mode', 'walk')
        creature.movement_mode = 'walk' if current == 'sneak' else 'sneak'
        return {'success': True}

    if action == Action.FLEE:
        if target is None:
            return {'success': False, 'reason': 'no_threat'}
        return {'success': creature.flee(target, cols, rows)}

    if action == Action.FOLLOW:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        return {'success': creature.follow(target, cols, rows)}

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

    # -- Social --
    if action == Action.TRADE:
        if target is None:
            target = next(
                (o for o in creature.nearby(max_dist=1, include_ghosts=False)),
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

    if action == Action.INTIMIDATE:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        if not getattr(target, 'sentient', True):
            return {'success': False, 'reason': 'not_sentient'}
        return creature.intimidate(target)

    if action == Action.DECEIVE:
        active = getattr(creature, '_active_social_target', None)
        if active is None:
            return {'success': False, 'reason': 'no_social_context'}
        result = creature.deceive(active)
        creature._active_social_target = None
        creature._social_context_ttl = 0
        return result

    if action == Action.STEAL:
        if target is None:
            target = next(
                (o for o in creature.nearby(max_dist=1, include_ghosts=False)),
                None
            )
            if target is None:
                return {'success': False, 'reason': 'no_target'}
        return creature.steal(target, item)

    if action == Action.TALK:
        if target is None:
            return {'success': False, 'reason': 'no_target'}
        if not getattr(target, 'sentient', True):
            return {'success': False, 'reason': 'not_sentient'}
        conv = context.get('conversation')
        roots = creature.start_conversation(target, conv)
        success = len(roots) > 0
        if success:
            creature._active_social_target = target
            creature._social_context_ttl = 2
            creature._check_deceit_revelation(target)
            target._check_deceit_revelation(creature)
            _auto_share_rumor(creature, target, now)
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
        if getattr(creature, '_guarding', False):
            creature.stop_guard()
            return {'success': True}
        return {'success': creature.guard(cols, rows)}

    if action == Action.SEARCH:
        return creature.search_tile()

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

    if action == Action.BLOCK_STANCE:
        if getattr(creature, 'is_blocking', False):
            creature.exit_block_stance()
            return {'success': True}
        return {'success': creature.enter_block_stance()}

    if action == Action.CALL_BACKUP:
        responders = creature.call_backup()
        return {'success': len(responders) > 0, 'responders': responders}

    # -- Economy --
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

    if action == Action.PROCESS:
        return creature.process()

    # -- Reproduction --
    if action == Action.PAIR:
        if target is None:
            target = next(
                (o for o in creature.nearby(max_dist=1, include_ghosts=False)
                 if o.sex != creature.sex and o.species == creature.species),
                None
            )
            if target is None:
                return {'success': False, 'reason': 'no_partner'}
        if creature.sex == 'male':
            return creature.propose_pairing(target, now)
        return target.propose_pairing(creature, now)

    # -- Debt --
    if action == Action.REPAY_LOAN:
        if not creature.loans:
            return {'success': False, 'reason': 'no_debt'}
        lender_uid = next(iter(creature.loans))
        from classes.creature import Creature as _C
        lender = _C.by_uid(lender_uid)
        if lender is None:
            return {'success': False, 'reason': 'lender_gone'}
        return creature.repay_loan(lender, creature.gold, now)

    return {'success': False, 'reason': 'unknown_action'}
