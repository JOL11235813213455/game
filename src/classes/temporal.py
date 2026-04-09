"""
Temporal transform system for creature observation history.

Takes a ring buffer of snapshots and generates rich temporal features:
  - ln(t/t-N) for various lookback windows
  - Volatility (stdev over window)
  - Range (max-min over window)
  - Direction (sign of change)
  - Streak (consecutive ticks in same direction)
  - Time since events

Each tracked variable × each transform × each window = one float.
"""
from __future__ import annotations
import math
from collections import deque


# Variables tracked in each snapshot
TRACKED_VARS = [
    'hp_ratio', 'stam_ratio', 'mana_ratio',
    'gold', 'debt', 'inv_value',
    'reputation', 'allies', 'enemies',
    'closest_enemy_dist', 'closest_ally_dist',
    'piety', 'kills', 'eq_kpi',
    'fatigue',
]

# Time windows for lookback
WINDOWS = [1, 5, 10, 50, 100]

# Event types for time-since tracking
EVENT_TYPES = [
    'combat', 'hit_taken', 'kill', 'social', 'trade', 'sleep',
    'consume', 'quest_step', 'pairing', 'level_up', 'moved',
    'failed_action', 'spell_cast', 'flee', 'loaned', 'repaid',
]


def make_history_snapshot(creature, visible_enemies=None,
                          visible_allies=None) -> dict:
    """Capture a snapshot for the history buffer.

    Lighter than the full reward snapshot — only tracked variables.
    """
    from classes.stats import Stat
    stats = creature.stats
    hp_max = max(1, stats.active[Stat.HP_MAX]())
    stam_max = max(1, stats.active[Stat.MAX_STAMINA]())
    mana_max = max(1, stats.active[Stat.MAX_MANA]())

    # Reputation utility
    all_rels = list(creature.relationships.values())
    if all_rels:
        depths = [r[1] / (r[1] + 5) for r in all_rels]
        sents = [r[0] for r in all_rels]
        sum_depth = sum(depths)
        reputation = sum(s * d for s, d in zip(sents, depths)) / max(0.001, sum_depth)
    else:
        reputation = 0.0

    allies = sum(1 for r in all_rels if r[0] > 5)
    enemies = sum(1 for r in all_rels if r[0] < -5)

    closest_enemy = 999
    if visible_enemies:
        closest_enemy = min(d for d, _ in visible_enemies)
    closest_ally = 999
    if visible_allies:
        closest_ally = min(d for d, _ in visible_allies)

    return {
        'hp_ratio': stats.active[Stat.HP_CURR]() / hp_max,
        'stam_ratio': stats.active[Stat.CUR_STAMINA]() / stam_max,
        'mana_ratio': stats.active[Stat.CUR_MANA]() / mana_max,
        'gold': creature.gold,
        'debt': creature.total_debt(0) if hasattr(creature, 'total_debt') else 0,
        'inv_value': sum(getattr(i, 'value', 0) for i in creature.inventory.items),
        'reputation': reputation,
        'allies': allies,
        'enemies': enemies,
        'closest_enemy_dist': closest_enemy,
        'closest_ally_dist': closest_ally,
        'piety': getattr(creature, 'piety', 0.0),
        'kills': getattr(creature, '_kills', 0),
        'eq_kpi': 0,  # simplified
        'fatigue': getattr(creature, '_fatigue_level', 0),
    }


def _safe_ln_ratio(current, past):
    """ln(current / past) with safety."""
    c = max(0.001, abs(current) + 0.001)
    p = max(0.001, abs(past) + 0.001)
    return math.log(c / p)


def _stdev(values):
    """Standard deviation of a list."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(var)


def _streak(values):
    """Count consecutive same-sign changes from the end."""
    if len(values) < 2:
        return 0
    count = 0
    last_sign = None
    for i in range(len(values) - 1, 0, -1):
        delta = values[i] - values[i - 1]
        sign = 1 if delta > 0 else (-1 if delta < 0 else 0)
        if sign == 0:
            continue
        if last_sign is None:
            last_sign = sign
            count = 1
        elif sign == last_sign:
            count += 1
        else:
            break
    return count * (last_sign or 0)


def generate_temporal_transforms(history: deque, current: dict) -> list[float]:
    """Generate all temporal transform features from history buffer.

    Returns a flat list of floats.

    For each tracked variable × each window:
      - ln(current / past)      change magnitude
      - sign of change          direction (+1, 0, -1)
      - stdev over window       volatility

    For key variables only (HP, stamina, gold, reputation, enemy dist):
      - range over window       max - min
      - streak                  consecutive same-direction ticks

    Total: ~15 vars × 5 windows × 3 base transforms = 225
           + 5 key vars × 5 windows × 2 extra transforms = 50
           = ~275 temporal features
    """
    obs = []
    hist_list = list(history)
    n = len(hist_list)

    # Key variables get extra transforms
    key_vars = {'hp_ratio', 'stam_ratio', 'gold', 'reputation', 'closest_enemy_dist'}

    for var in TRACKED_VARS:
        cur_val = current.get(var, 0)
        var_history = [h.get(var, 0) for h in hist_list]

        for window in WINDOWS:
            if n >= window and window > 0:
                past_val = hist_list[-window].get(var, 0)
                window_vals = [h.get(var, 0) for h in hist_list[-window:]]
            else:
                past_val = cur_val
                window_vals = [cur_val]

            # ln ratio: change magnitude
            obs.append(_safe_ln_ratio(cur_val, past_val))

            # Sign of change
            delta = cur_val - past_val
            obs.append(1.0 if delta > 0 else (-1.0 if delta < 0 else 0.0))

            # Volatility (stdev)
            obs.append(min(5.0, _stdev(window_vals)))

            # Extra transforms for key variables
            if var in key_vars:
                # Range
                if window_vals:
                    obs.append(max(window_vals) - min(window_vals))
                else:
                    obs.append(0.0)
                # Streak
                obs.append(_streak(var_history[-window:]) / max(1, window))

    return obs


def record_event(creature, event_name: str, tick: int):
    """Record that an event happened at this tick."""
    creature._event_ticks[event_name] = tick


def generate_time_since(creature, current_tick: int) -> list[float]:
    """Generate time-since-event features.

    Returns one float per event type: ticks since last occurrence, normalized.
    """
    obs = []
    for event in EVENT_TYPES:
        last = creature._event_ticks.get(event, 0)
        elapsed = current_tick - last
        # Normalize: fast events /100, slow events /1000
        if event in ('pairing', 'level_up'):
            obs.append(min(10.0, elapsed / 1000.0))
        else:
            obs.append(min(10.0, elapsed / 100.0))
    return obs


# Size constants for observation integration
TEMPORAL_TRANSFORMS_SIZE = len(TRACKED_VARS) * len(WINDOWS) * 3 + 5 * len(WINDOWS) * 2
TIME_SINCE_SIZE = len(EVENT_TYPES)
TOTAL_TEMPORAL_SIZE = TEMPORAL_TRANSFORMS_SIZE + TIME_SINCE_SIZE
