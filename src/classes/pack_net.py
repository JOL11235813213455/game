"""
PackNet — neural net for pack-level coordination decisions.

Acts as the GoalNet of the monster system. Runs at lower cadence than
individual MonsterNet (every 1-2s vs every monster tick). Consumes
aggregated pack state, outputs 4 signals that are broadcast to members:

  - sleep_signal   [0-1]  — 1.0 = all members should sleep
  - alert_level    [0-1]  — passive → hunt
  - cohesion       [0-1]  — spread → cluster (modulates territory sampling)
  - role_fractions [3]    — softmax over {patrol, attack, guard_eggs}

Architecture: input (14) → 64 → 32 → output (3 sigmoids + 3-way softmax)

Pure NumPy. Trained via REINFORCE with baseline (low-cadence decisions
suit simpler RL than PPO's clipping).
"""
from __future__ import annotations
import numpy as np
from pathlib import Path


PACK_OBSERVATION_SIZE = 14
PACK_OUTPUT_SIZE = 6  # 3 scalar signals + 3 role fractions


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0, x)


class PackNet:
    """Feedforward NN for pack coordination.

    Inputs (14):
      0  is_active_period
      1  light_level
      2  mean_dist_from_center (normalized by territory_radius)
      3  stdev_dist_from_center (normalized)
      4  mean_pairwise_dist (normalized)
      5  mean_hp_ratio
      6  min_hp_ratio
      7  mean_fatigue
      8  max_fatigue
      9  pack_size_norm (size / 10)
     10  egg_count_norm
     11  visible_creature_count_norm
     12  mean_distance_to_creature (normalized)
     13  min_distance_to_creature (normalized)

    Outputs (6):
      0  sleep_signal    (sigmoid)
      1  alert_level     (sigmoid)
      2  cohesion        (sigmoid)
      3  role_patrol     (softmax 3-way)
      4  role_attack     (softmax 3-way)
      5  role_guard_eggs (softmax 3-way)
    """

    def __init__(self, h1_size: int = 64, h2_size: int = 32,
                 input_size: int = PACK_OBSERVATION_SIZE,
                 output_size: int = PACK_OUTPUT_SIZE):
        self.input_size = input_size
        self.h1_size = h1_size
        self.h2_size = h2_size
        self.output_size = output_size
        self.weights: dict[str, np.ndarray] = {}
        self._init_random()

    def _init_random(self):
        s1 = np.sqrt(2.0 / (self.input_size + self.h1_size))
        s2 = np.sqrt(2.0 / (self.h1_size + self.h2_size))
        sp = np.sqrt(2.0 / (self.h2_size + self.output_size))
        self.weights = {
            'w1': np.random.randn(self.input_size, self.h1_size).astype(np.float32) * s1,
            'b1': np.zeros(self.h1_size, dtype=np.float32),
            'w2': np.random.randn(self.h1_size, self.h2_size).astype(np.float32) * s2,
            'b2': np.zeros(self.h2_size, dtype=np.float32),
            'w_out': np.random.randn(self.h2_size, self.output_size).astype(np.float32) * sp,
            'b_out': np.zeros(self.output_size, dtype=np.float32),
        }

    def forward(self, obs: np.ndarray) -> tuple:
        """Forward pass → (sleep, alert, cohesion, role_fractions dict)."""
        x = np.asarray(obs, dtype=np.float32)
        x = _relu(x @ self.weights['w1'] + self.weights['b1'])
        x = _relu(x @ self.weights['w2'] + self.weights['b2'])
        raw = x @ self.weights['w_out'] + self.weights['b_out']

        sleep_s = float(sigmoid(raw[0]))
        alert_s = float(sigmoid(raw[1]))
        cohesion_s = float(sigmoid(raw[2]))
        role_logits = raw[3:6]
        role_probs = softmax(role_logits)
        role_fractions = {
            'patrol': float(role_probs[0]),
            'attack': float(role_probs[1]),
            'guard_eggs': float(role_probs[2]),
        }
        return sleep_s, alert_s, cohesion_s, role_fractions

    def save(self, path: str | Path):
        np.savez(str(path), **self.weights)

    def load(self, path: str | Path):
        data = np.load(str(path))
        for key in self.weights:
            if key in data.files:
                arr = data[key]
                if arr.shape == self.weights[key].shape:
                    self.weights[key] = arr.astype(np.float32)


