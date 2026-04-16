"""
Monster action dispatch.

Given an action index from MonsterNet (or the heuristic policy),
execute the corresponding runtime behavior and return a result dict.

Result shape (for reward computation):
    {
      'action': int,
      'success': bool,
      'reason': str,          # populated on failure
      'target': Creature|Monster|None,
      'damage_dealt': int,
      'hunger_restored': float,
      'ate_own_species': bool,   # future cannibalism hooks
    }
"""
from __future__ import annotations
import math
import random
from classes.monster_actions import MonsterAction, compute_monster_mask
from classes.stats import Stat
from classes.maps import MapKey


def dispatch_monster(monster, action: int, context: dict) -> dict:
    """Execute a monster action and return a result dict.

    Args:
        monster: Monster instance
        action: MonsterAction enum int
        context: dict with keys cols, rows, now, target (optional)
    """
    result = {
        'action': action,
        'success': False,
        'reason': '',
        'target': None,
        'damage_dealt': 0,
        'hunger_restored': 0.0,
        'ate_own_species': False,
    }

    if not monster.is_alive:
        result['reason'] = 'dead'
        return result

    cols = context.get('cols', 50)
    rows = context.get('rows', 50)
    now = context.get('now', 0)
    target = context.get('target')

    a = MonsterAction(action)

    if a == MonsterAction.MOVE:
        return _do_move(monster, cols, rows, now, result)
    if a == MonsterAction.PATROL:
        return _do_patrol(monster, cols, rows, now, result)
    if a == MonsterAction.GUARD:
        return _do_guard(monster, result)
    if a == MonsterAction.ATTACK:
        return _do_attack(monster, target, now, result)
    if a == MonsterAction.PAIR:
        return _do_pair(monster, now, result)
    if a == MonsterAction.EAT:
        return _do_eat(monster, now, result)
    if a == MonsterAction.HOWL:
        return _do_howl(monster, result)
    if a == MonsterAction.FLEE:
        return _do_flee(monster, cols, rows, now, result)
    if a == MonsterAction.REST:
        return _do_rest(monster, result)
    if a == MonsterAction.PROTECT_EGG:
        return _do_protect_egg(monster, result)
    if a == MonsterAction.HARVEST:
        return _do_harvest(monster, now, result)

    result['reason'] = 'unknown_action'
    return result


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

def _step_toward(monster, tx: int, ty: int, cols: int, rows: int) -> bool:
    """Take a single tile step toward (tx, ty). Returns True if moved."""
    mx, my = monster.location.x, monster.location.y
    dx = 0 if tx == mx else (1 if tx > mx else -1)
    dy = 0 if ty == my else (1 if ty > my else -1)
    if dx == 0 and dy == 0:
        return False
    old_loc = monster.location
    monster.move(dx, dy, cols, rows)
    return monster.location != old_loc


def _do_move(monster, cols, rows, now, result) -> dict:
    """Move toward pack-assigned target position (fallback: random)."""
    target_pos = monster._pack_target_position
    if target_pos is None:
        # No pack target — sample a fresh one from territory
        if monster.pack is not None:
            target_pos = monster.pack.sample_target_position()
            monster._pack_target_position = target_pos
        else:
            # Solo drift: random step
            dx, dy = random.choice([(1,0),(-1,0),(0,1),(0,-1)])
            old = monster.location
            monster.move(dx, dy, cols, rows)
            result['success'] = monster.location != old
            monster._is_fleeing = False
            return result

    moved = _step_toward(monster, target_pos.x, target_pos.y, cols, rows)
    result['success'] = moved
    monster._is_fleeing = False
    return result


def _do_patrol(monster, cols, rows, now, result) -> dict:
    """Sample a fresh territory target and step toward it."""
    if monster.pack is not None:
        new_target = monster.pack.sample_target_position()
        monster._pack_target_position = new_target
        moved = _step_toward(monster, new_target.x, new_target.y, cols, rows)
        result['success'] = moved
    else:
        # Solo: random step
        dx, dy = random.choice([(1,0),(-1,0),(0,1),(0,-1)])
        old = monster.location
        monster.move(dx, dy, cols, rows)
        result['success'] = monster.location != old
    monster._is_fleeing = False
    return result


