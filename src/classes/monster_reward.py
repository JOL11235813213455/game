"""
Monster reward function.

Dense per-tick reward for monsters. Simpler than creature reward (no
social/economic/piety signals), focused on predator essentials.

Signal keys (match curriculum signal_scales):
  m_hunger         : hunger recovery / starvation penalty
  m_hp             : HP delta (positive = healed, negative = hit)
  m_kills          : + per creature killed this tick
  m_damage_dealt   : + per damage point dealt (ln-scaled)
  m_chase          : + for attacking a fleeing creature
  m_eat            : + per meat item consumed (hunger_restored * scale)
  m_graze          : + per hunger restored by passive grazing
  m_territory_stay : + for being inside pack territory
  m_territory_hold : + per tick no other pack encroaches
  m_pack_cohesion  : + for pack members within cohesion range
  m_sleep_sync     : + when >= 80% of pack is resting together
  m_dominance_wins : + per challenge won this tick
  m_pair_success   : + per successful pairing
  m_reproduction   : + per egg laid
  m_egg_protect    : + per tick guarding eggs when threat nearby
  m_queen_kill_bonus : + when killing a fixed-dominance alpha (shared w/ creature side)
  m_failed_actions : - per failed action
  m_avoid_threat   : + when creature avoids monster territory (creature-side only)
  m_cannibal_penalty : - when a creature eats own-species meat (creature-side)
"""
from __future__ import annotations
from classes.stats import Stat


def make_monster_snapshot(monster) -> dict:
    """Snapshot monster state for next-tick reward delta computation."""
    hp_max = max(1, monster.stats.active[Stat.HP_MAX]())
    pack_size = monster.pack.size if monster.pack else 1
    return {
        'hp_ratio': monster.stats.active[Stat.HP_CURR]() / hp_max,
        'hunger': monster.hunger,
        'kills': monster._kills,
        'damage_dealt': monster._damage_dealt,
        'x': monster.location.x,
        'y': monster.location.y,
        'pack_size': pack_size,
        'rank': monster.rank,
        'dominance_wins': getattr(monster, '_dominance_wins', 0),
        'pair_successes': getattr(monster, '_pair_successes', 0),
        'eggs_laid': getattr(monster, '_eggs_laid', 0),
    }


def compute_monster_reward(monster, prev: dict, curr: dict,
                           action_result: dict = None,
                           breakdown: bool = False,
                           signal_scales: dict | None = None) -> float:
    """Compute per-tick monster reward.

    Args:
        monster: Monster instance
        prev: snapshot from previous tick
        curr: snapshot from this tick
        action_result: dict returned by dispatch_monster for THIS tick
            (provides chase / eat / graze / failure flags)
        breakdown: if True, return (total, {signal_name: contribution})
        signal_scales: {name: weight} from curriculum stage
    """
    import math
    scales = signal_scales or {}
    parts: dict[str, float] = {}
    ar = action_result or {}

    # HP delta
    hp_delta = curr.get('hp_ratio', 0) - prev.get('hp_ratio', 0)
    parts['m_hp'] = hp_delta * scales.get('m_hp', 0.5)

    # Hunger delta
    hunger_delta = curr.get('hunger', 0) - prev.get('hunger', 0)
    parts['m_hunger'] = hunger_delta * scales.get('m_hunger', 1.0)

    # Kills
    kill_delta = curr.get('kills', 0) - prev.get('kills', 0)
    parts['m_kills'] = kill_delta * scales.get('m_kills', 1.0)

    # Damage dealt — ln-scaled
    dmg_delta = curr.get('damage_dealt', 0) - prev.get('damage_dealt', 0)
    parts['m_damage_dealt'] = (
        math.log1p(max(0, dmg_delta)) / 5.0 * scales.get('m_damage_dealt', 0.5)
    )

    # Chase bonus: attacking a fleeing creature
    if ar.get('action') is not None:
        from classes.monster_actions import MonsterAction
        if ar.get('action') == int(MonsterAction.ATTACK):
            tgt = ar.get('target')
            if tgt is not None and getattr(tgt, '_is_fleeing', False):
                parts['m_chase'] = scales.get('m_chase', 0.7)
            # Queen kill bonus: target was a fixed-dominance alpha
            if kill_delta > 0 and _was_queen_kill(tgt):
                parts['m_queen_kill_bonus'] = scales.get(
                    'm_queen_kill_bonus', 2.0)

    # Eat action bonus
    hunger_restored = ar.get('hunger_restored', 0.0)
    if hunger_restored > 0 and ar.get('action') == 5:  # MonsterAction.EAT
        parts['m_eat'] = hunger_restored * scales.get('m_eat', 1.0)
    if hunger_restored > 0 and ar.get('action') == 10:  # HARVEST
        parts['m_graze'] = hunger_restored * scales.get('m_graze', 0.7)

    # Territory signals
    if monster.pack is not None:
        center = monster.pack.territory_center
        dx = curr.get('x', 0) - center.x
        dy = curr.get('y', 0) - center.y
        if math.sqrt(dx * dx + dy * dy) <= monster.pack.territory_radius():
            parts['m_territory_stay'] = scales.get('m_territory_stay', 0.3)

        # Territory hold: reward if no other hostile pack members visible
        if _pack_holding_territory(monster.pack):
            parts['m_territory_hold'] = scales.get('m_territory_hold', 0.3)

        # Cohesion: reward if this monster is within cohesion distance of pack centroid
        if _within_cohesion(monster):
            parts['m_pack_cohesion'] = scales.get('m_pack_cohesion', 0.3)

        # Sleep sync
        if _pack_sleeping_together(monster.pack):
            parts['m_sleep_sync'] = scales.get('m_sleep_sync', 0.5)

    # Dominance wins
    dom_delta = curr.get('dominance_wins', 0) - prev.get('dominance_wins', 0)
    if dom_delta > 0:
        parts['m_dominance_wins'] = dom_delta * scales.get('m_dominance_wins', 1.0)

    # Pair success
    pair_delta = curr.get('pair_successes', 0) - prev.get('pair_successes', 0)
    if pair_delta > 0:
        parts['m_pair_success'] = pair_delta * scales.get('m_pair_success', 1.0)

    # Reproduction (egg laid)
    egg_delta = curr.get('eggs_laid', 0) - prev.get('eggs_laid', 0)
    if egg_delta > 0:
        parts['m_reproduction'] = egg_delta * scales.get('m_reproduction', 1.0)

    # Egg protect: if monster's pack has eggs and monster is near them
    if _guarding_pack_eggs(monster):
        parts['m_egg_protect'] = scales.get('m_egg_protect', 0.7)

    # Failed action penalty
    if not ar.get('success', True) and ar.get('reason') not in ('', 'closing_distance'):
        parts['m_failed_actions'] = -scales.get('m_failed_actions', 0.3)

    total = sum(parts.values())
    if breakdown:
        return total, parts
    return total


