"""
Monster observation builder.

Produces the flat float vector consumed by MonsterNet. Intentionally
simpler than the creature observation: no social/economic/relationship
sections. Focus on predator essentials — self state, perception of
prey, pack directives, territory awareness.

Layout (total = 93):
  SECTION 1  Self stats (6):     STR, AGL, PER, VIT, INT, LCK normalized
  SECTION 2  Self derived (8):   HP ratio, stam ratio, mana ratio,
                                 hunger, is_adult, fatigue, is_fleeing,
                                 in_liquid
  SECTION 3  Self identity (4):  size_norm, diet one-hot×3
                                 (carnivore/herbivore/omnivore)
  SECTION 4  Prey slots (5×6 = 30): for each of 5 nearest creatures
        (dx, dy, hp_ratio, size_norm, is_fleeing, threat_score)
  SECTION 5  Prey summary (4):   count_nearby, nearest_dist, mean_hp,
                                 is_creature_seen_by_pack
  SECTION 6  Pack signals (8):   sleep, alert, cohesion, role one-hot×4
                                 (patrol/attack/guard_eggs/rest),
                                 in_own_territory
  SECTION 7  Territory (5):      dx_to_center, dy_to_center,
                                 dist_from_center / territory_radius,
                                 pack_size_norm, is_alpha
  SECTION 8  Environment (4):    is_active_period (species-aware),
                                 light_level, tile_is_liquid,
                                 tile_is_compatible_for_grazing
  SECTION 9  Temporal (4):       hp_delta, hunger_delta,
                                 threat_distance_delta,
                                 kills_delta

All values clamped to [-1, 1] where negative is meaningful.
"""
from __future__ import annotations
import math
from classes.stats import Stat
from classes.maps import MapKey

MONSTER_OBSERVATION_SIZE = 69  # recomputed below; asserted at load

MAX_PREY_SLOTS = 5

# Diet one-hot order
_DIET_ORDER = ['carnivore', 'herbivore', 'omnivore']
# Role one-hot order
_ROLE_ORDER = ['patrol', 'attack', 'guard_eggs', 'rest']
# Size -> 0-1 mapping
_SIZE_NORM = {'tiny': 0.0, 'small': 0.2, 'medium': 0.4,
              'large': 0.6, 'huge': 0.8, 'colossal': 1.0}


def _clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def _ratio(cur, mx):
    return cur / mx if mx > 0 else 0.0


