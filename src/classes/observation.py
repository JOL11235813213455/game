"""
Observation vector assembly for the creature RL system.

Converts a creature's current state + surroundings into a flat
numeric vector suitable for neural net input. All values are normalized
to roughly [-1, 1] or [0, 1] range.

The observation has fixed-size sections:
  - Self stats (normalized base + key derived)
  - Resource ratios (HP%, stamina%, mana%)
  - Status flags (sleeping, guarding, blocking, fatigue level)
  - Per-neighbor slots (up to MAX_NEIGHBORS nearest creatures)
  - Terrain (adjacent tile walkability)
  - Temporal deltas (HP, stamina, distance-to-threat changes)
"""
from __future__ import annotations
from classes.stats import Stat
from classes.maps import MapKey

# Maximum neighbors encoded in the observation vector.
# Creatures beyond this count are dropped (furthest first).
MAX_NEIGHBORS = 8

# Stat normalization: divide raw stat by this to get ~[0, 1]
_STAT_NORM = 20.0


def _norm_stat(val: float) -> float:
    """Normalize a raw stat value to roughly [0, 1]."""
    return val / _STAT_NORM


def _ratio(cur: float, mx: float) -> float:
    """Safe ratio cur/max, returns 0 if max is 0."""
    return cur / mx if mx > 0 else 0.0


def _sign_norm(val: float, scale: float = 10.0) -> float:
    """Normalize a signed value to roughly [-1, 1]."""
    return val / (abs(val) + scale)


# ---- Observation vector layout ----
# Section sizes (for documentation and slicing):
#   self_stats:     7 base stats + 8 key derived = 15
#   resources:      3 (HP%, stamina%, mana%)
#   status:         4 (sleeping, guarding, blocking, fatigue)
#   per_neighbor:   10 per slot × MAX_NEIGHBORS
#   terrain:        8 (adjacent walkability) + 1 (current walkable)
#   temporal:       3 (HP delta, stamina delta, threat distance delta)
#   totals:         15 + 3 + 4 + (10 * MAX_NEIGHBORS) + 9 + 3 = 114 (with MAX_NEIGHBORS=8)

SELF_STATS_SIZE = 15
RESOURCES_SIZE = 3
STATUS_SIZE = 4
PER_NEIGHBOR_SIZE = 10
TERRAIN_SIZE = 9
TEMPORAL_SIZE = 3

OBSERVATION_SIZE = (SELF_STATS_SIZE + RESOURCES_SIZE + STATUS_SIZE +
                    PER_NEIGHBOR_SIZE * MAX_NEIGHBORS + TERRAIN_SIZE + TEMPORAL_SIZE)


