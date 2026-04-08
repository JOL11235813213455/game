"""
Reward function for the creature RL system.

Hierarchical reward structure:
  1. Survival (highest priority): alive/dead, HP preservation
  2. Resources: HP recovery, gold/item acquisition, ally count
  3. Proxy rewards: curiosity (INT-scaled), social success, combat victory
  4. Penalties: betrayal, getting caught stealing, fatigue

All rewards are computed as deltas between two snapshots.
"""
from __future__ import annotations
from classes.stats import Stat


def compute_reward(creature, prev: dict, curr: dict) -> float:
    """Compute reward for a single step.

    Args:
        creature: the Creature being evaluated
        prev: previous snapshot from make_reward_snapshot()
        curr: current snapshot from make_reward_snapshot()

    Returns:
        float reward value
    """
    reward = 0.0

    # ---- 1. Survival (highest weight) ----
    if curr['alive'] and not prev['alive']:
        # Shouldn't happen (resurrection), but reward it
        reward += 10.0
    elif not curr['alive'] and prev['alive']:
        # Death = massive penalty
        reward -= 20.0
        return reward  # No other rewards matter if dead

    if not curr['alive']:
        return -1.0  # Ongoing death penalty per tick

    # ---- 2. HP preservation ----
    hp_delta = curr['hp_ratio'] - prev['hp_ratio']
    if hp_delta > 0:
        reward += hp_delta * 5.0   # healing is good
    elif hp_delta < 0:
        reward += hp_delta * 8.0   # taking damage is worse than healing is good

    # ---- 3. Resources ----
    # Stamina management (don't let it hit 0)
    if curr['stam_ratio'] < 0.1 and prev['stam_ratio'] >= 0.1:
        reward -= 1.0  # stamina critically low
    if curr['stam_ratio'] > 0.5 and prev['stam_ratio'] <= 0.5:
        reward += 0.3  # stamina recovery

    # Item acquisition (inventory value change)
    value_delta = curr['inventory_value'] - prev['inventory_value']
    if value_delta > 0:
        reward += min(2.0, value_delta * 0.1)  # capped gain
    elif value_delta < 0:
        reward += max(-1.0, value_delta * 0.05)  # smaller penalty for loss

    # ---- 4. Social ----
    # Net relationship improvement
    rel_delta = curr['total_sentiment'] - prev['total_sentiment']
    reward += rel_delta * 0.1  # small weight, accumulates

    # Ally count change
    ally_delta = curr['ally_count'] - prev['ally_count']
    reward += ally_delta * 1.0

    # ---- 5. Curiosity (INT-scaled) ----
    # New creatures met (curiosity reward)
    new_met = curr['creatures_met'] - prev['creatures_met']
    if new_met > 0:
        int_mod = (creature.stats.active[Stat.INT]() - 10) // 2
        curiosity_weight = max(0.1, 0.5 + int_mod * 0.15)
        reward += new_met * curiosity_weight

    # New tiles explored
    new_tiles = curr['tiles_explored'] - prev['tiles_explored']
    if new_tiles > 0:
        int_mod = (creature.stats.active[Stat.INT]() - 10) // 2
        explore_weight = max(0.05, 0.2 + int_mod * 0.05)
        reward += new_tiles * explore_weight

    # ---- 6. Combat ----
    kills = curr['kills'] - prev['kills']
    reward += kills * 3.0

    # ---- 7. Piety ----
    # Piety reinforcement: acting in alignment with your god feels right
    piety_delta = curr['piety'] - prev['piety']
    if piety_delta > 0:
        reward += piety_delta * 5.0  # gaining piety = positive
    elif piety_delta < 0:
        reward += piety_delta * 3.0  # losing piety = mild negative

    # World alignment bonus: if the world leans toward your god, feel outgoing
    if curr['world_balance'] > 0:
        reward += curr['world_balance'] * creature.piety * 0.5

    # ---- 8. Penalties ----
    # Fatigue increase
    fatigue_delta = curr['fatigue'] - prev['fatigue']
    if fatigue_delta > 0:
        reward -= fatigue_delta * 1.5

    return reward


def make_reward_snapshot(creature) -> dict:
    """Capture current state for reward computation.

    Called at the start of each step. The delta between two snapshots
    drives the reward function.
    """
    stats = creature.stats
    hp_max = stats.active[Stat.HP_MAX]()
    stam_max = stats.active[Stat.MAX_STAMINA]()

    # Total inventory value
    inv_value = sum(getattr(i, 'value', 0) for i in creature.inventory.items)
    # Include equipped items
    inv_value += sum(getattr(i, 'value', 0) for i in set(creature.equipment.values()))

    # Total sentiment across all relationships
    total_sentiment = sum(r[0] for r in creature.relationships.values())

    # Ally count (positive sentiment)
    ally_count = sum(1 for r in creature.relationships.values() if r[0] > 5)

    # Creatures met (unique relationship count)
    creatures_met = len(creature.relationships)

    # Piety and world balance
    piety = getattr(creature, 'piety', 0.0)
    world_balance = 0.0
    deity = getattr(creature, 'deity', None)
    if deity:
        from classes.gods import WorldData
        from classes.trackable import Trackable
        for obj in Trackable.all_instances():
            if isinstance(obj, WorldData):
                world_balance = obj.get_balance(deity)
                break

    return {
        'alive': creature.is_alive,
        'hp_ratio': stats.active[Stat.HP_CURR]() / max(1, hp_max),
        'stam_ratio': stats.active[Stat.CUR_STAMINA]() / max(1, stam_max),
        'inventory_value': inv_value,
        'total_sentiment': total_sentiment,
        'ally_count': ally_count,
        'creatures_met': creatures_met,
        'tiles_explored': getattr(creature, '_tiles_explored', 0),
        'kills': getattr(creature, '_kills', 0),
        'fatigue': getattr(creature, '_fatigue_level', 0),
        'piety': piety,
        'world_balance': world_balance,
    }