def build_monster_observation(monster, cols: int, rows: int,
                              game_clock=None,
                              prev_snapshot: dict | None = None) -> list[float]:
    """Produce the monster observation vector.

    Args:
        monster: the Monster instance
        cols, rows: map dimensions (for normalization)
        game_clock: optional GameClock for day/night awareness
        prev_snapshot: optional dict from make_monster_snapshot() for
            temporal deltas
    """
    obs: list[float] = []

    stats = monster.stats
    hp_cur = stats.active[Stat.HP_CURR]()
    hp_max = max(1, stats.active[Stat.HP_MAX]())
    stam_cur = stats.active[Stat.CUR_STAMINA]()
    stam_max = max(1, stats.active[Stat.MAX_STAMINA]())
    mana_cur = stats.active[Stat.CUR_MANA]()
    mana_max = max(1, stats.active[Stat.MAX_MANA]())
    sight = max(1, stats.active[Stat.SIGHT_RANGE]())

    # ==== SECTION 1: SELF STATS (6) ====
    for stat_key in (Stat.STR, Stat.AGL, Stat.PER, Stat.VIT, Stat.INT, Stat.LCK):
        val = stats.base.get(stat_key, 10)
        obs.append(val / 20.0)

    # ==== SECTION 2: SELF DERIVED (8) ====
    obs.append(_ratio(hp_cur, hp_max))
    obs.append(_ratio(stam_cur, stam_max))
    obs.append(_ratio(mana_cur, mana_max))
    obs.append(max(-1.0, min(1.0, monster.hunger)))
    obs.append(1.0 if monster.age >= 18 else 0.0)
    # Fatigue: monsters don't track sleep_debt currently; leave as 0
    obs.append(0.0)
    # is_fleeing flag: the monster's own heuristic for running away.
    # Set by the action dispatcher; zero if unknown.
    obs.append(1.0 if getattr(monster, '_is_fleeing', False) else 0.0)
    obs.append(1.0 if getattr(monster, 'is_drowning', False) else 0.0)

    # ==== SECTION 3: SELF IDENTITY (4) ====
    obs.append(_SIZE_NORM.get(monster.size, 0.4))
    for d in _DIET_ORDER:
        obs.append(1.0 if monster.diet == d else 0.0)

    # ==== SECTION 4: PREY SLOTS (5 × 6 = 30) ====
    # Reuse the existing creature perception cache on the monster. Since
    # Monster shares the location setter pattern, get_perception works
    # the same way after we add it. For MVP we do a direct nearby scan.
    prey = _visible_creatures(monster, sight)
    prey.sort(key=lambda p: p[0])  # ascending distance
    for i in range(MAX_PREY_SLOTS):
        if i < len(prey):
            dist, cr = prey[i]
            dx = (cr.location.x - monster.location.x) / sight
            dy = (cr.location.y - monster.location.y) / sight
            cr_hp_max = max(1, cr.stats.active[Stat.HP_MAX]())
            hp_r = _ratio(cr.stats.active[Stat.HP_CURR](), cr_hp_max)
            size_n = _SIZE_NORM.get(getattr(cr, 'size', 'medium'), 0.4)
            is_fleeing = 1.0 if getattr(cr, '_is_fleeing', False) else 0.0
            threat = _threat_score(monster, cr) / 20.0
            obs.extend([_clamp(dx), _clamp(dy), hp_r, size_n,
                        is_fleeing, _clamp(threat)])
        else:
            obs.extend([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    # ==== SECTION 5: PREY SUMMARY (4) ====
    obs.append(min(1.0, len(prey) / 10.0))
    obs.append((min(p[0] for p in prey) if prey else sight) / sight)
    if prey:
        hp_sum = sum(_ratio(p[1].stats.active[Stat.HP_CURR](),
                             max(1, p[1].stats.active[Stat.HP_MAX]()))
                     for p in prey)
        obs.append(hp_sum / len(prey))
    else:
        obs.append(0.0)
    # Creature known-to-pack flag (via pack shared perception)
    pack = monster.pack
    creature_known = 0.0
    if pack is not None and pack.seen_creatures:
        creature_known = 1.0
    obs.append(creature_known)

    # ==== SECTION 6: PACK SIGNALS (8) ====
    obs.append(_clamp(monster._pack_sleep_signal))
    obs.append(_clamp(monster._pack_alert_level))
    obs.append(_clamp(monster._pack_cohesion))
    for role in _ROLE_ORDER:
        obs.append(1.0 if monster._pack_role == role else 0.0)
    # in_own_territory bool
    in_own_terr = 0.0
    if pack is not None:
        center = pack.territory_center
        dx = monster.location.x - center.x
        dy = monster.location.y - center.y
        if math.sqrt(dx*dx + dy*dy) <= pack.territory_radius():
            in_own_terr = 1.0
    obs.append(in_own_terr)

    # ==== SECTION 7: TERRITORY (5) ====
    if pack is not None:
        center = pack.territory_center
        radius = max(0.5, pack.territory_radius())
        dx = (monster.location.x - center.x) / radius
        dy = (monster.location.y - center.y) / radius
        dist_norm = math.sqrt(dx*dx + dy*dy)
        obs.append(_clamp(dx))
        obs.append(_clamp(dy))
        obs.append(_clamp(dist_norm))
        obs.append(min(1.0, pack.size / 10.0))
    else:
        obs.extend([0.0, 0.0, 0.0, 0.0])
    obs.append(1.0 if monster.is_alpha else 0.0)

    # ==== SECTION 8: ENVIRONMENT (4) ====
    # Active period: nocturnal XOR is_day
    is_day = bool(getattr(game_clock, 'is_day', True)) if game_clock else True
    if monster.active_hours == 'nocturnal':
        active_period = 0.0 if is_day else 1.0
    elif monster.active_hours == 'crepuscular':
        # Rough heuristic: active near dawn/dusk — just use sun elevation
        sun_elev = getattr(game_clock, 'sun_elevation', 0.5) if game_clock else 0.5
        active_period = 1.0 if 0.1 < sun_elev < 0.4 else 0.3
    else:  # diurnal
        active_period = 1.0 if is_day else 0.0
    obs.append(active_period)

    # Light level
    if game_clock:
        light = game_clock.sun_elevation if is_day else (
            getattr(game_clock, 'moon_brightness', 0) *
            getattr(game_clock, 'moon_elevation', 0))
    else:
        light = 0.5
    obs.append(_clamp(light, 0.0, 1.0))

    # Tile liquid + compatible grazing
    tile_liquid = 0.0
    tile_compat = 0.0
    if monster.current_map is not None:
        tile = monster.current_map.tiles.get(monster.location)
        if tile is not None:
            tile_liquid = 1.0 if getattr(tile, 'liquid', False) else 0.0
            if monster.compatible_tile is not None:
                tp = getattr(tile, 'purpose', None) or getattr(tile, 'resource_type', None)
                tile_compat = 1.0 if tp == monster.compatible_tile else 0.0
    obs.append(tile_liquid)
    obs.append(tile_compat)

    # ==== SECTION 9: TEMPORAL (4) ====
    prev = prev_snapshot or {}
    obs.append(_ratio(hp_cur, hp_max) - prev.get('hp_ratio', _ratio(hp_cur, hp_max)))
    obs.append(monster.hunger - prev.get('hunger', monster.hunger))
    prev_nearest = prev.get('nearest_prey_dist', sight)
    nearest = min(p[0] for p in prey) if prey else sight
    obs.append((nearest - prev_nearest) / sight)
    obs.append(monster._kills - prev.get('kills', monster._kills))

    return obs


def make_monster_snapshot(monster) -> dict:
    """Capture fields needed for next-tick temporal deltas."""
    from classes.stats import Stat
    hp_cur = monster.stats.active[Stat.HP_CURR]()
    hp_max = max(1, monster.stats.active[Stat.HP_MAX]())
    sight = max(1, monster.stats.active[Stat.SIGHT_RANGE]())
    prey = _visible_creatures(monster, sight)
    return {
        'hp_ratio': _ratio(hp_cur, hp_max),
        'hunger': monster.hunger,
        'nearest_prey_dist': min(p[0] for p in prey) if prey else sight,
        'kills': monster._kills,
    }


def _visible_creatures(monster, sight: int) -> list:
    """Return list of (manhattan_distance, Creature) within sight."""
    from classes.creature import Creature
    if monster.current_map is None:
        return []
    mx, my = monster.location.x, monster.location.y
    if hasattr(monster.current_map, 'creatures_in_range'):
        candidates = monster.current_map.creatures_in_range(
            mx, my, monster.location.z, sight)
    else:
        candidates = Creature.on_same_map(monster.current_map)
    result = []
    for c in candidates:
        if not c.is_alive:
            continue
        d = abs(c.location.x - mx) + abs(c.location.y - my)
        if d <= sight:
            result.append((d, c))
    return result


def _threat_score(monster, creature) -> float:
    """Estimate damage threat posed by a creature to this monster.

    Mirrors Creature._threat_score_against. Higher = more dangerous.
    """
    from classes.stats import Stat
    from classes.inventory import Weapon, Slot
    their_melee = creature.stats.active[Stat.MELEE_DMG]()
    their_weapon = 0
    try:
        w = (creature.equipment.get(Slot.HAND_R) or
             creature.equipment.get(Slot.HAND_L))
        if w and isinstance(w, Weapon):
            their_weapon = getattr(w, 'damage', 0)
    except Exception:
        pass
    my_armor = monster.stats.active[Stat.ARMOR]()
    per_hit = max(0, their_melee + their_weapon - my_armor)
    return float(per_hit * 5)


# Size probe to validate observation vector length on load.
def _probe_observation_size() -> int:
    """Build an observation with a probe monster to lock down the size."""
    try:
        from classes.maps import Map, Tile
        from classes.monster import Monster
        tiles = {MapKey(x, y, 0): Tile(walkable=True)
                 for x in range(5) for y in range(5)}
        m = Map(tile_set=tiles, entrance=(0, 0), x_max=5, y_max=5)
        mon = Monster(current_map=m, location=MapKey(2, 2, 0),
                      species='grey_wolf', sex='male')
        obs = build_monster_observation(mon, 5, 5)
        mon.current_map = None
        return len(obs)
    except Exception:
        return MONSTER_OBSERVATION_SIZE  # fallback if DB not loaded


try:
    MONSTER_OBSERVATION_SIZE = _probe_observation_size()
except Exception:
    pass
