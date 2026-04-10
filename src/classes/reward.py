"""
Reward function for the creature RL system.

13 primary signals + penalties, all using ln(after/before) transforms.
The model learns weights — these scales just set relative importance.

See docs/nn_inputs_full.txt Section 27 for the reward signal values
that the model sees in its observation.
"""
from __future__ import annotations
import math
from classes.stats import Stat


def _ln_ratio(after: float, before: float, epsilon: float = 0.001) -> float:
    """ln(after / before) with safety for zero/negative."""
    return math.log(max(epsilon, after) / max(epsilon, before))


def _sln(x: float) -> float:
    """Signed ln: sign(x) * ln(|x| + 1)."""
    if x == 0:
        return 0.0
    return math.copysign(math.log(abs(x) + 1), x)


def compute_reward(creature, prev: dict, curr: dict,
                   breakdown: bool = False,
                   last_action: int = None) -> float | tuple[float, dict]:
    """Compute reward for a single step.

    Args:
        creature: the Creature being evaluated
        prev: previous snapshot from make_reward_snapshot()
        curr: current snapshot from make_reward_snapshot()
        breakdown: if True, also return per-signal dict
        last_action: action just performed (for purpose alignment bonus)

    Returns:
        float reward value, or (float, dict) if breakdown=True
    """
    signals = {}

    # ---- DEATH (overrides everything) ----
    if not curr['alive']:
        if prev['alive']:
            signals['death'] = -20.0
            total = -20.0
        else:
            signals['death_ongoing'] = -1.0
            total = -1.0
        return (total, signals) if breakdown else total

    # ---- 1. HP change (scale 8.0) ----
    signals['hp'] = _ln_ratio(curr['hp_ratio'], prev['hp_ratio']) * 8.0

    # ---- 2. Wealth / gold (scale 3.0) ----
    signals['gold'] = _ln_ratio(curr['gold'] + 1, prev['gold'] + 1) * 3.0

    # ---- 3. Debt reduction (scale 2.0) + underwater penalty ----
    signals['debt'] = 0.0
    if prev['debt'] > 0 or curr['debt'] > 0:
        signals['debt'] = _ln_ratio(prev['debt'] + 1, curr['debt'] + 1) * 2.0
    if curr['disposable'] < 0:
        signals['debt'] -= 0.5  # per-tick underwater penalty

    # ---- 4. Inventory value (scale 1.0) ----
    signals['inventory'] = _ln_ratio(curr['inv_value'] + 1, prev['inv_value'] + 1) * 1.0

    # ---- 5. Equipment KPI (scale 2.0) ----
    signals['equipment'] = _ln_ratio(curr['eq_kpi'] + 1, prev['eq_kpi'] + 1) * 2.0

    # ---- 6. Reputation (scale 3.0) ----
    offset = 50.0
    signals['reputation'] = _ln_ratio(curr['reputation'] + offset,
                                      prev['reputation'] + offset) * 3.0

    # ---- 7. Ally count (scale 1.0, raw delta) ----
    signals['allies'] = (curr['allies'] - prev['allies']) * 1.0

    # ---- 8. Kills (scale 3.0) ----
    signals['kills'] = (curr['kills'] - prev['kills']) * 3.0

    # ---- 9. Exploration (scale 0.5) ----
    new_tiles = curr['tiles_explored'] - prev['tiles_explored']
    new_met = curr['creatures_met'] - prev['creatures_met']
    signals['exploration'] = new_tiles * 0.2 + new_met * 0.5

    # ---- 10. Piety (scale 2.0) ----
    signals['piety'] = 0.0
    if prev['piety'] > 0 or curr['piety'] > 0:
        signals['piety'] = _ln_ratio(curr['piety'] + 0.01,
                                     prev['piety'] + 0.01) * 2.0
    if curr['world_balance'] > 0:
        signals['piety'] += curr['world_balance'] * curr['piety'] * 0.5
    if prev['has_deity'] and not curr['has_deity']:
        signals['piety'] -= 2.0
    elif not prev['has_deity'] and curr['has_deity']:
        signals['piety'] += 1.0

    # ---- 11. Quest progress ----
    step_delta = curr['quest_steps'] - prev['quest_steps']
    quest_delta = curr['quests_completed'] - prev['quests_completed']
    signals['quests'] = step_delta * 5.0 + quest_delta * 10.0

    # ---- 12. Life goals (scale 2.0) ----
    signals['life_goals'] = (curr['life_goals'] - prev['life_goals']) * 2.0

    # ---- 13. XP activity (scale 0.05) ----
    signals['xp'] = 0.05 if curr['exp'] > prev['exp'] else 0.0

    # ---- PENALTIES ----
    fail_delta = curr['failed_actions'] - prev['failed_actions']
    signals['failed_actions'] = fail_delta * -0.5

    fatigue_delta = curr['fatigue'] - prev['fatigue']
    signals['fatigue'] = -fatigue_delta * 1.5 if fatigue_delta > 0 else 0.0

    nearby = curr.get('nearby_count', 0)
    signals['crowding'] = -(nearby - 4) * 0.3 if nearby >= 5 else 0.0

    # Goal progress: reward for moving closer to goal target
    if hasattr(creature, 'goal_target') and creature.goal_target is not None:
        progress = creature.goal_progress()
        signals['goal_progress'] = progress * 0.3  # small but consistent

        # At-goal bonus: performing aligned action at destination
        if creature.at_goal() and last_action is not None:
            from classes.actions import ACTION_PURPOSE
            action_purpose = ACTION_PURPOSE.get(last_action)
            if action_purpose and action_purpose == creature.current_goal:
                signals['goal_completed'] = 3.0

    total = sum(signals.values())

    # Purpose alignment: double reward when action matches tile purpose
    if last_action is not None and total > 0:
        from classes.actions import action_aligned_with_tile
        tile = creature.current_map.tiles.get(creature.location)
        zone_purposes = curr.get('zone_purposes')
        if tile and action_aligned_with_tile(last_action, tile, zone_purposes):
            signals['purpose_bonus'] = total
            total *= 2.0

    return (total, signals) if breakdown else total


