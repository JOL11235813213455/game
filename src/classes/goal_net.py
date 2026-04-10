"""
Goal selection network for hierarchical RL.

The GoalNet is a small network that selects a purpose/goal for a creature.
It runs infrequently (every N ticks or when a goal is completed/abandoned)
and outputs a probability distribution over purposes.

The action model (CreatureNet) then receives the selected goal as additional
input and handles moment-to-moment decisions including navigation.

Architecture: observation → 256 → 128 → NUM_PURPOSES (goal logits)
                                       → 1 (goal value)

Much smaller than the action net — goals are a higher-level, slower decision.
"""
from __future__ import annotations
import math
import random
import numpy as np
from classes.actions import TILE_PURPOSES, NUM_PURPOSES


class GoalNet:
    """NumPy inference-only goal selection network.

    For runtime use in the game. Training uses TorchGoalNet.
    """

    def __init__(self, input_size: int = 0, h1: int = 256, h2: int = 128):
        self.input_size = input_size
        self.h1 = h1
        self.h2 = h2
        self.output_size = NUM_PURPOSES
        # Weights initialized to small random values
        scale1 = math.sqrt(2.0 / input_size) if input_size > 0 else 0.01
        self.w1 = np.random.randn(input_size, h1).astype(np.float32) * scale1
        self.b1 = np.zeros(h1, dtype=np.float32)
        self.w2 = np.random.randn(h1, h2).astype(np.float32) * math.sqrt(2.0 / h1)
        self.b2 = np.zeros(h2, dtype=np.float32)
        self.w_goal = np.random.randn(h2, NUM_PURPOSES).astype(np.float32) * 0.01
        self.b_goal = np.zeros(NUM_PURPOSES, dtype=np.float32)

    def forward(self, obs: np.ndarray) -> np.ndarray:
        """Forward pass. Returns goal logits."""
        x = np.maximum(0, obs @ self.w1 + self.b1)  # ReLU
        x = np.maximum(0, x @ self.w2 + self.b2)
        logits = x @ self.w_goal + self.b_goal
        return logits

    def select_goal(self, obs: np.ndarray, temperature: float = 1.0,
                    known_purposes: set = None) -> tuple[int, str]:
        """Select a goal from the observation.

        Args:
            obs: observation vector
            temperature: sampling temperature (lower = more deterministic)
            known_purposes: set of purpose strings the creature knows locations for.
                           Unknown purposes get their logits heavily penalized.

        Returns:
            (goal_index, purpose_string)
        """
        logits = self.forward(obs)

        # Mask out purposes the creature doesn't know locations for
        # (can't go somewhere you don't know about, except 'exploring')
        if known_purposes is not None:
            for i, purpose in enumerate(TILE_PURPOSES):
                if purpose not in known_purposes and purpose != 'exploring':
                    logits[i] -= 100.0  # effectively zero probability

        # Temperature scaling
        if temperature != 1.0:
            logits = logits / max(0.01, temperature)

        # Softmax
        logits = logits - logits.max()
        probs = np.exp(logits)
        probs = probs / probs.sum()

        # Sample
        idx = np.random.choice(len(probs), p=probs)
        return idx, TILE_PURPOSES[idx]

    def load(self, path):
        """Load weights from .npz file."""
        data = np.load(str(path))
        self.w1 = data['gw1']
        self.b1 = data['gb1']
        self.w2 = data['gw2']
        self.b2 = data['gb2']
        self.w_goal = data['gw_goal']
        self.b_goal = data['gb_goal']
        self.input_size = self.w1.shape[0]
        self.h1 = self.w1.shape[1]
        self.h2 = self.w2.shape[1]


# Goal observation builder — builds a smaller observation for goal selection
# Uses a subset of the full observation: self stats, economy, social summary,
# spatial memory summary, current goal state