def _do_flee(monster, cols, rows, now, result) -> dict:
    """Move away from nearest visible creature. Sets is_fleeing flag."""
    from classes.creature import Creature
    if monster.current_map is None:
        result['reason'] = 'no_map'
        return result

    mx, my = monster.location.x, monster.location.y
    nearest = None
    nearest_d = 9999
    sight = max(1, monster.stats.active[Stat.SIGHT_RANGE]())
    for c in Creature.on_same_map(monster.current_map):
        if not c.is_alive:
            continue
        d = abs(c.location.x - mx) + abs(c.location.y - my)
        if d <= sight and d < nearest_d:
            nearest_d = d
            nearest = c

    if nearest is None:
        # No threat → regular move
        return _do_move(monster, cols, rows, now, result)

    # Flee direction (away from threat)
    dx = mx - nearest.location.x
    dy = my - nearest.location.y
    mdx = 1 if dx > 0 else (-1 if dx < 0 else 0)
    mdy = 1 if dy > 0 else (-1 if dy < 0 else 0)
    if mdx == 0 and mdy == 0:
        mdx, mdy = random.choice([(1,0),(-1,0),(0,1),(0,-1)])

    old = monster.location
    monster.move(mdx, mdy, cols, rows)
    result['success'] = monster.location != old
    monster._is_fleeing = True
    return result


# ---------------------------------------------------------------------------
# Combat
# ---------------------------------------------------------------------------

def _do_attack(monster, target, now, result) -> dict:
    """Melee/ranged attack against adjacent or in-range creature."""
    from classes.creature import Creature
    from classes.inventory import Weapon, Slot

    # If no explicit target, pick nearest visible creature
    if target is None or not getattr(target, 'is_alive', False):
        mx, my = monster.location.x, monster.location.y
        sight = max(1, monster.stats.active[Stat.SIGHT_RANGE]())
        nearest = None
        nearest_d = 9999
        for c in Creature.on_same_map(monster.current_map):
            if not c.is_alive:
                continue
            d = abs(c.location.x - mx) + abs(c.location.y - my)
            if d <= sight and d < nearest_d:
                nearest_d = d
                nearest = c
        target = nearest

    if target is None:
        result['reason'] = 'no_target'
        return result

    result['target'] = target
    dist = abs(target.location.x - monster.location.x) + abs(target.location.y - monster.location.y)

    # Check equipped weapon for ranged option
    weapon = monster.equipment.get(Slot.HAND_R) or monster.equipment.get(Slot.HAND_L)
    has_ranged = (weapon is not None and isinstance(weapon, Weapon)
                  and getattr(weapon, 'range', 1) > 1)

    if dist <= 1:
        # Melee
        r = monster.melee_attack(target, now)
        result['success'] = r.get('hit', False)
        result['damage_dealt'] = r.get('damage', 0)
        result['reason'] = r.get('reason', '')
        monster._is_fleeing = False
        return result

    if has_ranged and dist <= weapon.range:
        r = monster.ranged_attack(target, now)
        result['success'] = r.get('hit', False)
        result['damage_dealt'] = r.get('damage', 0)
        result['reason'] = r.get('reason', '')
        monster._is_fleeing = False
        return result

    # Out of range → close the distance
    result['reason'] = 'closing_distance'
    _step_toward(monster, target.location.x, target.location.y,
                 context_cols(), context_rows())
    monster._is_fleeing = False
    return result


def context_cols(): return 200   # safe default — mover clamps to map
def context_rows(): return 200


# ---------------------------------------------------------------------------
# Consumption / Recovery
# ---------------------------------------------------------------------------

def _do_eat(monster, now, result) -> dict:
    """Consume the first Meat item on the current tile."""
    from classes.inventory import Meat
    if monster.current_map is None:
        result['reason'] = 'no_map'
        return result
    tile = monster.current_map.tiles.get(monster.location)
    if tile is None:
        result['reason'] = 'no_tile'
        return result

    meat = None
    for item in tile.inventory.items:
        if isinstance(item, Meat):
            meat = item
            break
    if meat is None:
        # Try own inventory as fallback
        for item in monster.inventory.items:
            if isinstance(item, Meat):
                meat = item
                break
        if meat is None:
            result['reason'] = 'no_meat'
            return result

    # Check spoilage
    if meat.is_spoiled(now):
        result['reason'] = 'spoiled'
        # Eat anyway? Monsters with low INT don't care; high INT refuses.
        int_score = monster.stats.base.get(Stat.INT, 10)
        if int_score > 7:
            return result
        # Low-INT: eat spoiled meat, small HP penalty
        monster.stats.base[Stat.HP_CURR] = max(1,
            monster.stats.active[Stat.HP_CURR]() - 2)

    # Cannibalism check — monsters don't penalize themselves
    if meat.species == monster.species:
        result['ate_own_species'] = True

    # Apply hunger restoration
    restore = meat.meat_value
    monster.hunger = min(1.0, monster.hunger + restore)
    result['hunger_restored'] = restore
    result['success'] = True

    # Remove the meat from its container
    if meat in tile.inventory.items:
        tile.inventory.items.remove(meat)
    elif meat in monster.inventory.items:
        monster.inventory.items.remove(meat)

    monster._is_fleeing = False
    return result


