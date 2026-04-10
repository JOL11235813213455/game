"""
Observation vector assembly for the creature RL system.

Converts a creature's current state + surroundings into a flat
numeric vector (~714 floats) for neural net input.

See docs/nn_inputs_full.txt for the complete variable specification.
"""
from __future__ import annotations
import math
from classes.stats import Stat, BASE_STATS, DERIVED_STATS
from classes.maps import MapKey

MAX_ENGAGED = 6       # engaged creature slots
MAX_TILE_ITEMS = 3    # items on current tile to detail

# Derived stat list in stable order for consistent indexing
_DERIVED_ORDER = [
    Stat.HP_MAX, Stat.MELEE_DMG, Stat.RANGED_DMG, Stat.MAGIC_DMG,
    Stat.ACCURACY, Stat.CRIT_CHANCE, Stat.CRIT_DMG, Stat.DODGE,
    Stat.ARMOR, Stat.BLOCK, Stat.MOVE_SPEED, Stat.SIGHT_RANGE,
    Stat.HEARING_RANGE, Stat.STEALTH, Stat.DETECTION, Stat.CARRY_WEIGHT,
    Stat.MAX_STAMINA, Stat.MAX_MANA, Stat.MANA_REGEN, Stat.STAM_REGEN,
    Stat.HP_REGEN_DELAY, Stat.POISON_RESIST, Stat.DISEASE_RESIST,
    Stat.MAGIC_RESIST, Stat.STAGGER_RESIST, Stat.FEAR_RESIST,
    Stat.PERSUASION, Stat.INTIMIDATION, Stat.DECEPTION,
    Stat.COMPANION_LIMIT, Stat.CRAFT_QUALITY, Stat.LOOT_GINI,
    Stat.XP_MOD, Stat.DURABILITY_USE, Stat.BARTER_MOD, Stat.NPC_DISPOSITION,
]

_BASE_ORDER = [Stat.STR, Stat.VIT, Stat.AGL, Stat.PER, Stat.INT, Stat.CHR, Stat.LCK]

# Section sizes for validation
_SECTION_SIZES = {
    'self_base': 14, 'self_derived': 36, 'self_resources': 6,
    'self_combat': 17, 'self_economy': 20, 'self_slots': 14,
    'self_weapon': 15, 'self_inv_texture': 13, 'self_crafting': 6,
    'self_social': 10, 'self_status': 16, 'self_quest': 10,
    'self_goal': 21, 'self_movement': 8,
    'self_genetics': 7, 'self_reputation': 6,
    'tile_deep': 18, 'tile_liquid': 25, 'spatial_walls': 25, 'spatial_features': 12,
    'tile_items': MAX_TILE_ITEMS * 9, 'census': 45, 'census_audio': 3,
    'world_time': 13, 'temporal': 14, 'trends': 11, 'time_since': 12,
    'reward_signals': 17,
}
# Per-engaged and identity are variable (species/deity count)
PER_ENGAGED_SIZE = 45
IDENTITY_BASE_SIZE = 14  # before species one-hot + deity


def _dmod(val):
    return (val - 10) // 2


def _ln(x):
    return math.log(max(0.001, x))


def _sln(x):
    """Signed ln: sign(x) * ln(|x| + 1)."""
    if x == 0:
        return 0.0
    return math.copysign(math.log(abs(x) + 1), x)


def _ratio(cur, mx):
    return cur / mx if mx > 0 else 0.0