def build_observation(creature, cols: int, rows: int,
                      prev_snapshot: dict | None = None) -> list[float]:
    """Build a flat observation vector for a creature.

    Args:
        creature: the Creature to observe
        cols, rows: map dimensions
        prev_snapshot: previous frame's {hp, stamina, threat_dist} for deltas

    Returns:
        list of floats (length = OBSERVATION_SIZE)
    """
    obs = []
    stats = creature.stats

    # ---- Self stats (normalized) ----
    for s in (Stat.STR, Stat.VIT, Stat.AGL, Stat.PER, Stat.INT, Stat.CHR, Stat.LCK):
        obs.append(_norm_stat(stats.active[s]()))

    # Key derived stats
    obs.append(_norm_stat(stats.active[Stat.MELEE_DMG]()))
    obs.append(_norm_stat(stats.active[Stat.DODGE]()))
    obs.append(_norm_stat(stats.active[Stat.ARMOR]()))
    obs.append(_norm_stat(stats.active[Stat.MOVE_SPEED]()))
    obs.append(_norm_stat(stats.active[Stat.SIGHT_RANGE]()))
    obs.append(_norm_stat(stats.active[Stat.STEALTH]()))
    obs.append(_norm_stat(stats.active[Stat.DETECTION]()))
    obs.append(_norm_stat(stats.active[Stat.CARRY_WEIGHT]()) / 5.0)  # larger scale

    # ---- Resource ratios ----
    hp_max = stats.active[Stat.HP_MAX]()
    hp_cur = stats.active[Stat.HP_CURR]()
    stam_max = stats.active[Stat.MAX_STAMINA]()
    stam_cur = stats.active[Stat.CUR_STAMINA]()
    mana_max = stats.active[Stat.MAX_MANA]()
    mana_cur = stats.active[Stat.CUR_MANA]()

    obs.append(_ratio(hp_cur, hp_max))
    obs.append(_ratio(stam_cur, stam_max))
    obs.append(_ratio(mana_cur, mana_max))

    # ---- Status flags ----
    obs.append(1.0 if getattr(creature, 'is_sleeping', False) else 0.0)
    obs.append(1.0 if getattr(creature, 'is_guarding', False) else 0.0)
    obs.append(1.0 if getattr(creature, 'is_blocking', False) else 0.0)
    obs.append(getattr(creature, '_fatigue_level', 0) / 4.0)

    # ---- Nearby creatures ----
    from classes.world_object import WorldObject
    from classes.creature import Creature

    neighbors = []
    for obj in WorldObject.on_map(creature.current_map):
        if not isinstance(obj, Creature) or obj is creature:
            continue
        dist = (abs(creature.location.x - obj.location.x) +
                abs(creature.location.y - obj.location.y))
        sight = stats.active[Stat.SIGHT_RANGE]()
        if dist > sight:
            continue
        neighbors.append((dist, obj))

    # Sort by distance, take closest MAX_NEIGHBORS
    neighbors.sort(key=lambda x: x[0])
    neighbors = neighbors[:MAX_NEIGHBORS]

    for dist, other in neighbors:
        obs.append(dist / max(1, cols + rows))  # normalized distance
        # Relative direction (dx, dy normalized)
        dx = other.location.x - creature.location.x
        dy = other.location.y - creature.location.y
        mag = max(1, abs(dx) + abs(dy))
        obs.append(dx / mag)
        obs.append(dy / mag)
        # Relationship data
        rel = creature.get_relationship(other)
        if rel:
            obs.append(_sign_norm(rel[0]))          # sentiment
            obs.append(rel[1] / (rel[1] + 5))       # confidence
        else:
            obs.append(0.0)  # unknown sentiment
            obs.append(0.0)  # zero confidence
        # Curiosity
        obs.append(creature.curiosity_toward(other))
        # Rumor opinion
        obs.append(_sign_norm(creature.rumor_opinion(other.uid, current_tick=0)))
        # Observable threat level (HP ratio proxy + equipment presence)
        other_hp_ratio = _ratio(other.stats.active[Stat.HP_CURR](),
                                other.stats.active[Stat.HP_MAX]())
        has_weapon = 1.0 if any(True for _ in other.equipment.values()) else 0.0
        obs.append(other_hp_ratio)
        obs.append(has_weapon)
        # Same species
        same_species = 1.0 if (getattr(creature, 'species', None) and
                               creature.species == getattr(other, 'species', None)) else 0.0
        obs.append(same_species)

    # Pad remaining neighbor slots with zeros
    filled = len(neighbors)
    obs.extend([0.0] * (PER_NEIGHBOR_SIZE * (MAX_NEIGHBORS - filled)))

    # ---- Terrain ----
    # Current tile + 8 adjacent: walkable = 1.0, not = 0.0
    cx, cy = creature.location.x, creature.location.y
    game_map = creature.current_map
    for dx, dy in [(0, 0), (0, -1), (0, 1), (-1, 0), (1, 0),
                   (-1, -1), (1, -1), (-1, 1), (1, 1)]:
        tile = game_map.tiles.get(MapKey(cx + dx, cy + dy, creature.location.z))
        obs.append(1.0 if (tile and tile.walkable) else 0.0)

    # ---- Temporal deltas ----
    if prev_snapshot:
        hp_delta = (hp_cur - prev_snapshot.get('hp', hp_cur)) / max(1, hp_max)
        stam_delta = (stam_cur - prev_snapshot.get('stamina', stam_cur)) / max(1, stam_max)
        # Threat distance delta: negative = threat getting closer
        old_threat = prev_snapshot.get('threat_dist', 999)
        # Find closest hostile creature
        closest_threat = 999
        for dist, other in neighbors:
            rel = creature.get_relationship(other)
            if rel and rel[0] < -5:
                closest_threat = min(closest_threat, dist)
                break
        threat_delta = (closest_threat - old_threat) / max(1, cols)
        obs.append(hp_delta)
        obs.append(stam_delta)
        obs.append(threat_delta)
    else:
        obs.extend([0.0, 0.0, 0.0])

    assert len(obs) == OBSERVATION_SIZE, f"Expected {OBSERVATION_SIZE}, got {len(obs)}"
    return obs


def make_snapshot(creature, neighbors: list = None) -> dict:
    """Capture current state for next frame's temporal deltas."""
    hp = creature.stats.active[Stat.HP_CURR]()
    stam = creature.stats.active[Stat.CUR_STAMINA]()

    closest_threat = 999
    if neighbors:
        for dist, other in neighbors:
            rel = creature.get_relationship(other)
            if rel and rel[0] < -5:
                closest_threat = min(closest_threat, dist)
                break

    return {'hp': hp, 'stamina': stam, 'threat_dist': closest_threat}
