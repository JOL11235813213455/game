"""
Heuristic monster and pack policies.

Used for imitation learning priors before RL training starts, and as
a fallback when MonsterNet/PackNet aren't loaded. Priority-cascade
logic designed to reproduce common-sense predator/herd behavior.

These policies won't be optimal — they're intentionally simple so the
NN can improve on them. The goal is to get agents past the
random-exploration phase of RL immediately.
"""
from __future__ import annotations
from classes.stats import Stat
from classes.monster_actions import MonsterAction


def heuristic_monster_action(monster) -> int:
    """Priority-cascade heuristic for a monster's next action.

    Returns an int from the MonsterAction enum. Caller is responsible
    for ensuring the returned action is in the computed action mask —
    heuristic aligns with the INT+diet gates by construction.
    """
    hp_max = max(1, monster.stats.active[Stat.HP_MAX]())
    hp_ratio = monster.stats.active[Stat.HP_CURR]() / hp_max
    cur_stam = monster.stats.active[Stat.CUR_STAMINA]()
    int_score = monster.stats.base.get(Stat.INT, 10)

    # Find nearest visible threat/prey via monster's map
    from classes.creature import Creature
    nearest_creature = None
    nearest_dist = 9999
    if monster.current_map is not None:
        sight = max(1, monster.stats.active[Stat.SIGHT_RANGE]())
        mx, my = monster.location.x, monster.location.y
        for c in Creature.on_same_map(monster.current_map):
            if not c.is_alive:
                continue
            d = abs(c.location.x - mx) + abs(c.location.y - my)
            if d <= sight and d < nearest_dist:
                nearest_dist = d
                nearest_creature = c

    # 1. HP critical → FLEE (if stamina allows)
    if hp_ratio < 0.3 and nearest_creature is not None and cur_stam >= 1:
        return int(MonsterAction.FLEE)

    # 2. Hungry + prey adjacent → ATTACK
    if nearest_creature is not None and nearest_dist <= 1 and cur_stam >= 3:
        return int(MonsterAction.ATTACK)

    # 3. Hungry + prey fleeing → ATTACK (chase instinct)
    if (monster.hunger < 0.3 and nearest_creature is not None and
            getattr(nearest_creature, '_is_fleeing', False) and cur_stam >= 3):
        return int(MonsterAction.ATTACK)

    # 4. Pack signal overrides
    if monster._pack_sleep_signal > 0.7:
        if int_score >= 4:
            return int(MonsterAction.REST)
        # Low-INT species can only MOVE; REST is gated away by mask
        return int(MonsterAction.MOVE)

    if monster._pack_role == 'guard_eggs' and int_score >= 4:
        return int(MonsterAction.PROTECT_EGG)

    # 5. Alert level high + prey visible → ATTACK/chase
    if monster._pack_alert_level > 0.6 and nearest_creature is not None:
        if cur_stam >= 3:
            return int(MonsterAction.ATTACK)
        return int(MonsterAction.MOVE)

    # 6. Low INT: pure reactive (move toward pack target)
    if int_score <= 3:
        return int(MonsterAction.MOVE)

    # 7. Grazing opportunity: on a compatible tile
    if (monster.diet in ('herbivore', 'omnivore') and
            int_score >= 4 and monster._can_graze()):
        return int(MonsterAction.HARVEST)

    # 8. Hungry + on tile with meat: EAT
    if monster.hunger < 0.5 and monster.current_map is not None:
        tile = monster.current_map.tiles.get(monster.location)
        if tile is not None:
            from classes.inventory import Meat
            has_meat = any(isinstance(i, Meat) for i in tile.inventory.items)
            if has_meat and int_score >= 4:
                return int(MonsterAction.EAT)

    # 9. Mid INT + full hunger + calm pack → PATROL
    if int_score >= 4 and monster.hunger > 0.5 and monster._pack_alert_level < 0.3:
        return int(MonsterAction.PATROL)

    # 10. Default: MOVE (toward pack target position)
    return int(MonsterAction.MOVE)


def heuristic_pack_outputs(pack, game_clock=None) -> tuple:
    """Heuristic pack coordination outputs.

    Returns (sleep_signal, alert_level, cohesion, role_fractions_dict).
    """
    members = pack.members
    if not members:
        return 0.0, 0.0, 0.5, {'patrol': 1.0, 'attack': 0.0, 'guard_eggs': 0.0}

    # Active period (nocturnal XOR is_day)
    species_active = pack.species_config.get('active_hours', 'diurnal')
    is_day = bool(getattr(game_clock, 'is_day', True)) if game_clock else True
    if species_active == 'nocturnal':
        active = not is_day
    elif species_active == 'crepuscular':
        sun_elev = getattr(game_clock, 'sun_elevation', 0.5) if game_clock else 0.5
        active = 0.1 < sun_elev < 0.4
    else:
        active = is_day

    # Max fatigue across pack
    max_fatigue = max(max(0.0, -m.hunger) for m in members)

    # Sleep when inactive period AND fatigue is high
    sleep_signal = 1.0 if (not active and max_fatigue > 0.5) else 0.0

    # Alert: scales with visible creature count
    visible = len(pack.seen_creatures)
    alert_level = min(1.0, visible / 3.0)

    # Cohesion: tighter when alert
    cohesion = alert_level * 0.8

    # Role distribution
    # Simplified: if alert, mostly attack; if calm, mostly patrol.
    # guard_eggs slice activates when eggs present (future hook).
    if alert_level > 0.5:
        roles = {'patrol': 0.1, 'attack': 0.8, 'guard_eggs': 0.1}
    elif alert_level > 0.1:
        roles = {'patrol': 0.5, 'attack': 0.4, 'guard_eggs': 0.1}
    else:
        roles = {'patrol': 0.9, 'attack': 0.0, 'guard_eggs': 0.1}

    return sleep_signal, alert_level, cohesion, roles