def _clamp(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


def _sigmoid(x):
    """Squash to 0-1."""
    return 1.0 / (1.0 + math.exp(-max(-20, min(20, x))))


def _recip(x, cap=10.0):
    """Urgency transform: 1/x, capped."""
    if x <= 0:
        return cap
    return min(cap, 1.0 / x)


def _signed_sq(x):
    """Sign-preserving square: amplifies extremes."""
    return math.copysign(x * x, x)


def _pos_transforms(x, norm=1.0):
    """Return [raw, ln, sqrt, sq] for a positive value. Normalized by norm."""
    v = x / norm if norm > 0 else x
    return [
        v,                                         # raw normalized
        math.log(x + 1) / math.log(norm + 2),     # ln (scaled to ~0-1)
        math.sqrt(max(0, v)),                      # sqrt
        min(4.0, v * v),                           # squared (capped)
    ]


def _ratio_transforms(r):
    """Return [raw, sq, recip, logit] for a 0-1 ratio."""
    return [
        r,                                         # raw
        r * r,                                     # squared (amplifies high end)
        min(10.0, 1.0 / max(0.01, r)),            # reciprocal (urgency when low)
        _sln(r - 0.5) * 2,                        # centered signed-ln
    ]


def _signed_transforms(x, scale=10.0):
    """Return [sigmoid, signed_sq, raw_clamped] for a signed value."""
    return [
        _sigmoid(x / max(1, scale)),               # sigmoid to 0-1
        _signed_sq(x / max(1, scale)),             # amplify extremes
        _clamp(x / max(1, scale)),                 # raw clamped -1 to 1
    ]


def _dist_transforms(d, max_d):
    """Return [raw, ln, recip] for a distance value."""
    norm = d / max(1, max_d)
    return [
        norm,                                      # raw normalized
        math.log(d + 1) / math.log(max_d + 2),    # ln
        min(5.0, 1.0 / max(0.1, d)) if d > 0 else 5.0,  # urgency when close
    ]


def build_observation(creature, cols: int, rows: int,
                      prev_snapshot: dict | None = None,
                      game_clock=None,
                      world_data=None,
                      trend_10: dict | None = None,
                      trend_100: dict | None = None,
                      time_since: dict | None = None) -> list[float]:
    """Build the full observation vector.

    Returns list of floats (~714 elements).
    """
    from classes.world_object import WorldObject
    from classes.creature import Creature
    from classes.inventory import (
        Weapon, Wearable, Consumable, Ammunition, Egg, Equippable, Slot,
    )

    obs = []
    _section_starts = {}  # populated during build for mask system
    stats = creature.stats
    s = stats.active  # shorthand

    # ==== SECTION 1: SELF BASE STATS (14) ====
    _section_starts['self_base'] = len(obs)
    for st in _BASE_ORDER:
        val = s[st]()
        obs.append(val / 20.0)
        obs.append(_dmod(val) / 5.0)

    # ==== SECTION 2: SELF DERIVED STATS (36) ====
    _norms = {
        Stat.HP_MAX: 50, Stat.MELEE_DMG: 20, Stat.RANGED_DMG: 20,
        Stat.MAGIC_DMG: 20, Stat.ACCURACY: 20, Stat.CRIT_CHANCE: 100,
        Stat.CRIT_DMG: 20, Stat.DODGE: 20, Stat.ARMOR: 20, Stat.BLOCK: 20,
        Stat.MOVE_SPEED: 10, Stat.SIGHT_RANGE: 15, Stat.HEARING_RANGE: 10,
        Stat.STEALTH: 20, Stat.DETECTION: 20, Stat.CARRY_WEIGHT: 200,
        Stat.MAX_STAMINA: 100, Stat.MAX_MANA: 100, Stat.MANA_REGEN: 10,
        Stat.STAM_REGEN: 10, Stat.HP_REGEN_DELAY: 10,
        Stat.POISON_RESIST: 20, Stat.DISEASE_RESIST: 20,
        Stat.MAGIC_RESIST: 20, Stat.STAGGER_RESIST: 20, Stat.FEAR_RESIST: 20,
        Stat.PERSUASION: 20, Stat.INTIMIDATION: 20, Stat.DECEPTION: 20,
        Stat.COMPANION_LIMIT: 5, Stat.CRAFT_QUALITY: 10,
        Stat.LOOT_GINI: 1, Stat.XP_MOD: 1, Stat.DURABILITY_USE: 20,
        Stat.BARTER_MOD: 10, Stat.NPC_DISPOSITION: 10,
    }
    for st in _DERIVED_ORDER:
        obs.append(s[st]() / _norms.get(st, 20))

    # ==== SECTION 3: SELF CURRENT RESOURCES (10) ====
    hp_max = max(1, s[Stat.HP_MAX]())
    hp_cur = s[Stat.HP_CURR]()
    stam_max = max(1, s[Stat.MAX_STAMINA]())
    stam_cur = s[Stat.CUR_STAMINA]()
    mana_max = max(1, s[Stat.MAX_MANA]())
    mana_cur = s[Stat.CUR_MANA]()
    obs.append(_ratio(hp_cur, hp_max))
    obs.append(hp_cur / 50.0)
    obs.append(_ratio(stam_cur, stam_max))
    obs.append(stam_cur / 100.0)
    obs.append(_ratio(mana_cur, mana_max))
    obs.append(mana_cur / 100.0)
    # Regen state booleans
    obs.append(1.0 if creature.is_regenerating_hp else 0.0)
    obs.append(1.0 if creature.hp_regen_ready else 0.0)
    obs.append(1.0 if creature.is_regenerating_stamina else 0.0)
    obs.append(1.0 if creature.is_regenerating_mana else 0.0)

    # ==== SECTION 4: SELF COMBAT READINESS (17) ====
    weapon = creature.equipment.get(Slot.HAND_R) or creature.equipment.get(Slot.HAND_L)
    if weapon and isinstance(weapon, Weapon):
        w_dmg = weapon.damage + s[Stat.MELEE_DMG]()
        w_cost = max(5, 10 - _dmod(s[Stat.STR]()))
        w_time = weapon.attack_time_ms / 1000.0
        swings = max(1, stam_cur // max(1, w_cost))
        melee_dps = w_dmg * swings / max(0.1, w_time * swings) if swings > 0 else 0
        w_range = weapon.range
    else:
        w_dmg = max(1, s[Stat.MELEE_DMG]())
        w_cost = 5
        swings = max(1, stam_cur // 5)
        melee_dps = w_dmg * swings / max(0.1, 0.5 * swings)
        w_range = 1

    has_ranged = weapon is not None and isinstance(weapon, Weapon) and w_range > 1
    has_ammo = False
    if has_ranged and weapon.ammunition_type:
        for it in creature.inventory.items:
            if isinstance(it, Ammunition) and it.name == weapon.ammunition_type and it.quantity > 0:
                has_ammo = True
                break

    # Spell readiness
    known_spells = creature.get_known_spells() if hasattr(creature, 'get_known_spells') else []
    can_cast = False
    best_spell_dmg = 0
    has_heal_spell = False
    has_buff_spell = False
    from data.db import SPELLS
    for sk in known_spells:
        sp = SPELLS.get(sk)
        if sp:
            if mana_cur >= sp.get('mana_cost', 999):
                can_cast = True
            if sp.get('effect_type') == 'damage':
                best_spell_dmg = max(best_spell_dmg, sp.get('damage', 0))
            if sp.get('effect_type') == 'heal':
                has_heal_spell = True
            if sp.get('effect_type') == 'buff':
                has_buff_spell = True

    obs.append(melee_dps / 20.0)  # effective_melee_dps
    obs.append(0.0)  # effective_ranged_dps (simplified)
    obs.append(best_spell_dmg / 20.0 if can_cast else 0.0)  # spell dps
    obs.append(swings / 10.0)  # swings_until_exhausted
    obs.append(0.0)  # casts_until_oom (simplified)
    obs.append(1.0 if stam_cur >= w_cost else 0.0)  # can_melee
    obs.append(1.0 if has_ranged and has_ammo and stam_cur >= 3 else 0.0)  # can_ranged
    obs.append(1.0 if can_cast else 0.0)
    obs.append(1.0 if stam_cur >= 15 else 0.0)  # can_grapple
    obs.append(1.0 if stam_cur >= 3 else 0.0)  # can_flee
    obs.append(1.0 if stam_cur >= 3 else 0.0)  # can_run
    obs.append(1.0 if stam_cur >= 1 else 0.0)  # can_sneak
    obs.append(1.0 if stam_cur >= 2 else 0.0)  # can_guard
    # Defensive estimates
    dodge_val = s[Stat.DODGE]()
    armor_val = s[Stat.ARMOR]()
    obs.append(max(0, min(1, 0.5 + dodge_val * 0.025)))  # dodge_rate
    obs.append(max(0, min(1, armor_val / 20.0)))  # armor_rate
    max_hit = getattr(creature, '_max_hit_taken', 0)
    obs.append(hp_cur / max(1, max_hit) if max_hit > 0 else 10.0)  # hits_until_dead
    obs.append(max_hit / max(1, hp_max))  # max_hit_ratio

    # ==== SECTION 5: SELF ECONOMY (20) ====
    gold = creature.gold
    now_approx = 0  # simplified — caller can pass
    total_debt = creature.total_debt(now_approx) if hasattr(creature, 'total_debt') else 0
    disp = creature.disposable_wealth(now_approx) if hasattr(creature, 'disposable_wealth') else gold
    inv_value = sum(getattr(i, 'value', 0) for i in creature.inventory.items)
    eq_value = sum(getattr(i, 'value', 0) for i in set(creature.equipment.values()))
    eq_kpi = 0  # simplified — full KPI calc is expensive

    obs.append(gold / 100.0)
    obs.append(_ln(gold + 1) / 10.0)
    obs.append(total_debt / 100.0)
    obs.append(_ln(total_debt + 1) / 10.0)
    obs.append(_sln(disp) / 10.0)
    obs.append(disp / max(1, gold) if gold > 0 else 0.0)
    obs.append(len(creature.loans) / 5.0)
    obs.append(len(creature.loans_given) / 5.0)
    obs.append(max((l['principal'] for l in creature.loans.values()), default=0) / 100.0)
    obs.append(max((l['principal'] for l in creature.loans_given.values()), default=0) / 100.0)
    avg_rate = (sum(l['rate'] for l in creature.loans.values()) / max(1, len(creature.loans))
                if creature.loans else 0)
    obs.append(avg_rate)
    obs.append(_ln(inv_value + 1) / 10.0)
    obs.append(len(creature.inventory.items) / 20.0)
    obs.append(_ln(eq_kpi + 1) / 10.0)
    obs.append(_ln(eq_value + 1) / 10.0)
    obs.append((14 - len(creature.equipment)) / 14.0)
    carried = creature.carried_weight
    carry_max = max(1, s[Stat.CARRY_WEIGHT]())
    obs.append(carried / carry_max)
    obs.append(1.0 if carried + 1 < carry_max else 0.0)
    obs.append(max((getattr(i, 'value', 0) for i in creature.inventory.items), default=0) / 50.0)
    obs.append(sum(1 for i in creature.inventory.items if getattr(i, 'value', 0) > 10) / 10.0)

    # ==== SECTION 6: SELF EQUIPMENT SLOTS (14) ====
    for slot in [Slot.HEAD, Slot.NECK, Slot.SHOULDERS, Slot.CHEST, Slot.BACK,
                 Slot.WRISTS, Slot.HANDS, Slot.WAIST, Slot.LEGS, Slot.FEET,
                 Slot.RING_L, Slot.RING_R, Slot.HAND_L, Slot.HAND_R]:
        obs.append(1.0 if slot in creature.equipment else 0.0)

    # ==== SECTION 7: SELF WEAPON/AMMO/SPELL (15) ====
    if weapon and isinstance(weapon, Weapon):
        obs.append(weapon.damage / 20.0)
        obs.append(weapon.range / 10.0)
        obs.append(weapon.attack_time_ms / 1000.0)
        obs.append(weapon.durability_current / max(1, weapon.durability_max))
    else:
        obs.extend([0.0, 0.0, 0.0, 0.0])
    obs.append(1.0 if has_ranged else 0.0)
    obs.append(1.0 if has_ammo else 0.0)
    ammo_qty = 0
    for it in creature.inventory.items:
        if isinstance(it, Ammunition):
            ammo_qty += it.quantity
    obs.append(ammo_qty / 50.0)
    consumables = [i for i in creature.inventory.items if isinstance(i, Consumable)]
    obs.append(len(consumables) / 10.0)
    obs.append(max((getattr(c, 'damage', 0) for c in consumables), default=0) / 20.0)
    obs.append(1.0 if any(c.buffs for c in consumables) else 0.0)
    obs.append(len(known_spells) / 10.0)
    obs.append(1.0 if can_cast else 0.0)
    obs.append(best_spell_dmg / 20.0)
    obs.append(1.0 if has_heal_spell else 0.0)
    obs.append(1.0 if has_buff_spell else 0.0)

    # ==== SECTION 8: SELF INVENTORY TEXTURE (13) ====
    obs.append(sum(1 for i in creature.inventory.items if isinstance(i, Weapon)) / 5.0)
    obs.append(sum(1 for i in creature.inventory.items if isinstance(i, Wearable)) / 5.0)
    obs.append(sum(1 for i in creature.inventory.items if isinstance(i, Egg)) / 3.0)
    obs.append(0.0)  # trap items (no type flag yet)
    obs.append(0.0)  # best_weapon_kpi (expensive)
    obs.append(0.0)  # best_armor_kpi (expensive)
    obs.append(0.0)  # has_unequipped_upgrade (expensive)
    # Equipment durability
    equip_durs = [e.durability_current / max(1, e.durability_max)
                  for e in set(creature.equipment.values())
                  if hasattr(e, 'durability_current')]
    obs.append(sum(equip_durs) / max(1, len(equip_durs)) if equip_durs else 1.0)
    obs.append(1.0 if any(d < 0.2 for d in equip_durs) else 0.0)
    obs.append(sum(1 for i in creature.inventory.items if hasattr(i, 'quantity')) / 20.0)
    obs.append(1.0 if any(getattr(i, 'value', 0) > 5 for i in creature.inventory.items) else 0.0)
    obs.append(min((getattr(i, 'value', 99) for i in creature.inventory.items), default=0) / 50.0)
    armor_durs = [e.durability_current / max(1, e.durability_max)
                  for e in set(creature.equipment.values())
                  if isinstance(e, Wearable) and hasattr(e, 'durability_current')]
    obs.append(sum(armor_durs) / max(1, len(armor_durs)) if armor_durs else 1.0)

    # ==== SECTION 8b: SELF CRAFTING READINESS (6) ====
    from classes.inventory import ItemFrame as _ItemFrame
    frames_in_inv = [i for i in creature.inventory.items if isinstance(i, _ItemFrame)]
    has_frame = len(frames_in_inv) > 0
    best_completion = max((f.completion_ratio for f in frames_in_inv), default=0.0)
    can_craft = any(f.is_complete for f in frames_in_inv)
    has_shovel = any(getattr(i, 'name', '').lower() in ('shovel', 'spade', 'pickaxe')
                     for i in creature.inventory.items + list(set(creature.equipment.values())))
    can_disassemble = any(isinstance(i, _ItemFrame) and i.ingredients.items
                          for i in creature.inventory.items)
    obs.append(1.0 if has_frame else 0.0)
    obs.append(best_completion)
    obs.append(1.0 if can_craft else 0.0)
    obs.append(1.0 if has_shovel else 0.0)
    obs.append(1.0 if can_disassemble else 0.0)
    obs.append(s[Stat.CRAFT_QUALITY]() / 10.0)

    # ==== SECTION 9: SELF SOCIAL CAPITAL (10) ====
    pos_rels = [r for r in creature.relationships.values() if r[0] > 0]
    neg_rels = [r for r in creature.relationships.values() if r[0] < 0]
    all_rels = list(creature.relationships.values())
    obs.append(sum(r[0] for r in pos_rels) / max(1, len(pos_rels)) / 10.0 if pos_rels else 0.0)
    obs.append(sum(r[0] for r in neg_rels) / max(1, len(neg_rels)) / 10.0 if neg_rels else 0.0)
    obs.append(sum(r[1] for r in all_rels) / max(1, len(all_rels)) / 20.0 if all_rels else 0.0)
    if len(all_rels) > 1:
        mean_s = sum(r[0] for r in all_rels) / len(all_rels)
        var = sum((r[0] - mean_s)**2 for r in all_rels) / len(all_rels)
        obs.append(var**0.5 / 10.0)
    else:
        obs.append(0.0)
    obs.append(0.0)  # most_recent_interaction ticks (need tracking)
    obs.append(0.0)  # betrayals_committed (need tracking)
    obs.append(0.0)  # betrayals_received (need tracking)
    obs.append(sum(len(v) for v in creature.rumors.values()) / 20.0)
    obs.append(0.0)  # rumors_spread (need tracking)
    obs.append(0.0)  # pending_conversations (expensive)

    # ==== SECTION 10: SELF STATUS/REPRODUCTION (16) ====
    obs.append(1.0 if getattr(creature, 'is_sleeping', False) else 0.0)
    obs.append(1.0 if getattr(creature, 'is_guarding', False) else 0.0)
    obs.append(1.0 if getattr(creature, 'is_blocking', False) else 0.0)
    obs.append(1.0 if creature.is_pregnant else 0.0)
    obs.append(1.0 if creature.has_partner else 0.0)
    obs.append(1.0 if getattr(creature, 'is_mother', False) else 0.0)
    obs.append(1.0 if creature.is_fertile else 0.0)
    obs.append(1.0 if creature.dialogue is not None else 0.0)
    obs.append(1.0 if getattr(creature, '_pair_cooldown', 0) > 0 else 0.0)
    obs.append(getattr(creature, '_fatigue_level', 0) / 4.0)
    obs.append(getattr(creature, 'sleep_debt', 0) / 4.0)
    obs.append(creature.piety)
    obs.append(creature.fecundity() if hasattr(creature, 'fecundity') else 0.0)
    has_egg = any(isinstance(i, Egg) for i in creature.inventory.items)
    obs.append(1.0 if has_egg else 0.0)
    egg = next((i for i in creature.inventory.items if isinstance(i, Egg)), None)
    obs.append(egg.gestation_days / 30.0 if egg else 0.0)
    obs.append(1.0 if egg and egg.is_abomination else 0.0)

    # ==== SECTION 11: SELF QUEST/PROGRESSION (10) ====
    obs.append(len(creature.quest_log.get_active_quests()) / 5.0)
    obs.append(getattr(creature, '_quests_completed', 0) / 10.0)
    obs.append(0.0)  # failed_quests
    obs.append(getattr(creature, '_quest_steps_completed', 0) / 20.0)
    obs.append(stats.base.get(Stat.LVL, 0) / 20.0)
    obs.append(stats.unspent_stat_points / 10.0)
    # XP ratio to next level
    from classes.levels import level_from_exp, cumulative_exp
    lvl = stats.base.get(Stat.LVL, 0)
    exp = stats.base.get(Stat.EXP, 0)
    curr_exp = cumulative_exp(lvl)
    next_exp = cumulative_exp(lvl + 1)
    obs.append((exp - curr_exp) / max(1, next_exp - curr_exp))
    obs.append(creature.life_goal_attainment / 10.0)
    obs.append(creature.failed_actions / 10.0)
    obs.append(getattr(creature, '_tiles_explored', 0) / 100.0)

    # ==== SECTION 11b: SELF GOAL STATE (NUM_PURPOSES + 4) ====
    from classes.actions import TILE_PURPOSES as _PURPOSES
    # Goal one-hot
    curr_goal = getattr(creature, 'current_goal', None)
    for p in _PURPOSES:
        obs.append(1.0 if curr_goal == p else 0.0)
    # Goal distance and direction
    goal_dist = creature.goal_distance() if hasattr(creature, 'goal_distance') else float('inf')
    obs.append(min(goal_dist, 50) / 50.0)
    goal_dir = creature.direction_to_goal() if hasattr(creature, 'direction_to_goal') else (0, 0)
    obs.append(goal_dir[0])  # dx normalized to -1/0/1
    obs.append(goal_dir[1])  # dy normalized to -1/0/1
    obs.append(1.0 if hasattr(creature, 'at_goal') and creature.at_goal() else 0.0)

    # ==== SECTION 12: SELF MOVEMENT/POSITION (8) ====
    cx, cy = creature.location.x, creature.location.y
    map_w = max(1, cols)
    map_h = max(1, rows)
    center_dist = (abs(cx - map_w//2) + abs(cy - map_h//2)) / max(1, map_w + map_h)
    obs.append(center_dist)
    obs.append(1.0 if cx == 0 or cx >= cols-1 or cy == 0 or cy >= rows-1 else 0.0)
    tile = creature.current_map.tiles.get(creature.location)
    obs.append(1.0 if tile and tile.linked_map else 0.0)
    obs.append(1.0 if tile and tile.nested_map else 0.0)
    obs.append(len(creature.map_stack) / 5.0)
    entrance = MapKey(*creature.current_map.entrance, 0)
    obs.append(1.0 if creature.location == entrance and creature.map_stack else 0.0)
    obs.append(0.0)  # ticks_on_current_tile (need tracking)
    obs.append(0.0)  # ticks_on_current_map (need tracking)

    # ==== SECTION 13: SELF GENETICS (7) ====
    if creature.chromosomes:
        from classes.genetics import express
        gen_mods = express(creature.chromosomes)
        for st in _BASE_ORDER:
            obs.append(gen_mods.get(st, 0) / 3.0)
    else:
        obs.extend([0.0] * 7)

    # ==== SECTION 14: SELF SIZE/SPECIES/DEITY/IDENTITY (25+ values) ====
    from classes.creature import SIZE_CATEGORIES
    for sz in SIZE_CATEGORIES:
        obs.append(1.0 if creature.size == sz else 0.0)
    obs.append(1.0 if creature.sex == 'male' else 0.0)
    obs.append(1.0 if creature.sex == 'female' else 0.0)
    obs.append(1.0 if creature.is_child else 0.0)
    obs.append(1.0 if creature.is_adult else 0.0)
    obs.append(1.0 if creature.is_abomination else 0.0)
    obs.append(1.0 if getattr(creature, 'inbred', False) else 0.0)
    obs.append(creature.age / max(1, creature.OLD_MIN))
    obs.append(max(0, creature.age - 18) / max(1, creature.OLD_MIN - 18))
    # Species one-hot (just human for now)
    obs.append(1.0 if creature.species == 'human' else 0.0)
    # Deity one-hot
    _gods = ['Aelora','Xarith','Solmara','Vaelkor','Verithan','Nyssara','Sylvaine','Mortheus']
    obs.append(1.0 if creature.deity is None else 0.0)
    for g in _gods:
        obs.append(1.0 if creature.deity == g else 0.0)

    # ==== SECTION 15: SELF REPUTATION SUMMARY (6) ====
    # sumproduct(sentiment, depth) / sum(depth)
    depths = [r[1] / (r[1] + 5) for r in all_rels]
    sents = [r[0] for r in all_rels]
    sum_depth = sum(depths)
    rep_utility = sum(s * d for s, d in zip(sents, depths)) / max(0.001, sum_depth)
    obs.append(rep_utility / 20.0)
    obs.append(len(creature.relationships) / 20.0)
    obs.append(len(pos_rels) / 10.0)
    obs.append(len(neg_rels) / 10.0)
    obs.append(sum(1 for r in all_rels if r[0] > 5) / 10.0)
    obs.append(sum(1 for r in all_rels if r[0] < -5) / 10.0)

    # ==== BUILD VISIBLE/AUDIBLE CREATURE LISTS ====
    game_map = creature.current_map
    sight = max(1, s[Stat.SIGHT_RANGE]())
    hearing = max(1, s[Stat.HEARING_RANGE]())

    visible = []
    heard_only = []
    for obj in WorldObject.on_map(game_map):
        if not isinstance(obj, Creature) or obj is creature or not obj.is_alive:
            continue
        dist = abs(cx - obj.location.x) + abs(cy - obj.location.y)
        stealth = obj.stats.active[Stat.STEALTH]()
        eff_sight = sight - stealth
        if dist <= eff_sight:
            visible.append((dist, obj))
        elif dist <= hearing:
            heard_only.append((dist, obj))

    visible.sort(key=lambda x: x[0])

    # ==== SECTION 16: CURRENT TILE DEEP (18) ====
    obs.append(1.0 if tile and getattr(tile, 'covered', False) else 0.0)
    obs.append(creature.location.z / 5.0)
    obs.append(getattr(tile, 'speed_modifier', 1.0) if tile else 1.0)
    tile_items = tile.inventory.items if tile else []
    obs.append(len(tile_items) / 10.0)
    obs.append(_ln(sum(getattr(i, 'value', 0) for i in tile_items) + 1) / 10.0)
    tile_gold = getattr(tile, 'gold', 0) if tile else 0
    obs.append(_ln(tile_gold + 1) / 10.0)  # gold on ground
    obs.append(1.0 if tile_gold > 0 else 0.0)  # has gold flag
    obs.append(1.0 if any(isinstance(i, Egg) for i in tile_items) else 0.0)
    obs.append(1.0 if any(isinstance(i, Weapon) for i in tile_items) else 0.0)
    obs.append(1.0 if any(isinstance(i, Consumable) for i in tile_items) else 0.0)
    # Capacity
    from classes.creature import SIZE_UNITS, TILE_CAPACITY
    used = sum(SIZE_UNITS.get(getattr(o, 'size', 'medium'), 4)
               for _, o in visible if o.location == creature.location)
    obs.append(used / TILE_CAPACITY)
    obs.append(sum(1 for _, o in visible if o.location == creature.location) / 5.0)
    trap_dc = tile.stat_mods.get('trap_dc') if tile else None
    obs.append(1.0 if trap_dc else 0.0)
    obs.append((trap_dc or 0) / 20.0)
    obs.append(1.0 if tile and tile.linked_map else 0.0)
    obs.append(1.0 if tile and tile.nested_map else 0.0)
    bg = getattr(tile, 'bg_color', None)
    if bg and isinstance(bg, str) and len(bg) == 7 and bg[0] == '#':
        obs.append(int(bg[1:3], 16) / 255.0)
        obs.append(int(bg[3:5], 16) / 255.0)
        obs.append(int(bg[5:7], 16) / 255.0)
    else:
        obs.extend([0.5, 0.5, 0.5])
    obs.append(1.0 if tile_items else 0.0)

    # ==== SECTION 16b: TILE LIQUID / WATER (10) ====
    is_liquid = getattr(tile, 'liquid', False) if tile else False
    obs.append(1.0 if is_liquid else 0.0)
    flow_dir = getattr(tile, 'flow_direction', None) if tile else None
    obs.append(1.0 if flow_dir == 'N' else 0.0)
    obs.append(1.0 if flow_dir == 'S' else 0.0)
    obs.append(1.0 if flow_dir == 'E' else 0.0)
    obs.append(1.0 if flow_dir == 'W' else 0.0)
    obs.append(getattr(tile, 'flow_speed', 0) / 10.0 if tile else 0.0)
    obs.append(getattr(tile, 'depth', 0) / 3.0 if tile else 0.0)
    obs.append(1.0 if getattr(creature, 'is_drowning', False) else 0.0)
    obs.append(1.0 if getattr(creature, 'can_swim', False) else 0.0)
    buried_count = len(tile.buried_inventory.items) if tile and hasattr(tile, 'buried_inventory') else 0
    obs.append(1.0 if buried_count > 0 or getattr(tile, 'buried_gold', 0) > 0 else 0.0)
    # Tile purpose one-hot
    from classes.actions import TILE_PURPOSES
    tile_purpose = getattr(tile, 'purpose', None) if tile else None
    for p in TILE_PURPOSES:
        obs.append(1.0 if tile_purpose == p else 0.0)

    # ==== SECTION 17: SPATIAL WALLS + OPENNESS (25) ====
    _dirs8 = [(0,-1),(0,1),(1,0),(-1,0),(1,-1),(-1,-1),(1,1),(-1,1)]
    for dx, dy in _dirs8:
        d = 0
        for step in range(1, sight + 1):
            t = game_map.tiles.get(MapKey(cx + dx*step, cy + dy*step, creature.location.z))
            if t and t.walkable:
                d = step
            else:
                break
        obs.append(d / max(1, sight))

    for dx, dy in _dirs8:
        t = game_map.tiles.get(MapKey(cx+dx, cy+dy, creature.location.z))
        obs.append(1.0 if t and t.walkable else 0.0)

    # Ring walkability
    for ring in range(1, 4):
        ring_tiles = 0
        ring_walk = 0
        for ddx in range(-ring, ring+1):
            for ddy in range(-ring, ring+1):
                if abs(ddx) == ring or abs(ddy) == ring:
                    ring_tiles += 1
                    t = game_map.tiles.get(MapKey(cx+ddx, cy+ddy, creature.location.z))
                    if t and t.walkable:
                        ring_walk += 1
        obs.append(ring_walk / max(1, ring_tiles))

    # Chokepoint detection
    adj_walk = sum(1 for dx, dy in _dirs8[:4]
                   if game_map.tiles.get(MapKey(cx+dx, cy+dy, creature.location.z))
                   and game_map.tiles[MapKey(cx+dx, cy+dy, creature.location.z)].walkable)
    obs.append(1.0 if adj_walk <= 2 else 0.0)
    obs.append(1.0 if adj_walk >= 6 else 0.0)
    obs.append(1.0 if adj_walk <= 2 else 0.0)  # corner approx

    # Direction to nearest exit
    nearest_exit_dx, nearest_exit_dy = 0.0, 0.0
    # Simplified: skip exit scan for performance

    obs.append(nearest_exit_dx)
    obs.append(nearest_exit_dy)

    # ==== SECTION 18: SPATIAL FEATURE LOCATIONS (12) ====
    # Directions to features (simplified averages)
    def _avg_dir(targets):
        if not targets:
            return 0.0, 0.0
        dx = sum(t[1].location.x - cx for t in targets) / len(targets)
        dy = sum(t[1].location.y - cy for t in targets) / len(targets)
        mag = max(1, abs(dx) + abs(dy))
        return dx/mag, dy/mag

    enemies = [(d, c) for d, c in visible
               if creature.relationships.get(c.uid) and creature.relationships[c.uid][0] < -5]
    allies = [(d, c) for d, c in visible
              if creature.relationships.get(c.uid) and creature.relationships[c.uid][0] > 5]

    # Items direction (skip — expensive tile scan)
    obs.extend([0.0, 0.0])

    ex, ey = _avg_dir(enemies)
    obs.append(ex); obs.append(ey)
    ax, ay = _avg_dir(allies)
    obs.append(ax); obs.append(ay)
    obs.extend([0.0, 0.0])  # structures direction
    obs.append(0.0)  # num_linked_tiles
    obs.append(0.0)  # num_structures
    obs.append(0.0)  # tiles_with_items
    obs.append(len(visible) / 10.0)  # tiles_with_creatures (approx)

    # Crowding metrics — local density within 3-tile radius
    crowd_radius = 3
    nearby_count = sum(1 for d, c in visible if d <= crowd_radius)
    obs.append(nearby_count / 8.0)  # normalized local density
    obs.append(1.0 if nearby_count >= 5 else 0.0)  # overcrowded flag
    # Direction AWAY from crowd center (flee vector)
    if nearby_count > 0:
        nearby = [(c.location.x, c.location.y) for d, c in visible if d <= crowd_radius]
        crowd_cx = sum(nx for nx, ny in nearby) / len(nearby)
        crowd_cy = sum(ny for nx, ny in nearby) / len(nearby)
        flee_dx = cx - crowd_cx
        flee_dy = cy - crowd_cy
        flee_mag = max(1.0, abs(flee_dx) + abs(flee_dy))
        obs.append(flee_dx / flee_mag)
        obs.append(flee_dy / flee_mag)
    else:
        obs.append(0.0)
        obs.append(0.0)

    # ==== SECTION 19: TILE ITEMS TOP 3 (27) ====
    sorted_items = sorted(tile_items, key=lambda i: getattr(i, 'value', 0), reverse=True)
    for idx in range(MAX_TILE_ITEMS):
        if idx < len(sorted_items):
            it = sorted_items[idx]
            obs.append(getattr(it, 'value', 0) / 50.0)
            obs.append(1.0 if isinstance(it, Weapon) else 0.0)
            obs.append(1.0 if isinstance(it, Wearable) else 0.0)
            obs.append(1.0 if isinstance(it, Consumable) else 0.0)
            obs.append(1.0 if isinstance(it, Egg) else 0.0)
            obs.append(1.0 if isinstance(it, Ammunition) else 0.0)
            obs.append(getattr(it, 'weight', 0) / 20.0)
            obs.append(0.0)  # kpi_for_me (expensive)
            obs.append(0.0)  # is_upgrade (expensive)
        else:
            obs.extend([0.0] * 9)

    # ==== SECTION 20: CENSUS VISIBLE (45) ====
    v_creatures = [c for _, c in visible]
    n_vis = len(v_creatures)
    obs.append(n_vis / 20.0)
    obs.append(sum(1 for c in v_creatures if c.species == creature.species) / 20.0)
    obs.append(sum(1 for c in v_creatures if c.species != creature.species) / 20.0)
    obs.append(sum(1 for c in v_creatures if c.sex == 'male') / 20.0)
    obs.append(sum(1 for c in v_creatures if c.sex == 'female') / 20.0)
    obs.append(sum(1 for c in v_creatures if c.sex == 'male' and c.species == creature.species) / 20.0)
    obs.append(sum(1 for c in v_creatures if c.sex == 'female' and c.species == creature.species) / 20.0)
    obs.append(sum(1 for c in v_creatures if c.is_child) / 20.0)
    obs.append(sum(1 for c in v_creatures if c.is_adult) / 20.0)
    n_allies = sum(1 for c in v_creatures if creature.relationships.get(c.uid) and creature.relationships[c.uid][0] > 5)
    n_enemies = sum(1 for c in v_creatures if creature.relationships.get(c.uid) and creature.relationships[c.uid][0] < -5)
    obs.append(n_allies / 10.0)
    obs.append(n_enemies / 10.0)
    obs.append((n_vis - n_allies - n_enemies) / 10.0)
    obs.append(sum(1 for c in v_creatures if c.deity == creature.deity and creature.deity) / 10.0)
    obs.append(0.0)  # opposed_deity (need god lookup)
    obs.append(sum(1 for c in v_creatures if c.equipment) / 10.0)
    obs.append(sum(1 for c in v_creatures if c.is_pregnant) / 10.0)
    obs.append(sum(1 for c in v_creatures if getattr(c, 'is_sleeping', False)) / 10.0)
    obs.append(sum(1 for c in v_creatures if c.is_abomination) / 10.0)
    obs.append(sum(c.stats.active[Stat.HP_CURR]() / max(1, c.stats.active[Stat.HP_MAX]())
                   for c in v_creatures) / max(1, n_vis))
    dists = [d for d, _ in visible]
    obs.append(sum(dists) / max(1, len(dists)) / max(1, sight))
    obs.append(min(dists) / max(1, sight) if dists else 1.0)
    ally_dists = [d for d, c in visible if creature.relationships.get(c.uid) and creature.relationships[c.uid][0] > 5]
    enemy_dists = [d for d, c in visible if creature.relationships.get(c.uid) and creature.relationships[c.uid][0] < -5]
    obs.append(min(ally_dists) / max(1, sight) if ally_dists else 1.0)
    obs.append(min(enemy_dists) / max(1, sight) if enemy_dists else 1.0)
    same_sp_dists = [d for d, c in visible if c.species == creature.species]
    obs.append(min(same_sp_dists) / max(1, sight) if same_sp_dists else 1.0)
    opp_sex_dists = [d for d, c in visible if c.sex != creature.sex]
    obs.append(min(opp_sex_dists) / max(1, sight) if opp_sex_dists else 1.0)
    obs.append(sum(1 for d, c in visible
                   if c.equipment and creature.relationships.get(c.uid)
                   and creature.relationships[c.uid][0] < -5) / 5.0)
    obs.append(sum(c.stats.active[Stat.HP_CURR]() for d, c in enemies) / 100.0 if enemies else 0.0)
    obs.append(sum(c.stats.active[Stat.HP_CURR]() for d, c in allies) / 100.0 if allies else 0.0)
    obs.append(1.0 if n_enemies > n_allies + 1 else 0.0)
    obs.append(1.0 if n_allies > n_enemies + 1 else 0.0)
    my_hp_max = hp_max
    obs.append(1.0 if all(my_hp_max >= c.stats.active[Stat.HP_MAX]() for c in v_creatures) and v_creatures else 0.0)
    obs.append(1.0 if all(my_hp_max <= c.stats.active[Stat.HP_MAX]() for c in v_creatures) and v_creatures else 0.0)
    obs.append(sum(1 for c in v_creatures
                   if c.sex != creature.sex and c.is_adult and not c.is_pregnant
                   and c.species == creature.species) / 5.0)
    obs.append(sum(1 for i in tile_items if isinstance(i, Egg)) / 5.0)  # eggs_visible (approx)
    obs.append(sum(1 for c in v_creatures
                   if getattr(creature, 'mother_uid', None) == c.uid
                   or getattr(creature, 'father_uid', None) == c.uid
                   or getattr(c, 'mother_uid', None) == creature.uid
                   or getattr(c, 'father_uid', None) == creature.uid) / 3.0)
    obs.append(sum(1 for c in v_creatures
                   if c.uid == getattr(creature, 'mother_uid', None)
                   or c.uid == getattr(creature, 'father_uid', None)) / 2.0)
    obs.append(1.0 if creature.partner_uid and any(c.uid == creature.partner_uid for c in v_creatures) else 0.0)
    obs.append(sum(1 for c in v_creatures if c.uid in creature.loans_given) / 5.0)
    obs.append(sum(1 for c in v_creatures if c.uid in creature.loans) / 5.0)
    obs.append(creature.attractiveness_rank_nearby() if hasattr(creature, 'attractiveness_rank_nearby') else 0.5)
    obs.append(creature.pairing_eagerness() if hasattr(creature, 'pairing_eagerness') else 0.0)
    obs.append(1.0 if creature.deity and sum(1 for c in v_creatures if c.deity == creature.deity) >
               sum(1 for c in v_creatures if c.deity and c.deity != creature.deity) else 0.0)
    obs.append(0.0)  # avg_visible_wealth (expensive)
    obs.append(0.0)  # avg_piety_my_god
    obs.append(0.0)  # avg_piety_opposed

    # ==== SECTION 21: CENSUS AUDIBLE (3) ====
    obs.append(len(heard_only) / 10.0)
    if heard_only:
        hdx = sum(c.location.x - cx for _, c in heard_only) / len(heard_only)
        hdy = sum(c.location.y - cy for _, c in heard_only) / len(heard_only)
        hmag = max(1, abs(hdx) + abs(hdy))
        obs.append(hdx / hmag)
        obs.append(hdy / hmag)
    else:
        obs.extend([0.0, 0.0])

    # ==== SECTION 22: PER-ENGAGED CREATURE (45 × 6 = 270) ====
    engaged = visible[:MAX_ENGAGED]
    for idx in range(MAX_ENGAGED):
        if idx < len(engaged):
            dist, other = engaged[idx]
            dx = other.location.x - cx
            dy = other.location.y - cy
            mag = max(1, abs(dx) + abs(dy))
            rel = creature.relationships.get(other.uid)
            other_rel = other.relationships.get(creature.uid)

            obs.append(dist / max(1, sight))
            obs.append(dx / mag)
            obs.append(dy / mag)
            obs.append(_clamp(rel[0] / 20.0) if rel else 0.0)
            obs.append(_clamp(other_rel[0] / 20.0) if other_rel else 0.0)
            obs.append(rel[1] / (rel[1] + 5) if rel else 0.0)
            obs.append(1.0 / (1 + rel[1]) if rel else 1.0)
            obs.append(_clamp(creature.rumor_opinion(other.uid, 0) / 10.0))
            other_hp = other.stats.active[Stat.HP_CURR]() / max(1, other.stats.active[Stat.HP_MAX]())
            obs.append(other_hp)
            obs.append(1.0 if other.equipment else 0.0)
            obs.append(1.0 if other.species == creature.species else 0.0)
            obs.append(1.0 if other.deity == creature.deity and creature.deity else 0.0)
            obs.append(1.0 if creature.deity and other.deity and
                       creature.deity != other.deity else 0.0)  # opposed (simplified)
            obs.append(1.0 if other.sex == 'male' else 0.0)
            obs.append(1.0 if other.sex == 'female' else 0.0)
            obs.append(1.0 if other.is_child else 0.0)
            obs.append(1.0 if other.uid == getattr(creature, 'mother_uid', None)
                       or other.uid == getattr(creature, 'father_uid', None) else 0.0)
            obs.append(1.0 if getattr(other, 'mother_uid', None) == creature.uid
                       or getattr(other, 'father_uid', None) == creature.uid else 0.0)
            obs.append(1.0 if other.uid == creature.partner_uid else 0.0)
            obs.append(1.0 if other.is_pregnant else 0.0)
            obs.append(1.0 if other.is_abomination else 0.0)
            obs.append(1.0 if getattr(other, 'is_sleeping', False) else 0.0)
            obs.append(1.0 if getattr(other, 'is_guarding', False) else 0.0)
            obs.append(1.0 if getattr(other, 'is_blocking', False) else 0.0)
            obs.append(_ln(creature.debt_owed_to(other.uid, 0) + 1) / 5.0
                       if hasattr(creature, 'debt_owed_to') else 0.0)
            obs.append(_ln(other.debt_owed_to(creature.uid, 0) + 1) / 5.0
                       if hasattr(other, 'debt_owed_to') else 0.0)
            for sz in SIZE_CATEGORIES:
                obs.append(1.0 if other.size == sz else 0.0)
            obs.append(other.age / max(1, creature.OLD_MIN))
            obs.append(1.0 if other_hp < 0.5 else 0.0)
            obs.append(1.0 if other_hp < 0.2 else 0.0)
            obs.append(1.0 if len(other.equipment) > 3 else 0.0)  # appears_wealthy
            obs.append(1.0 if len(other.equipment) <= 1 else 0.0)  # appears_poor
            # Could kill estimates
            obs.append(0.0)  # could_kill_me (expensive)
            obs.append(0.0)  # i_could_kill_them (expensive)
            obs.append(0.0)  # fleeing_from_me (need last-tick tracking)
            obs.append(0.0)  # approaching_me (need tracking)
            other_allies = sum(1 for c in v_creatures
                               if other.relationships.get(c.uid) and other.relationships[c.uid][0] > 5)
            obs.append(1.0 if other_allies > 0 else 0.0)
            obs.append(other_allies / 5.0)
            obs.append(creature.desirability(other, creature)
                       if hasattr(creature, 'desirability') else 0.0)
            obs.append(1.0 if (other.sex != creature.sex and other.is_adult
                               and not other.is_pregnant
                               and other.species == creature.species) else 0.0)
        else:
            obs.extend([0.0] * PER_ENGAGED_SIZE)

    # ==== SECTION 23: WORLD / TIME (13) ====
    if game_clock:
        h = game_clock.hour
        obs.append(math.sin(h / 24.0 * 2 * math.pi))
        obs.append(math.cos(h / 24.0 * 2 * math.pi))
        obs.append(1.0 if game_clock.is_day else 0.0)
        obs.append(game_clock.sun_elevation)
        obs.append(game_clock.moon_elevation)
        obs.append(game_clock.moon_brightness)
        obs.append(game_clock.moon_phase)
        obs.append(game_clock.day / 365.0)
        light = game_clock.sun_elevation if game_clock.is_day else game_clock.moon_brightness * game_clock.moon_elevation
        obs.append(light)
    else:
        obs.extend([0.0] * 9)

    if world_data:
        for pair in [('Aelora','Xarith'), ('Solmara','Vaelkor'),
                     ('Verithan','Nyssara'), ('Sylvaine','Mortheus')]:
            obs.append(world_data.get_balance(pair[0]))
    else:
        obs.extend([0.0] * 4)

    # ==== SECTION 24: TEMPORAL IMMEDIATE (14) ====
    prev = prev_snapshot or {}
    obs.append(_ratio(hp_cur, hp_max) - prev.get('hp_ratio', _ratio(hp_cur, hp_max)))
    obs.append(_ratio(stam_cur, stam_max) - prev.get('stam_ratio', _ratio(stam_cur, stam_max)))
    obs.append(_ratio(mana_cur, mana_max) - prev.get('mana_ratio', _ratio(mana_cur, mana_max)))
    obs.append(_sln(gold - prev.get('gold', gold)) / 5.0)
    obs.append((rep_utility - prev.get('rep_utility', rep_utility)) / 10.0)
    prev_threat = prev.get('closest_threat', 999)
    closest_threat = min(enemy_dists) if enemy_dists else 999
    obs.append((closest_threat - prev_threat) / max(1, sight))
    obs.append(creature.piety - prev.get('piety', creature.piety))
    obs.append(_sln(eq_kpi - prev.get('eq_kpi', eq_kpi)) / 5.0)
    obs.append(_sln(inv_value - prev.get('inv_value', inv_value)) / 5.0)
    obs.append((n_allies - prev.get('allies', n_allies)))
    obs.append(_sln(total_debt - prev.get('debt', total_debt)) / 5.0)
    obs.append(min(1.0, getattr(creature, '_kills', 0) - prev.get('kills', getattr(creature, '_kills', 0))))
    obs.append(min(1.0, getattr(creature, '_quest_steps_completed', 0) - prev.get('quest_steps', getattr(creature, '_quest_steps_completed', 0))))
    obs.append(1.0 if stats.base.get(Stat.EXP, 0) > prev.get('exp', stats.base.get(Stat.EXP, 0)) else 0.0)

    # ==== SECTION 25+26: TEMPORAL TRANSFORMS FROM HISTORY ====
    # Rich temporal features: ln ratios, volatility, streaks, time-since-events
    from classes.temporal import (
        generate_temporal_transforms, generate_time_since,
        make_history_snapshot,
    )
    if hasattr(creature, '_history') and creature._history:
        current_snap = make_history_snapshot(creature,
                                            visible_enemies=enemies,
                                            visible_allies=allies)
        obs.extend(generate_temporal_transforms(creature._history, current_snap))
        current_tick = 0  # simplified — caller should pass via prev_snapshot
        obs.extend(generate_time_since(creature, current_tick))
    else:
        # No history yet — output zeros
        from classes.temporal import TOTAL_TEMPORAL_SIZE
        obs.extend([0.0] * TOTAL_TEMPORAL_SIZE)

    # ==== SECTION 27: REWARD SIGNAL VALUES (17) ====
    obs.append(_ratio(hp_cur, hp_max))
    obs.append(_ln(gold + 1) / 10.0)
    obs.append(_ln(total_debt + 1) / 10.0)
    obs.append(_ln(inv_value + 1) / 10.0)
    obs.append(_ln(eq_kpi + 1) / 10.0)
    obs.append(rep_utility / 20.0)
    obs.append(n_allies / 10.0)
    obs.append(getattr(creature, '_kills', 0) / 10.0)
    obs.append(getattr(creature, '_tiles_explored', 0) / 100.0)
    obs.append(len(creature.relationships) / 20.0)
    obs.append(creature.piety)
    obs.append(getattr(creature, '_quest_steps_completed', 0) / 10.0)
    obs.append(creature.life_goal_attainment / 10.0)
    obs.append(getattr(creature, '_fatigue_level', 0) / 4.0)
    obs.append(creature.failed_actions / 10.0)
    obs.append(1.0 if disp < 0 else 0.0)
    obs.append(1.0 if stats.base.get(Stat.EXP, 0) > prev.get('exp', 0) else 0.0)

    # ==== SECTION 28: WILD TRANSFORMS ====
    # Multiple mathematical representations of key variables.
    # Gives the net different "lenses" on the same data.

    # HP ratio transforms: [raw, sq, recip(urgency), centered-ln]
    obs.extend(_ratio_transforms(_ratio(hp_cur, hp_max)))

    # Stamina ratio transforms
    obs.extend(_ratio_transforms(_ratio(stam_cur, stam_max)))

    # Mana ratio transforms
    obs.extend(_ratio_transforms(_ratio(mana_cur, mana_max)))

    # Gold transforms: [raw, ln, sqrt, sq]
    obs.extend(_pos_transforms(gold, norm=100))

    # Debt transforms
    obs.extend(_pos_transforms(total_debt, norm=100))

    # Inventory value transforms
    obs.extend(_pos_transforms(inv_value, norm=100))

    # Equipment value transforms
    obs.extend(_pos_transforms(eq_value, norm=100))

    # HP raw transforms (absolute HP matters differently than ratio)
    obs.extend(_pos_transforms(hp_cur, norm=50))

    # Stamina raw transforms
    obs.extend(_pos_transforms(stam_cur, norm=100))

    # Mana raw transforms
    obs.extend(_pos_transforms(mana_cur, norm=100))

    # Base stat transforms (each stat: [raw, sq, dmod_sigmoid])
    for st in _BASE_ORDER:
        val = s[st]()
        dm = _dmod(val)
        obs.append(val * val / 400.0)                  # squared / 400
        obs.append(_sigmoid(dm))                        # sigmoid of dmod

    # Reputation transforms: [sigmoid, signed_sq, clamped]
    obs.extend(_signed_transforms(rep_utility, scale=20))

    # Sentiment extremes transforms
    best_sent = max((r[0] for r in all_rels), default=0)
    worst_sent = min((r[0] for r in all_rels), default=0)
    obs.extend(_signed_transforms(best_sent, scale=20))
    obs.extend(_signed_transforms(worst_sent, scale=20))

    # Distance to threats: transforms for closest enemy
    closest_enemy_dist = min(enemy_dists) if enemy_dists else float(sight)
    obs.extend(_dist_transforms(closest_enemy_dist, sight))

    # Distance to allies
    closest_ally_dist = min(ally_dists) if ally_dists else float(sight)
    obs.extend(_dist_transforms(closest_ally_dist, sight))

    # Age transforms: [raw, ln, sqrt]
    obs.extend(_pos_transforms(creature.age, norm=creature.OLD_MIN))

    # Carried weight ratio transforms
    cw_ratio = carried / max(1, carry_max)
    obs.extend(_ratio_transforms(min(1.0, cw_ratio)))

    # Key interaction terms (products of important variables)
    obs.append(_ratio(hp_cur, hp_max) * _ratio(stam_cur, stam_max))  # combat readiness
    obs.append(_ratio(hp_cur, hp_max) * _ratio(mana_cur, mana_max))  # caster readiness
    obs.append(gold * n_allies / max(1, 100 * 10))                   # total capital
    obs.append(melee_dps / 20.0 * _ratio(stam_cur, stam_max))       # effective attack power
    obs.append(creature.piety * (1.0 if creature.deity else 0.0))    # religious commitment
    obs.append(n_enemies / max(1, n_allies + 1))                     # threat ratio
    obs.append(_ratio(hp_cur, hp_max) * (1.0 - getattr(creature, '_fatigue_level', 0) / 4.0))  # effective health
    obs.append(creature.age / max(1, creature.OLD_MIN) * creature.fecundity()
               if hasattr(creature, 'fecundity') else 0.0)           # reproductive value

    # God balance transforms (signed: -1 to 1 for each axis)
    if world_data:
        for pair in [('Aelora','Xarith'), ('Solmara','Vaelkor'),
                     ('Verithan','Nyssara'), ('Sylvaine','Mortheus')]:
            bal = world_data.get_balance(pair[0])
            obs.extend(_signed_transforms(bal, scale=1.0))
            # My god's alignment with this axis
            if creature.deity in pair:
                obs.append(bal if creature.deity == pair[0] else -bal)
            else:
                obs.append(0.0)
    else:
        obs.extend([0.0] * 16)  # 4 axes × (3 transforms + 1 personal)

    # Piety interaction with world balance
    if world_data and creature.deity:
        my_balance = world_data.get_balance(creature.deity)
        obs.append(my_balance * creature.piety)               # world favors my god × my devotion
        obs.append(abs(my_balance) * creature.piety)          # world polarization × my devotion
        obs.append(1.0 if my_balance > 0 else 0.0)           # is my god winning
    else:
        obs.extend([0.0] * 3)

    return obs


# Observation size — will be set after first call
OBSERVATION_SIZE = None  # set dynamically below


def _compute_observation_size():
    """Compute actual observation size by building one observation."""
    from classes.maps import Map, Tile
    from classes.creature import Creature
    tiles = {MapKey(x, y, 0): Tile(walkable=True) for x in range(5) for y in range(5)}
    m = Map(tile_set=tiles, entrance=(0, 0), x_max=5, y_max=5)
    c = Creature(current_map=m, location=MapKey(2, 2, 0), name='_size_probe',
                 stats={Stat.STR: 10, Stat.VIT: 10, Stat.AGL: 10, Stat.PER: 10,
                        Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10})
    obs = build_observation(c, 5, 5)
    # Clean up probe objects from Trackable registry
    c.current_map = None
    return len(obs)


try:
    OBSERVATION_SIZE = _compute_observation_size()
except Exception:
    OBSERVATION_SIZE = 800  # fallback


# ---------------------------------------------------------------------------
# Section index registry — for observation masking
# ---------------------------------------------------------------------------

SECTION_RANGES = {
    'self_base':        (0, 14),
    'self_derived':     (14, 50),
    'self_resources':   (50, 60),       # +4 regen booleans
    'self_combat':      (60, 77),
    'self_economy':     (77, 97),
    'self_slots':       (97, 111),
    'self_weapon':      (111, 126),
    'self_inv_texture': (126, 139),
    'self_crafting':    (139, 145),
    'self_social':      (145, 155),
    'self_status':      (155, 171),
    'self_quest':       (171, 181),
    'self_goal':        (181, 202),
    'self_movement':    (202, 210),
    'self_genetics':    (210, 217),
    'self_identity':    (217, 242),
    'self_reputation':  (242, 248),
    'tile_deep':        (248, 266),
    'tile_liquid':      (266, 291),
    'spatial_walls':    (291, 316),
    'spatial_features': (316, 332),     # +4 crowding metrics
    'tile_items':       (332, 359),
    'census_visible':   (359, 404),
    'census_audible':   (404, 407),
    'per_engaged':      (407, 677),
    'world_time':       (677, 690),
    'temporal':         (690, 704),
    'trends':           (704, 715),
    'time_since':       (715, 727),
    'reward_signals':   (727, 744),
    'transforms':       (744, OBSERVATION_SIZE),
}

# Semantic groups for easy mask building
SECTION_GROUPS = {
    'social': ['self_social', 'self_reputation', 'census_visible',
               'census_audible', 'per_engaged'],
    'combat': ['self_combat', 'self_weapon'],
    'vision': ['spatial_walls', 'spatial_features', 'tile_deep', 'tile_items',
               'census_visible', 'per_engaged'],
    'hearing': ['census_audible'],
    'economy': ['self_economy', 'self_inv_texture', 'self_crafting', 'self_slots'],
    'religion': ['world_time'],  # god balances are in world_time + transforms
    'memory': ['temporal', 'trends', 'time_since'],
    'quest': ['self_quest', 'self_goal'],
    'spatial': ['self_movement', 'spatial_walls', 'spatial_features', 'tile_deep', 'tile_liquid'],
    'reproduction': ['self_status', 'self_genetics'],
}


def apply_mask(obs: list[float], mask: set[str],
               scale: float = 0.0) -> list[float]:
    """Zero out (or scale) observation sections.

    Args:
        obs: the full observation vector
        mask: set of section names or group names to zero
        scale: what to multiply masked values by (0.0 = full zero, 0.5 = halved)

    Returns:
        modified observation (same list, mutated in place)
    """
    # Expand group names to section names
    sections_to_mask = set()
    for name in mask:
        if name in SECTION_GROUPS:
            sections_to_mask.update(SECTION_GROUPS[name])
        elif name in SECTION_RANGES:
            sections_to_mask.add(name)

    for section in sections_to_mask:
        rng = SECTION_RANGES.get(section)
        if rng is None:
            continue
        start, end = rng
        end = min(end, len(obs))
        for i in range(start, end):
            obs[i] *= scale

    return obs


# ---------------------------------------------------------------------------
# Preset masks — neurodivergent / impaired creatures
# ---------------------------------------------------------------------------

PRESET_MASKS = {
    # Social processing disorders
    'socially_deaf': {
        'sections': {'social'},
        'scale': 0.0,
        'description': 'Cannot read social landscape — no sentiment, reputation, or relationship awareness',
    },
    'socially_impaired': {
        'sections': {'self_social', 'self_reputation'},
        'scale': 0.5,
        'description': 'Reduced social awareness — sentiment halved, relationships dim',
    },
    'antisocial': {
        'sections': {'self_social', 'self_reputation', 'self_quest'},
        'scale': 0.0,
        'description': 'No social awareness or quest motivation',
    },

    # Sensory impairments
    'blind': {
        'sections': {'vision'},
        'scale': 0.0,
        'description': 'Cannot see — no spatial, tile, census, or per-creature visual info',
    },
    'deaf': {
        'sections': {'hearing'},
        'scale': 0.0,
        'description': 'Cannot hear — no audible creature detection',
    },
    'blind_deaf': {
        'sections': {'vision', 'hearing'},
        'scale': 0.0,
        'description': 'Cannot see or hear',
    },

    # Cognitive impairments
    'amnesiac': {
        'sections': {'memory'},
        'scale': 0.0,
        'description': 'No memory of past events — no trends, no time-since tracking',
    },
    'impulsive': {
        'sections': {'trends', 'time_since', 'self_quest'},
        'scale': 0.0,
        'description': 'No long-term planning — no trends, no quest awareness',
    },

    # Emotional / behavioral
    'fearless': {
        'sections': {'self_combat'},
        'scale': 0.0,
        'description': 'Cannot assess threats — no combat readiness awareness',
    },
    'greedy': {
        'sections': {'social', 'self_quest', 'reproduction'},
        'scale': 0.0,
        'description': 'Only sees economic signals — pure wealth accumulator',
    },
    'zealot': {
        'sections': {'economy', 'self_quest', 'self_combat'},
        'scale': 0.0,
        'description': 'Only religion matters — ignores economy, quests, combat assessment',
    },
    'feral': {
        'sections': {'social', 'economy', 'self_quest', 'religion'},
        'scale': 0.0,
        'description': 'Pure animal — no social, economic, quest, or religious awareness',
    },

    # Partial impairments
    'nearsighted': {
        'sections': {'spatial_walls', 'spatial_features'},
        'scale': 0.3,
        'description': 'Reduced spatial awareness — can see nearby but not far',
    },
    'paranoid': {
        'sections': {'self_social'},
        'scale': -1.0,  # inverts social signals!
        'description': 'Social signals inverted — perceives friends as threats',
    },
}


def apply_preset_mask(obs: list[float], preset_name: str) -> list[float]:
    """Apply a named preset mask to an observation."""
    preset = PRESET_MASKS.get(preset_name)
    if preset is None:
        return obs
    return apply_mask(obs, preset['sections'], preset['scale'])


def make_snapshot(creature, visible_enemies=None) -> dict:
    """Capture current state for temporal deltas next tick."""
    stats = creature.stats
    hp_max = max(1, stats.active[Stat.HP_MAX]())
    stam_max = max(1, stats.active[Stat.MAX_STAMINA]())
    mana_max = max(1, stats.active[Stat.MAX_MANA]())
    inv_value = sum(getattr(i, 'value', 0) for i in creature.inventory.items)

    # Reputation utility
    all_rels = list(creature.relationships.values())
    depths = [r[1] / (r[1] + 5) for r in all_rels]
    sents = [r[0] for r in all_rels]
    sum_depth = sum(depths)
    rep_utility = sum(s * d for s, d in zip(sents, depths)) / max(0.001, sum_depth) if all_rels else 0.0

    n_allies = sum(1 for r in all_rels if r[0] > 5)

    return {
        'hp_ratio': stats.active[Stat.HP_CURR]() / hp_max,
        'stam_ratio': stats.active[Stat.CUR_STAMINA]() / stam_max,
        'mana_ratio': stats.active[Stat.CUR_MANA]() / mana_max,
        'gold': creature.gold,
        'rep_utility': rep_utility,
        'closest_threat': 999,  # caller fills from visible enemies
        'piety': creature.piety,
        'eq_kpi': 0,  # simplified
        'inv_value': inv_value,
        'allies': n_allies,
        'debt': creature.total_debt(0) if hasattr(creature, 'total_debt') else 0,
        'kills': getattr(creature, '_kills', 0),
        'quest_steps': getattr(creature, '_quest_steps_completed', 0),
        'exp': creature.stats.base.get(Stat.EXP, 0),
    }
