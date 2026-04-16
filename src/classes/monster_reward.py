"""
Monster reward function.

Dense per-tick reward for monsters. Simpler than creature reward (no
social/economic/piety signals), focused on predator essentials:

  - m_hunger             : hunger recovery / starvation penalty
  - m_hp                 : HP delta (positive = healed, negative = hit)
  - m_kills              : + per creature killed this tick
  - m_damage_dealt       : + per damage point dealt to creatures
  - m_chase              : + for attacking a fleeing creature
  - m_eat                : + per meat item consumed
  - m_graze              : + per hunger restored by passive grazing
  - m_territory_stay     : + for being inside pack territory
  - m_territory_hold     : + per tick no other pack encroaches
  - m_pack_cohesion      : + for pack members staying within cohesion range
  - m_sleep_sync         : + when all pack members sleep together
  - m_dominance_wins     : + per challenge won
  - m_pair_success       : + per successful pairing
  - m_reproduction       : + per egg laid
  - m_egg_protect        : + per tick guarding eggs when threat nearby
  - m_queen_kill_bonus   : (shared with creature side)
  - m_failed_actions     : - per failed action (wall-bash, invalid attack)

Signal scales come from the curriculum stage's signal_scales JSON.
"""
from __future__ import annotations
from classes.stats import Stat


def make_monster_snapshot(monster) -> dict:
    """Snapshot monster state for next-tick reward delta computation."""
    hp_max = max(1, monster.stats.active[Stat.HP_MAX]())
    return {
        'hp_ratio': monster.stats.active[Stat.HP_CURR]() / hp_max,
        'hunger': monster.hunger,
        'kills': monster._kills,
        'damage_dealt': monster._damage_dealt,
        'x': monster.location.x,
        'y': monster.location.y,
    }


def compute_monster_reward(monster, prev: dict, curr: dict,
                           breakdown: bool = False,
                           last_action: int = None,
                           signal_scales: dict | None = None) -> float:
    """Compute the per-tick monster reward.

    Args:
        monster: Monster instance
        prev: snapshot from previous tick
        curr: snapshot from this tick
        breakdown: if True, return (total, {signal_name: contribution})
        last_action: MonsterAction enum int
        signal_scales: {name: weight} from curriculum stage

    Returns:
        float total reward, or (float, dict) if breakdown
    """
    scales = signal_scales or {}
    parts: dict[str, float] = {}

    # HP delta
    hp_delta = curr.get('hp_ratio', 0) - prev.get('hp_ratio', 0)
    parts['m_hp'] = hp_delta * scales.get('m_hp', 0.5)

    # Hunger delta (positive when ate, negative when starved)
    hunger_delta = curr.get('hunger', 0) - prev.get('hunger', 0)
    parts['m_hunger'] = hunger_delta * scales.get('m_hunger', 1.0)

    # Kills delta
    kill_delta = curr.get('kills', 0) - prev.get('kills', 0)
    parts['m_kills'] = kill_delta * scales.get('m_kills', 1.0)

    # Damage dealt
    dmg_delta = curr.get('damage_dealt', 0) - prev.get('damage_dealt', 0)
    parts['m_damage_dealt'] = min(1.0, dmg_delta / 20.0) * scales.get(
        'm_damage_dealt', 0.5)

    # Chase: if last_action was ATTACK and target was fleeing
    if last_action is not None:
        from classes.monster_actions import MonsterAction
        if last_action == int(MonsterAction.ATTACK):
            # Chase bonus applies if any visible creature was fleeing
            # (simplified — runtime dispatcher can be more precise)
            parts['m_chase'] = scales.get('m_chase', 0.7)

    # Territory stay
    if monster.pack is not None:
        import math
        center = monster.pack.territory_center
        dx = curr.get('x', 0) - center.x
        dy = curr.get('y', 0) - center.y
        if math.sqrt(dx * dx + dy * dy) <= monster.pack.territory_radius():
            parts['m_territory_stay'] = scales.get('m_territory_stay', 0.3)

    # Eat signal: covered by hunger_delta when positive. Explicit m_eat
    # can be triggered by the dispatcher on EAT action success.

    total = sum(parts.values())
    if breakdown:
        return total, parts
    return total
