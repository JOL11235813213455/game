"""
Goal selection network for hierarchical RL.

The GoalNet selects a purpose/goal for a creature. It runs on a
variable interval (distance-based + emergency interrupts) and outputs
a probability distribution over purposes.

The action model (CreatureNet) handles moment-to-moment decisions
including navigation toward the selected goal.

Architecture: observation → 384 → 256 → 128 → NUM_PURPOSES (goal logits)
                                              → 1 (goal value)

Three hidden layers with LayerNorm for stable training across
heterogeneous input scales.
"""
from __future__ import annotations
import math
import random
import numpy as np
from classes.actions import TILE_PURPOSES, NUM_PURPOSES
from classes.relationship_graph import GRAPH


def _layer_norm(x: np.ndarray, gamma: np.ndarray, beta: np.ndarray,
                eps: float = 1e-5) -> np.ndarray:
    mean = x.mean()
    var = x.var()
    return gamma * (x - mean) / np.sqrt(var + eps) + beta


class GoalNet:
    """NumPy inference-only goal selection network (3-layer with LayerNorm)."""

    def __init__(self, input_size: int = 0,
                 h1: int = 384, h2: int = 256, h3: int = 128):
        self.input_size = input_size
        self.h1, self.h2, self.h3 = h1, h2, h3
        self.output_size = NUM_PURPOSES
        s1 = math.sqrt(2.0 / input_size) if input_size > 0 else 0.01
        self.w1 = np.random.randn(input_size, h1).astype(np.float32) * s1
        self.b1 = np.zeros(h1, dtype=np.float32)
        self.ln1_g = np.ones(h1, dtype=np.float32)
        self.ln1_b = np.zeros(h1, dtype=np.float32)
        self.w2 = np.random.randn(h1, h2).astype(np.float32) * math.sqrt(2.0 / h1)
        self.b2 = np.zeros(h2, dtype=np.float32)
        self.ln2_g = np.ones(h2, dtype=np.float32)
        self.ln2_b = np.zeros(h2, dtype=np.float32)
        self.w3 = np.random.randn(h2, h3).astype(np.float32) * math.sqrt(2.0 / h2)
        self.b3 = np.zeros(h3, dtype=np.float32)
        self.ln3_g = np.ones(h3, dtype=np.float32)
        self.ln3_b = np.zeros(h3, dtype=np.float32)
        self.w_goal = np.random.randn(h3, NUM_PURPOSES).astype(np.float32) * 0.01
        self.b_goal = np.zeros(NUM_PURPOSES, dtype=np.float32)

    def forward(self, obs: np.ndarray) -> np.ndarray:
        x = np.maximum(0, _layer_norm(obs @ self.w1 + self.b1, self.ln1_g, self.ln1_b))
        x = np.maximum(0, _layer_norm(x @ self.w2 + self.b2, self.ln2_g, self.ln2_b))
        x = np.maximum(0, _layer_norm(x @ self.w3 + self.b3, self.ln3_g, self.ln3_b))
        return x @ self.w_goal + self.b_goal

    def select_goal(self, obs: np.ndarray, temperature: float = 1.0,
                    known_purposes: set = None) -> tuple[int, str]:
        logits = self.forward(obs)
        if known_purposes is not None:
            for i, purpose in enumerate(TILE_PURPOSES):
                if purpose not in known_purposes and purpose != 'exploring':
                    logits[i] -= 100.0
        if temperature != 1.0:
            logits = logits / max(0.01, temperature)
        logits = logits - logits.max()
        probs = np.exp(logits)
        probs = probs / probs.sum()
        idx = np.random.choice(len(probs), p=probs)
        return idx, TILE_PURPOSES[idx]

    def load(self, path):
        data = np.load(str(path))
        self.w1 = data['gw1']; self.b1 = data['gb1']
        self.ln1_g = data['gln1_g']; self.ln1_b = data['gln1_b']
        self.w2 = data['gw2']; self.b2 = data['gb2']
        self.ln2_g = data['gln2_g']; self.ln2_b = data['gln2_b']
        self.w3 = data['gw3']; self.b3 = data['gb3']
        self.ln3_g = data['gln3_g']; self.ln3_b = data['gln3_b']
        self.w_goal = data['gw_goal']; self.b_goal = data['gb_goal']
        self.input_size = self.w1.shape[0]
        self.h1 = self.w1.shape[1]
        self.h2 = self.w2.shape[1]
        self.h3 = self.w3.shape[1]


