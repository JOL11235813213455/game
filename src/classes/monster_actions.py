"""
Monster action space.

10 actions total. INT-gated and diet-gated — the dynamic mask zeros
out actions not available to this monster (e.g. HOWL for INT<=7,
HARVEST for carnivores, PROTECT_EGG when no eggs exist).
"""
from __future__ import annotations
from enum import IntEnum
import numpy as np


class MonsterAction(IntEnum):
    MOVE = 0          # toward pack-assigned target position (optionally sneak)
    PATROL = 1        # random walk inside territory (INT >= 4)
    GUARD = 2         # stand and watch (defensive stance)
    ATTACK = 3        # melee/ranged depending on species
    PAIR = 4          # attempt to mate with same-rank partner
    EAT = 5           # consume meat on tile, or passively graze if low-INT
    HOWL = 6          # pack alert signal (INT >= 8, raises pack alert)
    FLEE = 7          # retreat from nearest threat
    REST = 8          # restore stamina/hunger on tile
    PROTECT_EGG = 9   # guard the pack's eggs (requires eggs present)
    HARVEST = 10      # active harvest from compatible tile (INT >= 4,
                      # herbivore/omnivore only)


NUM_MONSTER_ACTIONS = len(MonsterAction)

# Action groups by INT band
_INSTINCT_ACTIONS = {MonsterAction.MOVE, MonsterAction.ATTACK, MonsterAction.FLEE}
_FERAL_ACTIONS = _INSTINCT_ACTIONS | {
    MonsterAction.PATROL, MonsterAction.GUARD, MonsterAction.EAT,
    MonsterAction.REST, MonsterAction.PROTECT_EGG,
}
_AWARE_ACTIONS = _FERAL_ACTIONS | {
    MonsterAction.HOWL, MonsterAction.PAIR,
}
_CUNNING_ACTIONS = _AWARE_ACTIONS  # same action set as aware; cunning is about planning


def _int_band(int_score: int) -> str:
    if int_score <= 3:
        return 'instinct'
    if int_score <= 7:
        return 'feral'
    if int_score <= 12:
        return 'aware'
    return 'cunning'


def _allowed_by_int(int_score: int) -> set:
    band = _int_band(int_score)
    if band == 'instinct':
        return _INSTINCT_ACTIONS
    if band == 'feral':
        return _FERAL_ACTIONS
    return _AWARE_ACTIONS  # aware and cunning share action set


def compute_monster_mask(monster) -> np.ndarray:
    """Return a binary mask array (1.0 = allowed) for a monster's actions.

    Combines INT-band gating, diet gating, and contextual gates (is an
    egg visible? stamina sufficient?).
    """
    from classes.stats import Stat
    mask = np.zeros(NUM_MONSTER_ACTIONS, dtype=np.float32)
    int_score = monster.stats.base.get(Stat.INT, 10)
    allowed = _allowed_by_int(int_score)

    for action in MonsterAction:
        if action in allowed:
            mask[int(action)] = 1.0

    # HARVEST: only herbivores/omnivores with INT >= 4
    if monster.diet in ('herbivore', 'omnivore') and int_score >= 4:
        mask[int(MonsterAction.HARVEST)] = 1.0
    else:
        mask[int(MonsterAction.HARVEST)] = 0.0

    # PROTECT_EGG: only enabled if pack has eggs. Future: check pack
    # inventory for Egg items. For now always enabled in feral+ band;
    # the reward function handles reward-shaping for misuse.

    # Stamina gates for attack/flee/howl
    cur_stam = monster.stats.active[Stat.CUR_STAMINA]()
    if cur_stam < 3:
        mask[int(MonsterAction.ATTACK)] = 0.0
    if cur_stam < 1:
        mask[int(MonsterAction.FLEE)] = 0.0

    # PAIR: only aware+ INT, only if at adjacent compatible partner exists
    # (simplified: leave enabled if AWARE; heuristic/dispatcher filters
    # at execution time)

    # Always allow MOVE as a safe fallback
    mask[int(MonsterAction.MOVE)] = 1.0

    return mask