def _was_queen_kill(target) -> bool:
    """True if the target was a fixed-dominance alpha (e.g. queen bee)."""
    from classes.monster import Monster
    if not isinstance(target, Monster):
        return False
    if not getattr(target, 'is_alpha', False):
        return False
    dom_type = getattr(target, 'dominance_type', 'contest')
    return dom_type == 'fixed'


def _pack_holding_territory(pack) -> bool:
    """True if no hostile foreign monsters are inside this pack's territory."""
    from classes.monster import Monster
    import math
    center = pack.territory_center
    radius = pack.territory_radius()
    for other in Monster._uid_registry.values():
        if other.pack is pack or not other.is_alive:
            continue
        dx = other.location.x - center.x
        dy = other.location.y - center.y
        if math.sqrt(dx * dx + dy * dy) <= radius:
            return False
    return True


def _within_cohesion(monster) -> bool:
    """True if this monster is within cohesion target distance of pack centroid."""
    import math
    pack = monster.pack
    if pack is None or pack.size < 2:
        return True
    xs = [m.location.x for m in pack.members]
    ys = [m.location.y for m in pack.members]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    d = math.sqrt((monster.location.x - cx) ** 2 +
                  (monster.location.y - cy) ** 2)
    # Cohesion target: when cohesion=1, target distance shrinks to 20% of territory
    effective = pack.effective_territory_size()
    return d <= effective


def _pack_sleeping_together(pack) -> bool:
    """True if 80%+ of pack members are resting (low stamina use, sleep signal high)."""
    if pack.size == 0:
        return False
    if pack.sleep_signal < 0.5:
        return False
    sleeping = sum(1 for m in pack.members
                   if getattr(m, '_pack_sleep_signal', 0) > 0.5)
    return sleeping / max(1, pack.size) >= 0.8


def _guarding_pack_eggs(monster) -> bool:
    """True if an egg is on the monster's current tile or adjacent tile."""
    from classes.inventory import Egg
    if monster.current_map is None:
        return False
    mx, my = monster.location.x, monster.location.y
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            from classes.maps import MapKey
            key = MapKey(mx + dx, my + dy, monster.location.z)
            tile = monster.current_map.tiles.get(key)
            if tile is None:
                continue
            for item in tile.inventory.items:
                if isinstance(item, Egg) and getattr(item, '_is_monster_egg', False):
                    return True
    return False