# ---------------------------------------------------------------------------
# Goal observation builder
# ---------------------------------------------------------------------------

def build_goal_observation(creature, cols: int, rows: int,
                           game_clock=None, tick: int = 0) -> list[float]:
    """Build observation for goal selection.

    Sections:
    - Self vitals (6)
    - Self economy (6)
    - Self social (5): +outstanding_lies
    - Self status (7): +is_fertile, fecundity
    - Urgency signals (7): hunger, sleep, HP, debt, work, equipment, exploration
    - Hunger (3): raw, positive, starving flag
    - Combat/readiness (4): enemies, recent combat, avg durability, critical flag
    - Crafting/capability (3): has frame, has processable, can_swim
    - Known location counts (NUM_PURPOSES)
    - Nearest known distance (NUM_PURPOSES)
    - Job context (NUM_PURPOSES + 4): purpose one-hot, work/sleep hours, wage, at_workplace
    - Time of day (4): sin/cos hour, hours until work, hours until sleep
    - Quest context (4): active count, purpose match, progress, distance
    - Current goal (NUM_PURPOSES + 3): one-hot, distance, progress, elapsed
    """
    from classes.stats import Stat
    from classes.inventory import Equippable, Stackable

    obs = []
    stats = creature.stats
    s = stats.active

    # ---- Self vitals (6) ----
    hp_max = max(1, s[Stat.HP_MAX]())
    stam_max = max(1, s[Stat.MAX_STAMINA]())
    mana_max = max(1, s[Stat.MAX_MANA]())
    hp_ratio = s[Stat.HP_CURR]() / hp_max
    obs.append(hp_ratio)
    obs.append(s[Stat.HP_CURR]() / 50.0)
    obs.append(s[Stat.CUR_STAMINA]() / stam_max)
    obs.append(s[Stat.CUR_STAMINA]() / 100.0)
    obs.append(s[Stat.CUR_MANA]() / mana_max)
    obs.append(s[Stat.CUR_MANA]() / 100.0)

    # ---- Self economy (6) ----
    gold = creature.gold
    debt = creature.total_debt(0) if hasattr(creature, 'total_debt') else 0
    inv_value = sum(getattr(i, 'value', 0) for i in creature.inventory.items)
    eq_value = sum(getattr(i, 'value', 0) for i in set(creature.equipment.values()))
    carry_max = max(1, s[Stat.CARRY_WEIGHT]())
    obs.append(gold / 100.0)
    obs.append(debt / 100.0)
    obs.append(inv_value / 100.0)
    obs.append(eq_value / 100.0)
    obs.append(creature.carried_weight / carry_max)
    obs.append((14 - len(creature.equipment)) / 14.0)

    # ---- Self social (5) ----
    all_rels = list(GRAPH.edges_from(creature.uid).values())
    n_allies = sum(1 for r in all_rels if r[0] > 5)
    n_enemies = sum(1 for r in all_rels if r[0] < -5)
    depths = [r[1] / (r[1] + 5) for r in all_rels]
    sents = [r[0] for r in all_rels]
    sum_depth = sum(depths)
    rep = sum(s * d for s, d in zip(sents, depths)) / max(0.001, sum_depth) if all_rels else 0
    obs.append(n_allies / 10.0)
    obs.append(n_enemies / 10.0)
    obs.append(rep / 20.0)
    obs.append(GRAPH.count_from(creature.uid) / 20.0)
    obs.append(GRAPH.outstanding_lies(creature.uid) / 10.0)

    # ---- Self status (7) ----
    sleep_debt = getattr(creature, 'sleep_debt', 0)
    obs.append(getattr(creature, '_fatigue_level', 0) / 4.0)
    obs.append(sleep_debt / 4.0)
    obs.append(creature.piety)
    obs.append(1.0 if creature.is_pregnant else 0.0)
    obs.append(1.0 if creature.has_partner else 0.0)
    obs.append(1.0 if creature.is_fertile else 0.0)
    obs.append(creature.fecundity() if hasattr(creature, 'fecundity') else 0.0)

    # ---- Urgency signals (7) ----
    hunger = getattr(creature, 'hunger', 0.0)
    hunger_urgency = max(0.0, -hunger) ** 0.5

    cur_hour = game_clock.hour if game_clock else 12.0
    schedule = getattr(creature, 'schedule', None)
    activity = schedule.activity_at(cur_hour) if schedule else 'open'
    is_work = activity == 'work'
    is_sleep_time = activity == 'sleep'
    sleep_urgency = min(1.0, sleep_debt / 3.0) * (1.0 if is_sleep_time else 0.5)

    hp_danger = max(0.0, 1.0 - hp_ratio * 3.0)

    wealth = max(1.0, float(gold) + inv_value)
    debt_pressure = 1.0 / (1.0 + math.exp(-(debt / wealth - 1.0) * 4)) if debt > 0 else 0.0

    job = getattr(creature, 'job', None)
    tile = creature.current_map.tiles.get(creature.location) if creature.current_map else None
    tile_purpose = getattr(tile, 'purpose', None) if tile else None
    at_workplace = bool(job and tile_purpose and tile_purpose in job.workplace_purposes)
    work_urgency = 1.0 if (is_work and job and not at_workplace) else 0.0

    eq_durs = []
    for eq in set(creature.equipment.values()):
        if eq is not None and hasattr(eq, 'durability_current') and eq.durability_current is not None:
            eq_durs.append(eq.durability_current / max(1, eq.durability_max))
    avg_dur = sum(eq_durs) / max(1, len(eq_durs)) if eq_durs else 1.0
    equip_decay = max(0.0, 1.0 - avg_dur * 2.0)

    known_total = sum(len(v) for v in creature.known_locations.values())
    exploration_pressure = max(0.0, 1.0 - known_total / (NUM_PURPOSES * 3))

    obs.append(hunger_urgency)
    obs.append(sleep_urgency)
    obs.append(hp_danger)
    obs.append(debt_pressure)
    obs.append(work_urgency)
    obs.append(equip_decay)
    obs.append(exploration_pressure)

    # ---- Hunger (3) ----
    obs.append(hunger)
    obs.append(max(0.0, hunger))
    obs.append(1.0 if hunger < -0.5 else 0.0)

    # ---- Combat / readiness (4) ----
    obs.append(n_enemies / 10.0)
    event_ticks = getattr(creature, '_event_ticks', {})
    last_combat = event_ticks.get('combat', -9999)
    obs.append(1.0 if (tick - last_combat) < 100 else 0.0)
    obs.append(avg_dur)
    obs.append(1.0 if any(d < 0.2 for d in eq_durs) else 0.0)

    # ---- Crafting / capability (3) ----
    from classes.inventory import ItemFrame as _IF
    has_frame = any(isinstance(i, _IF) for i in creature.inventory.items)
    has_processable = any(isinstance(i, Stackable) and getattr(i, 'value', 0) > 0
                          for i in creature.inventory.items)
    obs.append(1.0 if has_frame else 0.0)
    obs.append(1.0 if has_processable else 0.0)
    obs.append(1.0 if creature.can_swim else 0.0)

    # ---- Known location counts (NUM_PURPOSES) ----
    map_name = getattr(creature.current_map, 'name', '') or ''
    for purpose in TILE_PURPOSES:
        locs = creature.known_locations.get(purpose, [])
        obs.append(min(len(locs), 5) / 5.0)

    # ---- Nearest known distance (NUM_PURPOSES) ----
    for purpose in TILE_PURPOSES:
        locs = creature.known_locations.get(purpose, [])
        same_map = [(x, y) for mn, x, y, _ in locs if mn == map_name]
        if same_map:
            nearest = min(abs(x - creature.location.x) + abs(y - creature.location.y)
                          for x, y in same_map)
            obs.append(min(nearest, 50) / 50.0)
        elif locs:
            obs.append(0.8)
        else:
            obs.append(1.0)

    # ---- Job context (NUM_PURPOSES + 4) ----
    for purpose in TILE_PURPOSES:
        obs.append(1.0 if (job and job.purpose == purpose) else 0.0)
    obs.append(1.0 if is_work else 0.0)
    obs.append(1.0 if is_sleep_time else 0.0)
    obs.append(job.wage_per_tick / 2.0 if job else 0.0)
    obs.append(1.0 if at_workplace else 0.0)

    # ---- Time of day (4) ----
    hour_frac = cur_hour / 24.0
    obs.append(math.sin(hour_frac * 2 * math.pi))
    obs.append(math.cos(hour_frac * 2 * math.pi))
    # Hours until next work/sleep period
    if schedule:
        hrs_to_work = 0.0
        hrs_to_sleep = 0.0
        for offset in range(1, 25):
            h = (cur_hour + offset) % 24.0
            if hrs_to_work == 0.0 and schedule.in_work_hours(h):
                hrs_to_work = offset
            if hrs_to_sleep == 0.0 and schedule.in_sleep_hours(h):
                hrs_to_sleep = offset
            if hrs_to_work > 0 and hrs_to_sleep > 0:
                break
        obs.append(hrs_to_work / 12.0 if hrs_to_work > 0 else 0.0)
        obs.append(hrs_to_sleep / 12.0 if hrs_to_sleep > 0 else 0.0)
    else:
        obs.append(0.0)
        obs.append(0.0)

    # ---- Quest context (4) ----
    active_quests = creature.quest_log.get_active_quests() if hasattr(creature, 'quest_log') else []
    obs.append(len(active_quests) / 5.0)
    quest_purpose_match = 0.0
    quest_progress = 0.0
    quest_dist = 1.0
    if active_quests and creature.current_goal:
        for q in active_quests:
            if hasattr(q, 'purpose') and q.purpose == creature.current_goal:
                quest_purpose_match = 1.0
                break
    obs.append(quest_purpose_match)
    obs.append(getattr(creature, '_quest_steps_completed', 0) / 20.0)
    obs.append(quest_dist)

    # ---- Current goal state (NUM_PURPOSES + 3) ----
    for purpose in TILE_PURPOSES:
        obs.append(1.0 if creature.current_goal == purpose else 0.0)
    obs.append(min(creature.goal_distance(), 50) / 50.0 if creature.goal_target else 1.0)
    obs.append(creature.goal_progress() / 5.0)
    elapsed = (tick - creature.goal_started_tick) if creature.goal_target else 0
    obs.append(min(elapsed, 1000) / 1000.0)

    return obs


GOAL_OBSERVATION_SIZE = (6 + 6 + 5 + 7 +       # vitals, economy, social, status
                         7 + 3 + 4 + 3 +        # urgency, hunger, combat, crafting
                         NUM_PURPOSES +          # known counts
                         NUM_PURPOSES +          # nearest distances
                         NUM_PURPOSES + 4 +      # job context
                         4 +                     # time of day
                         4 +                     # quest context
                         NUM_PURPOSES + 3)       # current goal