def make_reward_snapshot(creature) -> dict:
    """Capture current state for reward computation."""
    stats = creature.stats
    hp_max = max(1, stats.active[Stat.HP_MAX]())
    stam_max = max(1, stats.active[Stat.MAX_STAMINA]())

    # Inventory + equipment value
    inv_value = sum(getattr(i, 'value', 0) for i in creature.inventory.items)
    eq_value = sum(getattr(i, 'value', 0) for i in set(creature.equipment.values()))

    # Reputation utility: sumproduct(sentiment, depth) / sum(depth)
    all_rels = list(creature.relationships.values())
    if all_rels:
        depths = [r[1] / (r[1] + 5) for r in all_rels]
        sents = [r[0] for r in all_rels]
        sum_depth = sum(depths)
        reputation = sum(s * d for s, d in zip(sents, depths)) / max(0.001, sum_depth)
    else:
        reputation = 0.0

    allies = sum(1 for r in all_rels if r[0] > 5)
    creatures_met = len(creature.relationships)

    # Debt
    debt = creature.total_debt(0) if hasattr(creature, 'total_debt') else 0
    disposable = creature.disposable_wealth(0) if hasattr(creature, 'disposable_wealth') else creature.gold

    # Piety + world balance
    piety = getattr(creature, 'piety', 0.0)
    deity = getattr(creature, 'deity', None)
    world_balance = 0.0
    if deity:
        from classes.gods import WorldData
        from classes.trackable import Trackable
        for obj in Trackable.all_instances():
            if isinstance(obj, WorldData):
                world_balance = obj.get_balance(deity)
                break

    # Nearby creature count (within 3 tiles) for crowding penalty
    nearby_count = 0
    try:
        from classes.world_object import WorldObject
        from classes.creature import Creature as _Creature
        for obj in WorldObject.on_map(creature.current_map):
            if isinstance(obj, _Creature) and obj is not creature and obj.is_alive:
                dx = abs(obj.location.x - creature.location.x)
                dy = abs(obj.location.y - creature.location.y)
                if dx + dy <= 3:
                    nearby_count += 1
    except Exception:
        pass

    # Zone purposes at current location
    zone_purposes = set()
    try:
        tile_purpose = None
        tile = creature.current_map.tiles.get(creature.location)
        if tile:
            tile_purpose = getattr(tile, 'purpose', None)
        if tile_purpose:
            zone_purposes.add(tile_purpose)
    except Exception:
        pass

    return {
        'alive': creature.is_alive,
        'hp_ratio': stats.active[Stat.HP_CURR]() / hp_max,
        'zone_purposes': zone_purposes,
        'gold': creature.gold,
        'debt': debt,
        'disposable': disposable,
        'inv_value': inv_value,
        'eq_kpi': 0,  # simplified — full KPI expensive
        'reputation': reputation,
        'allies': allies,
        'kills': getattr(creature, '_kills', 0),
        'tiles_explored': getattr(creature, '_tiles_explored', 0),
        'creatures_met': creatures_met,
        'piety': piety,
        'has_deity': deity is not None,
        'world_balance': world_balance,
        'quest_steps': getattr(creature, '_quest_steps_completed', 0),
        'quests_completed': getattr(creature, '_quests_completed', 0),
        'life_goals': getattr(creature, 'life_goal_attainment', 0),
        'exp': stats.base.get(Stat.EXP, 0),
        'failed_actions': getattr(creature, 'failed_actions', 0),
        'fatigue': getattr(creature, '_fatigue_level', 0),
        'nearby_count': nearby_count,
    }
