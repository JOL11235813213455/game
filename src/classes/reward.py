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
from classes.relationship_graph import GRAPH


def _ln_ratio(after: float, before: float, epsilon: float = 0.001) -> float:
    """ln(after / before) with safety for zero/negative."""
    return math.log(max(epsilon, after) / max(epsilon, before))


def _sln(x: float) -> float:
    """Signed ln: sign(x) * ln(|x| + 1)."""
    if x == 0:
        return 0.0
    return math.copysign(math.log(abs(x) + 1), x)


def _current_tile_liquid(creature) -> bool:
    """Return True if the creature is standing on a liquid tile."""
    try:
        tile = creature.current_map.tiles.get(creature.location)
        return bool(tile and getattr(tile, 'liquid', False))
    except Exception:
        return False


def _current_tile_deep_water(creature) -> bool:
    """Return True if standing on liquid with depth >= 1 (drowning danger)."""
    try:
        tile = creature.current_map.tiles.get(creature.location)
        return bool(tile and getattr(tile, 'liquid', False)
                     and getattr(tile, 'depth', 0) >= 1)
    except Exception:
        return False


def _nearest_deep_water(creature) -> float:
    """Normalized distance to nearest deep water tile within sight.

    Returns 1.0 if no deep water visible. Only counts tiles with
    depth >= 1 (not shallow banks).
    """
    try:
        sight = max(1, creature.stats.active[Stat.SIGHT_RANGE]())
        cx, cy = creature.location.x, creature.location.y
        z = creature.location.z
        game_map = creature.current_map
        from classes.maps import MapKey as _MK
        best = None
        for dx in range(-sight, sight + 1):
            adx = abs(dx)
            for dy in range(-sight, sight + 1):
                d = adx + abs(dy)
                if d > sight:
                    continue
                t = game_map.tiles.get(_MK(cx + dx, cy + dy, z))
                if (t and getattr(t, 'liquid', False)
                        and getattr(t, 'depth', 0) >= 1):
                    if best is None or d < best:
                        best = d
        return best / sight if best is not None else 1.0
    except Exception:
        return 1.0


def _resolve_action_purpose(creature, action: int) -> str | None:
    """Return the purpose string an action should count toward *right now*.

    Most actions map statically via ACTION_PURPOSE. Two are polymorphic:

      * ``HARVEST`` — aligned to the current tile's ``purpose`` (so
        harvesting fish on a ``fishing`` tile pays the fishing reward,
        berries on a ``gathering`` tile pays gathering, etc.).
      * ``JOB`` — aligned to the creature's assigned job purpose.

    Falls back to the static ACTION_PURPOSE entry when the polymorphic
    context is missing.
    """
    from classes.actions import Action, ACTION_PURPOSE
    if action == Action.JOB:
        job = getattr(creature, 'job', None)
        if job is not None:
            return job.purpose
        return None
    if action == Action.HARVEST:
        tile = creature.current_map.tiles.get(creature.location) if creature.current_map else None
        if tile is not None and getattr(tile, 'purpose', None):
            return tile.purpose
        # fall through to static default
    return ACTION_PURPOSE.get(action)