def _do_harvest(monster, now, result) -> dict:
    """Harvest the current tile's resource if it matches monster's diet."""
    if monster.diet == 'carnivore':
        result['reason'] = 'carnivore'
        return result
    if monster.current_map is None:
        result['reason'] = 'no_map'
        return result
    tile = monster.current_map.tiles.get(monster.location)
    if tile is None:
        result['reason'] = 'no_tile'
        return result
    if getattr(tile, 'resource_type', None) is None:
        result['reason'] = 'no_resource'
        return result
    # Match compatible tile if set
    if (monster.compatible_tile is not None and
            tile.resource_type != monster.compatible_tile):
        result['reason'] = 'wrong_resource'
        return result

    amount = int(tile.resource_amount or 0)
    if amount <= 0:
        result['reason'] = 'depleted'
        return result

    # Monsters don't accumulate resources as items — they convert directly
    # to hunger. Each harvest point fills 0.05 hunger.
    tile.resource_amount = 0
    gain = min(1.0 - monster.hunger, amount * 0.05)
    monster.hunger = min(1.0, monster.hunger + gain)
    result['hunger_restored'] = gain
    result['success'] = True
    monster._is_fleeing = False
    return result


def _do_rest(monster, result) -> dict:
    """Restore stamina on the current tile (no movement)."""
    cur_stam = monster.stats.active[Stat.CUR_STAMINA]()
    max_stam = monster.stats.active[Stat.MAX_STAMINA]()
    if cur_stam >= max_stam:
        result['reason'] = 'full_stamina'
        return result
    # Boost regen this tick
    gain = max(1, int(max_stam * 0.1))
    monster.stats.base[Stat.CUR_STAMINA] = min(max_stam, cur_stam + gain)
    monster._ensure_stamina_regen()
    result['success'] = True
    monster._is_fleeing = False
    return result


def _do_guard(monster, result) -> dict:
    """Stay still, elevated perception (future: apply DETECTION mod)."""
    result['success'] = True
    monster._is_fleeing = False
    return result


# ---------------------------------------------------------------------------
# Social / Reproduction
# ---------------------------------------------------------------------------

def _do_pair(monster, now, result) -> dict:
    """Attempt to pair with a same-rank adjacent monster of opposite sex."""
    if monster.pack is None:
        result['reason'] = 'no_pack'
        return result
    if monster.age < 18:
        result['reason'] = 'underage'
        return result

    partner = None
    for other in monster.pack.members:
        if other is monster or not other.is_alive:
            continue
        if other.sex == monster.sex:
            continue
        if other.rank != monster.rank:
            continue
        # Must be adjacent
        d = abs(other.location.x - monster.location.x) + abs(other.location.y - monster.location.y)
        if d <= 1:
            partner = other
            break

    if partner is None:
        result['reason'] = 'no_partner_in_rank'
        return result

    result['target'] = partner
    # Simplified: mark the female pregnant. Actual reproduction is
    # handled in the pack reproduction tick (pack runtime).
    female = monster if monster.sex == 'female' else partner
    if not getattr(female, 'is_pregnant', False):
        female.is_pregnant = True
        female._gestation_tick_end = now + 180_000  # 3 min real time = 3 game days
        result['success'] = True
    else:
        result['reason'] = 'already_pregnant'
    monster._is_fleeing = False
    return result


def _do_howl(monster, result) -> dict:
    """Boost the pack's alert level by notifying the pack NN."""
    if monster.pack is None:
        result['reason'] = 'no_pack'
        return result
    # Bump alert_level directly via broadcast
    pack = monster.pack
    new_alert = min(1.0, pack.alert_level + 0.3)
    pack.broadcast_signals(pack.sleep_signal, new_alert, pack.cohesion,
                            pack.role_fractions)
    result['success'] = True
    monster._is_fleeing = False
    return result


def _do_protect_egg(monster, result) -> dict:
    """Mark protective state (future: ties into egg guarding reward)."""
    monster._is_fleeing = False
    result['success'] = True
    return result