def build_goal_observation(creature, cols: int, rows: int) -> list[float]:
    """Build a compact observation for goal selection.

    Much smaller than the full action observation — goals don't need
    per-engaged creature details or tile-level specifics.

    Sections:
    - Self vitals (6): hp/stam/mana ratios + raw
    - Self economy (6): gold, debt, inv_value, eq_value, carried_weight_ratio, open_slots
    - Self social (4): allies, enemies, reputation, creatures_met
    - Self status (5): fatigue, sleep_debt, piety, is_pregnant, has_partner
    - Known location counts (NUM_PURPOSES): how many locations known per purpose
    - Nearest known distance (NUM_PURPOSES): distance to nearest known per purpose
    - Current goal (NUM_PURPOSES + 3): goal one-hot, distance, progress, ticks_elapsed
    """
    from classes.stats import Stat

    obs = []
    stats = creature.stats
    s = stats.active

    # Self vitals (6)
    hp_max = max(1, s[Stat.HP_MAX]())
    stam_max = max(1, s[Stat.MAX_STAMINA]())
    mana_max = max(1, s[Stat.MAX_MANA]())
    obs.append(s[Stat.HP_CURR]() / hp_max)
    obs.append(s[Stat.HP_CURR]() / 50.0)
    obs.append(s[Stat.CUR_STAMINA]() / stam_max)
    obs.append(s[Stat.CUR_STAMINA]() / 100.0)
    obs.append(s[Stat.CUR_MANA]() / mana_max)
    obs.append(s[Stat.CUR_MANA]() / 100.0)

    # Self economy (6)
    obs.append(creature.gold / 100.0)
    debt = creature.total_debt(0) if hasattr(creature, 'total_debt') else 0
    obs.append(debt / 100.0)
    inv_value = sum(getattr(i, 'value', 0) for i in creature.inventory.items)
    obs.append(inv_value / 100.0)
    eq_value = sum(getattr(i, 'value', 0) for i in set(creature.equipment.values()))
    obs.append(eq_value / 100.0)
    carry_max = max(1, s[Stat.CARRY_WEIGHT]())
    obs.append(creature.carried_weight / carry_max)
    obs.append((14 - len(creature.equipment)) / 14.0)

    # Self social (4)
    all_rels = list(creature.relationships.values())
    obs.append(sum(1 for r in all_rels if r[0] > 5) / 10.0)
    obs.append(sum(1 for r in all_rels if r[0] < -5) / 10.0)
    depths = [r[1] / (r[1] + 5) for r in all_rels]
    sents = [r[0] for r in all_rels]
    sum_depth = sum(depths)
    rep = sum(s * d for s, d in zip(sents, depths)) / max(0.001, sum_depth) if all_rels else 0
    obs.append(rep / 20.0)
    obs.append(len(creature.relationships) / 20.0)

    # Self status (5)
    obs.append(getattr(creature, '_fatigue_level', 0) / 4.0)
    obs.append(getattr(creature, 'sleep_debt', 0) / 4.0)
    obs.append(creature.piety)
    obs.append(1.0 if creature.is_pregnant else 0.0)
    obs.append(1.0 if creature.has_partner else 0.0)

    # Known location counts per purpose (NUM_PURPOSES)
    map_name = getattr(creature.current_map, 'name', '') or ''
    for purpose in TILE_PURPOSES:
        locs = creature.known_locations.get(purpose, [])
        obs.append(min(len(locs), 5) / 5.0)

    # Nearest known distance per purpose (NUM_PURPOSES)
    for purpose in TILE_PURPOSES:
        locs = creature.known_locations.get(purpose, [])
        same_map = [(x, y) for mn, x, y, _ in locs if mn == map_name]
        if same_map:
            nearest = min(abs(x - creature.location.x) + abs(y - creature.location.y)
                          for x, y in same_map)
            obs.append(min(nearest, 50) / 50.0)
        elif locs:
            obs.append(0.8)  # known but on another map
        else:
            obs.append(1.0)  # completely unknown

    # Current goal state (NUM_PURPOSES + 3)
    for purpose in TILE_PURPOSES:
        obs.append(1.0 if creature.current_goal == purpose else 0.0)
    obs.append(min(creature.goal_distance(), 50) / 50.0 if creature.goal_target else 1.0)
    obs.append(creature.goal_progress() / 5.0)
    elapsed = 0  # would need current tick
    obs.append(min(elapsed, 1000) / 1000.0)

    return obs


GOAL_OBSERVATION_SIZE = (6 + 6 + 4 + 5 +  # self stats
                         NUM_PURPOSES +     # known counts
                         NUM_PURPOSES +     # nearest distances
                         NUM_PURPOSES + 3)  # current goal