def build_pack_observation(pack, game_clock=None) -> np.ndarray:
    """Aggregate pack state into the 14-float PackNet input."""
    import math
    from classes.stats import Stat

    members = pack.members
    n = max(1, len(members))

    # Environment
    is_day = bool(getattr(game_clock, 'is_day', True)) if game_clock else True
    species_active = pack.species_config.get('active_hours', 'diurnal')
    if species_active == 'nocturnal':
        active_period = 0.0 if is_day else 1.0
    elif species_active == 'crepuscular':
        sun_elev = getattr(game_clock, 'sun_elevation', 0.5) if game_clock else 0.5
        active_period = 1.0 if 0.1 < sun_elev < 0.4 else 0.3
    else:
        active_period = 1.0 if is_day else 0.0

    if game_clock:
        light = (game_clock.sun_elevation if is_day
                 else getattr(game_clock, 'moon_brightness', 0) *
                      getattr(game_clock, 'moon_elevation', 0))
    else:
        light = 0.5

    # Distance from territory center
    center = pack.territory_center
    radius = max(1.0, pack.territory_radius())
    dists_from_center = []
    for m in members:
        dx = m.location.x - center.x
        dy = m.location.y - center.y
        dists_from_center.append(math.sqrt(dx * dx + dy * dy) / radius)

    if dists_from_center:
        mean_center = sum(dists_from_center) / len(dists_from_center)
        if len(dists_from_center) > 1:
            var = sum((d - mean_center) ** 2 for d in dists_from_center) / len(dists_from_center)
            std_center = math.sqrt(var)
        else:
            std_center = 0.0
    else:
        mean_center = 0.0
        std_center = 0.0

    # Pairwise distance
    if len(members) >= 2:
        pairwise = []
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                dx = a.location.x - b.location.x
                dy = a.location.y - b.location.y
                pairwise.append(math.sqrt(dx * dx + dy * dy) / radius)
        mean_pair = sum(pairwise) / len(pairwise)
    else:
        mean_pair = 0.0

    # HP stats
    if members:
        hp_ratios = []
        for m in members:
            hp_max = max(1, m.stats.active[Stat.HP_MAX]())
            hp_ratios.append(m.stats.active[Stat.HP_CURR]() / hp_max)
        mean_hp = sum(hp_ratios) / len(hp_ratios)
        min_hp = min(hp_ratios)
    else:
        mean_hp = 0.0
        min_hp = 0.0

    # Fatigue: 1 - hunger_ratio as a cheap proxy (monsters don't track
    # sleep_debt yet). Could be refined later.
    if members:
        fatigues = [max(0.0, -m.hunger) for m in members]
        mean_fatigue = sum(fatigues) / len(fatigues)
        max_fatigue = max(fatigues)
    else:
        mean_fatigue = 0.0
        max_fatigue = 0.0

    # Shared perception
    seen = pack.seen_creatures
    visible_count_norm = min(1.0, len(seen) / 10.0)
    if seen:
        dists = []
        for cid, (x, y, _) in seen.items():
            mx = center.x
            my = center.y
            dists.append(math.sqrt((x - mx) ** 2 + (y - my) ** 2) / radius)
        mean_creature_dist = sum(dists) / len(dists)
        min_creature_dist = min(dists)
    else:
        mean_creature_dist = 1.0
        min_creature_dist = 1.0

    # Egg count (future: pack tracks eggs directly; for now 0)
    egg_count_norm = 0.0

    # Pack size
    pack_size_norm = min(1.0, n / 10.0)

    return np.array([
        active_period,
        max(0.0, min(1.0, light)),
        min(1.0, mean_center),
        min(1.0, std_center),
        min(1.0, mean_pair),
        mean_hp, min_hp,
        mean_fatigue, max_fatigue,
        pack_size_norm, egg_count_norm,
        visible_count_norm,
        min(1.0, mean_creature_dist), min(1.0, min_creature_dist),
    ], dtype=np.float32)