def compute_reward(creature, prev: dict, curr: dict,
                   breakdown: bool = False,
                   last_action: int = None,
                   signal_scales: dict = None) -> float | tuple[float, dict]:
    """Compute reward for a single step.

    Args:
        creature: the Creature being evaluated
        prev: previous snapshot from make_reward_snapshot()
        curr: current snapshot from make_reward_snapshot()
        breakdown: if True, also return per-signal dict
        last_action: action just performed (for purpose alignment bonus)
        signal_scales: optional dict mapping signal name -> scale factor.
            When provided, every computed signal is multiplied by its
            scale BEFORE summing. Signals with no entry default to 0.0
            (silenced). When None, every signal uses its hardcoded
            default weight (legacy behavior). Used by the curriculum
            runner to mask reward components per training stage.

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

    # Social success: immediate reward for successful social actions
    social_delta = curr.get('social_wins', 0) - prev.get('social_wins', 0)
    if social_delta > 0:
        signals['social_success'] = social_delta * 0.5

    # ---- 8. Kills (scale 3.0) ----
    signals['kills'] = (curr['kills'] - prev['kills']) * 3.0

    # Damage dealt: reward proportional to HP reduced on others
    dmg_delta = curr.get('damage_dealt', 0) - prev.get('damage_dealt', 0)
    if dmg_delta > 0:
        signals['damage_dealt'] = math.log(1 + dmg_delta) * 1.0

    # ---- 9. Exploration (scale 0.5) ----
    new_tiles = curr['tiles_explored'] - prev['tiles_explored']
    new_met = curr['creatures_met'] - prev['creatures_met']
    signals['exploration'] = new_tiles * 0.2 + new_met * 0.5

    # ---- 9b. Pickup success ----
    pickup_delta = curr.get('pickups', 0) - prev.get('pickups', 0)
    if pickup_delta > 0:
        signals['pickup_success'] = pickup_delta * 0.3

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

    # Sleep quality: positive reward when sleep reduces fatigue
    prev_fatigue = prev.get('fatigue', 0)
    curr_fatigue = curr.get('fatigue', 0)
    if curr_fatigue < prev_fatigue:
        signals['sleep_quality'] = (prev_fatigue - curr_fatigue) * 1.0

    nearby = curr.get('nearby_count', 0)
    signals['crowding'] = -(nearby - 4) * 0.3 if nearby >= 5 else 0.0

    # Idleness: small penalty for WAITing at full stamina
    if (last_action is not None and last_action == 23  # WAIT
            and curr.get('stamina_ratio', 1.0) > 0.9):
        signals['idleness'] = -0.05

    # Water danger: penalty only for DEEP water (depth >= 1) without
    # swimming. Shallow banks (depth=0, liquid=True) are safe — the
    # creature can fish there. The proximity warning only fires for
    # deep water, not banks.
    in_deep = curr.get('in_deep_water', False)
    if in_deep and not curr.get('can_swim', False):
        signals['water_danger'] = -3.0
    elif (curr.get('nearest_deep_water_dist', 1.0) < 0.3
          and not curr.get('can_swim', False)):
        proximity = 1.0 - curr.get('nearest_deep_water_dist', 1.0)
        signals['water_danger'] = -proximity * 1.0

    # Wage earned since last tick — rewards consistent job execution.
    wage_delta = curr.get('wage_accumulated', 0.0) - prev.get('wage_accumulated', 0.0)
    if wage_delta > 0:
        signals['wage'] = math.log(1 + wage_delta) * 0.5

    # Trade surplus earned since last tick — uses the bargaining surplus
    # from compute_trade_price (buyer_surplus or seller_surplus), not the
    # raw gold delta. trade_reward scales it by wealth so small surpluses
    # matter more to poor creatures than rich ones.
    from classes.valuation import trade_reward
    surplus_delta = (curr.get('trade_surplus', 0.0)
                     - prev.get('trade_surplus', 0.0))
    if surplus_delta > 0:
        wealth = max(1.0, float(curr.get('gold', 0)) + curr.get('inv_value', 0.0))
        signals['trade'] = trade_reward(surplus_delta, wealth)

    # Hunger: satiated = positive, hungry = negative (logarithmic)
    hunger = curr.get('hunger', 0.0)
    prev_hunger = prev.get('hunger', 0.0)
    if hunger > 0.5:
        # Well-fed: small positive proportional to fullness
        signals['hunger'] = (hunger - 0.5) * 0.5
    elif hunger < 0.0:
        # Hungry: logarithmically increasing penalty
        signals['hunger'] = -math.log(1 + abs(hunger) * 3) * 1.5
    else:
        signals['hunger'] = 0.0
    # Bonus for eating (hunger increased this tick)
    if hunger > prev_hunger + 0.05:
        signals['hunger'] += 1.0  # ate something — reward

    # Goal progress: reward for moving closer to goal target
    if hasattr(creature, 'goal_target') and creature.goal_target is not None:
        progress = creature.goal_progress()
        signals['goal_progress'] = progress * 0.3  # small but consistent

        # At-goal bonus: performing aligned action at destination
        if creature.at_goal() and last_action is not None:
            action_purpose = _resolve_action_purpose(creature, last_action)
            if action_purpose and action_purpose == creature.current_goal:
                signals['goal_completed'] = 3.0

    # Apply curriculum signal mask: scale (or silence) individual signals
    # before summing. Signals without an entry are silenced (multiplied
    # by 0). When signal_scales is None, all signals pass through
    # unchanged (legacy behavior).
    if signal_scales is not None:
        for k in list(signals.keys()):
            signals[k] = signals[k] * signal_scales.get(k, 0.0)

    total = sum(signals.values())

    # Purpose proximity: reward scales with distance to visible purpose tile
    # On the tile: reward^2. In sight: reward^(1+1/d). Out of sight: -0.25
    # Also masked by signal_scales['purpose_proximity'] when curriculum
    # masking is active.
    pp_scale = (signal_scales.get('purpose_proximity', 0.0)
                if signal_scales is not None else 1.0)
    if last_action is not None and total != 0 and pp_scale > 0:
        action_purpose = _resolve_action_purpose(creature, last_action)
        if action_purpose:
            dist_to_purpose = curr.get('dist_to_purpose', {}).get(action_purpose)
            if dist_to_purpose is not None:
                # Visible — boost reward based on proximity
                d = max(1, dist_to_purpose)
                exponent = 1 + 1.0 / d
                if total > 0:
                    boosted = total ** exponent
                    delta = (boosted - total) * pp_scale
                    signals['purpose_proximity'] = delta
                    total += delta
                else:
                    # Negative reward — reduce penalty when near purpose tile
                    delta = abs(total) * (1.0 / d) * 0.5 * pp_scale
                    signals['purpose_proximity'] = delta
                    total += delta
            else:
                # No matching purpose tile visible — slight penalty
                delta = -0.25 * pp_scale
                signals['purpose_proximity'] = delta
                total += delta

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
    all_rels = list(GRAPH.edges_from(creature.uid).values())
    if all_rels:
        depths = [r[1] / (r[1] + 5) for r in all_rels]
        sents = [r[0] for r in all_rels]
        sum_depth = sum(depths)
        reputation = sum(s * d for s, d in zip(sents, depths)) / max(0.001, sum_depth)
    else:
        reputation = 0.0

    allies = sum(1 for r in all_rels if r[0] > 5)
    creatures_met = GRAPH.count_from(creature.uid)

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

    # Distance to nearest visible purpose source (tiles + objects)
    dist_to_purpose = {}
    try:
        sight = max(1, stats.active[Stat.SIGHT_RANGE]())
        cx, cy = creature.location.x, creature.location.y
        game_map = creature.current_map
        # Scan visible tiles for purpose
        from classes.maps import MapKey as _MK
        for dx in range(-sight, sight + 1):
            for dy in range(-sight, sight + 1):
                if abs(dx) + abs(dy) > sight:
                    continue
                t = game_map.tiles.get(_MK(cx + dx, cy + dy, creature.location.z))
                if t and getattr(t, 'purpose', None):
                    d = abs(dx) + abs(dy)
                    p = t.purpose
                    if p not in dist_to_purpose or d < dist_to_purpose[p]:
                        dist_to_purpose[p] = d
        # Scan visible objects (structures, creatures, items) with purpose
        from classes.world_object import WorldObject as _WO
        for obj in _WO.on_map(game_map):
            if obj is creature or not getattr(obj, 'purpose', None):
                continue
            d = abs(cx - obj.location.x) + abs(cy - obj.location.y)
            max_range = sight * getattr(obj, 'purpose_distance', 0.5)
            if d <= max_range:
                p = obj.purpose
                if p not in dist_to_purpose or d < dist_to_purpose[p]:
                    dist_to_purpose[p] = d
    except Exception:
        pass

    return {
        'alive': creature.is_alive,
        'hp_ratio': stats.active[Stat.HP_CURR]() / hp_max,
        'dist_to_purpose': dist_to_purpose,
        'gold': creature.gold,
        'debt': debt,
        'disposable': disposable,
        'inv_value': inv_value,
        'eq_kpi': eq_value,  # sum of equipment values (cheap proxy for full KPI)
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
        'hunger': getattr(creature, 'hunger', 0.0),
        'in_liquid': _current_tile_liquid(creature),
        'in_deep_water': _current_tile_deep_water(creature),
        'can_swim': getattr(creature, 'can_swim', False),
        'nearest_water_dist': 1.0,
        'nearest_deep_water_dist': _nearest_deep_water(creature),
        'nearby_count': nearby_count,
        'wage_accumulated': getattr(creature, '_wage_accumulated', 0.0),
        'trade_surplus': getattr(creature, '_trade_surplus_accumulated', 0.0),
        'gold': getattr(creature, 'gold', 0),
        'social_wins': getattr(creature, '_social_wins', 0),
        'damage_dealt': getattr(creature, '_damage_dealt', 0),
        'pickups': getattr(creature, '_pickups', 0),
        'stamina_ratio': stats.active[Stat.CUR_STAMINA]() / stam_max,
    }
