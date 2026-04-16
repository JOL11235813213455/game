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
from classes.relationship_graph import GRAPH

MAX_ENGAGED = 10      # persistent perception slots for top visible creatures
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
    'self_social': 10, 'self_status': 16, 'self_hunger': 6, 'self_quest': 10,
    'self_goal': 21, 'self_schedule': 10, 'self_movement': 8,
    'self_genetics': 7, 'self_reputation': 6,
    'tile_deep': 21, 'tile_liquid': 25, 'spatial_walls': 25, 'spatial_features': 12,
    'tile_items': MAX_TILE_ITEMS * 9, 'census': 45, 'census_audio': 3,
    'world_time': 6, 'monster_slots': 30, 'monster_summary': 3,
    'temporal': 14, 'trends': 11, 'time_since': 12,
    'reward_signals': 17, 'social_topology': 17, 'water_awareness': 5,
    'hearing_section': 12,
}
# Per-engaged and identity are variable (species/deity count)
PER_ENGAGED_SIZE = 51  # grew from 45: 4 placeholder zeros replaced + 6 new fields
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
    """Return [raw, ln, sqrt, sq] for a positive value. Normalized by norm.

    Hardened against negative inputs: ``hp_cur``, ``gold``, etc. can
    briefly be negative on damage/over-pay before subsequent logic
    clamps them. ``math.log`` of a non-positive number raises
    ValueError, which would crash the entire training process during
    the next observation build.
    """
    x = max(0.0, x)
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
    """Return [raw, ln, recip] for a distance value.

    Hardened against negative inputs: distance computations should
    never go below zero, but a degenerate setup (e.g. computing
    distance to a creature whose location is None) could pass a
    negative or NaN value through. ``math.log`` of a non-positive
    number crashes the training process.
    """
    d = max(0.0, d)
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
                      time_since: dict | None = None,
                      observation_tick: int | None = None) -> list[float]:
    """Build the full observation vector.

    Returns list of floats (~714 elements).
    """
    from classes.world_object import WorldObject
    from classes.creature import Creature
    from classes.inventory import (
        Weapon, Wearable, Consumable, Ammunition, Egg, Equippable, Slot,
    )

    obs = []
    # Local section-start registry updated during build. The most recent
    # build's offsets are copied into the module-level _LAST_SECTION_STARTS
    # on return so SECTION_RANGES can be refreshed lazily.
    _section_starts = {}
    stats = creature.stats
    s = stats.active  # shorthand

    # ---- Cache stat callables (huge win: stat lookups dominate profile) ----
    # Call each stat's getter ONCE and reuse the scalar. Base stats are
    # each referenced many times across the function; derived stats are
    # each referenced 1-5 times.
    _base_vals = [s[st]() for st in _BASE_ORDER]
    _STR, _VIT, _AGL, _PER, _INT, _CHR, _LCK = _base_vals
    _derived_vals = {st: s[st]() for st in _DERIVED_ORDER}
    hp_max_raw = _derived_vals[Stat.HP_MAX]
    hp_max = max(1, hp_max_raw)
    hp_cur = s[Stat.HP_CURR]()
    stam_max_raw = _derived_vals[Stat.MAX_STAMINA]
    stam_max = max(1, stam_max_raw)
    stam_cur = s[Stat.CUR_STAMINA]()
    mana_max_raw = _derived_vals[Stat.MAX_MANA]
    mana_max = max(1, mana_max_raw)
    mana_cur = s[Stat.CUR_MANA]()
    sight = max(1, _derived_vals[Stat.SIGHT_RANGE])
    hearing = max(1, _derived_vals[Stat.HEARING_RANGE])
    melee_dmg_val = _derived_vals[Stat.MELEE_DMG]
    dodge_val = _derived_vals[Stat.DODGE]
    armor_val = _derived_vals[Stat.ARMOR]
    carry_max = max(1, _derived_vals[Stat.CARRY_WEIGHT])
    craft_quality_val = _derived_vals[Stat.CRAFT_QUALITY]

    # ---- Cache relationships (hot path) ----
    rels = GRAPH.edges_from(creature.uid)
    rels_list = list(rels.values())

    # ==== SECTION 1: SELF BASE STATS (14) ====
    _section_starts['self_base'] = len(obs)
    for val in _base_vals:
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
        obs.append(_derived_vals[st] / _norms.get(st, 20))

    # ==== SECTION 3: SELF CURRENT RESOURCES (10) ====
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
        w_dmg = weapon.damage + melee_dmg_val
        w_cost = max(5, 10 - _dmod(_STR))
        w_time = weapon.attack_time_ms / 1000.0
        swings = max(1, stam_cur // max(1, w_cost))
        melee_dps = w_dmg * swings / max(0.1, w_time * swings) if swings > 0 else 0
        w_range = weapon.range
    else:
        w_dmg = max(1, melee_dmg_val)
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
    obs.append(craft_quality_val / 10.0)

    # ==== SECTION 9: SELF SOCIAL CAPITAL (10) ====
    # Single-pass aggregation over relationships (was: 5+ separate scans).
    _pos_sum = 0.0
    _pos_ct = 0
    _neg_sum = 0.0
    _neg_ct = 0
    _depth_sum = 0
    _sent_sum = 0.0
    _n_rels = len(rels_list)
    for _r in rels_list:
        _s0 = _r[0]
        _depth_sum += _r[1]
        _sent_sum += _s0
        if _s0 > 0:
            _pos_sum += _s0
            _pos_ct += 1
        elif _s0 < 0:
            _neg_sum += _s0
            _neg_ct += 1
    pos_rels_count = _pos_ct
    neg_rels_count = _neg_ct
    all_rels = rels_list
    obs.append(_pos_sum / max(1, _pos_ct) / 10.0 if _pos_ct else 0.0)
    obs.append(_neg_sum / max(1, _neg_ct) / 10.0 if _neg_ct else 0.0)
    obs.append(_depth_sum / max(1, _n_rels) / 20.0 if _n_rels else 0.0)
    if _n_rels > 1:
        mean_s = _sent_sum / _n_rels
        var = sum((_r[0] - mean_s)**2 for _r in rels_list) / _n_rels
        obs.append(var**0.5 / 10.0)
    else:
        obs.append(0.0)
    obs.append(0.0)  # most_recent_interaction ticks (need tracking)
    obs.append(GRAPH.outstanding_lies(creature.uid) / 10.0)
    obs.append(len(GRAPH.deceits_against(creature.uid)) / 10.0)
    obs.append(GRAPH.count_rumors_held(creature.uid) / 20.0)
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

    # ==== SECTION 10a2: CONDITIONS (Phase 1 FSM) — 17 floats ====
    # For each of the 8 canonical conditions: (is_active, severity_norm).
    # Plus one float for the compound action_state index, normalized.
    # Keeps the NN aware of poison/stun/sleep/blessing etc. without
    # requiring per-condition one-hot (2 dense features per condition).
    _section_starts['self_conditions'] = len(obs)
    from classes.conditions import CONDITION_ORDER, CONDITION_SPECS
    conds = getattr(creature, 'conditions', None) or {}
    for _cname in CONDITION_ORDER:
        _c = conds.get(_cname)
        if _c is None:
            obs.append(0.0)
            obs.append(0.0)
        else:
            _spec = CONDITION_SPECS[_cname]
            obs.append(1.0)
            obs.append(_c.severity / max(1, _spec.max_severity))
    # Compound action-state index: normal=0, stunned=1, sleeping=2, dead=3.
    # Normalized to 0..1 for NN-friendliness. When the FSM hasn't been
    # built yet (no conditions ever applied), default to 'normal'.
    _ACTION_STATE_IDX = {'normal': 0, 'stunned': 1, 'sleeping': 2, 'dead': 3}
    _ast = getattr(creature, 'action_state', None)
    _astate_name = _ast.current if _ast is not None else 'normal'
    obs.append(_ACTION_STATE_IDX.get(_astate_name, 0) / 3.0)

    # ==== SECTION 10b: SELF HUNGER (6) ====
    hunger = getattr(creature, 'hunger', 0.0)
    obs.append(hunger)                                           # raw: -1 to 1
    obs.append(max(0, hunger))                                   # positive only (satiation)
    obs.append(max(0, -hunger))                                  # negative only (hunger urgency)
    obs.append(1.0 if hunger > 0.5 else 0.0)                    # well-fed flag
    obs.append(1.0 if hunger < -0.5 else 0.0)                   # starving flag
    # Desperation: nonlinear escalator for sub-zero hunger.
    # 0.0 at hunger >= 0, ramps quickly toward 1.0 as hunger -> -1.
    # Gives the policy a salient "panic" signal independent of the linear urgency.
    desperation = max(0.0, -hunger) ** 0.5
    obs.append(desperation)

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

    # ==== SECTION 11c: SELF JOB / SCHEDULE (10) ====
    # Gives the NN time-of-day awareness and job context so it can learn
    # "do my job at work during work hours, sleep at night, free otherwise."
    job = getattr(creature, 'job', None)
    schedule = getattr(creature, 'schedule', None)
    cur_hour = game_clock.hour if game_clock else 12.0
    activity = schedule.activity_at(cur_hour) if schedule else 'open'
    obs.append(1.0 if job is not None else 0.0)                       # has_job
    obs.append(1.0 if activity == 'sleep' else 0.0)                   # activity one-hot: sleep
    obs.append(1.0 if activity == 'work' else 0.0)                    #                    work
    obs.append(1.0 if activity == 'open' else 0.0)                    #                    open
    # At workplace? (purpose matches job's workplace purposes)
    _tile = creature.current_map.tiles.get(creature.location) if creature.current_map else None
    _tp = getattr(_tile, 'purpose', None) if _tile else None
    at_workplace = 1.0 if (job and _tp and _tp in job.workplace_purposes) else 0.0
    obs.append(at_workplace)
    # Ready to work: at workplace AND in work hours — the "should JOB now" signal
    obs.append(1.0 if (at_workplace and activity == 'work') else 0.0)
    # Job purpose one-hot compressed to 1 float: is tile matching creature's job purpose?
    obs.append(1.0 if (job and _tp == job.purpose) else 0.0)
    # Wage bank (ln-transformed so it scales gently)
    obs.append(math.log(1 + max(0.0, getattr(creature, '_wage_accumulated', 0.0))) / 5.0)
    # Sleep pressure: 1 if in sleep hours, 0 otherwise
    obs.append(1.0 if activity == 'sleep' else 0.0)
    # Schedule variance marker: creature has a non-default schedule (future: night shift, etc.)
    obs.append(1.0 if job and job.schedule is not schedule else 0.0)

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
    # sumproduct(sentiment, depth) / sum(depth), single pass.
    _sum_d = 0.0
    _sum_sd = 0.0
    _high_pos = 0
    _high_neg = 0
    for _r in rels_list:
        _d = _r[1] / (_r[1] + 5)
        _sum_d += _d
        _sum_sd += _r[0] * _d
        if _r[0] > 5:
            _high_pos += 1
        elif _r[0] < -5:
            _high_neg += 1
    rep_utility = _sum_sd / max(0.001, _sum_d)
    obs.append(rep_utility / 20.0)
    obs.append(_n_rels / 20.0)
    obs.append(pos_rels_count / 10.0)
    obs.append(neg_rels_count / 10.0)
    obs.append(_high_pos / 10.0)
    obs.append(_high_neg / 10.0)

    # ==== BUILD VISIBLE/AUDIBLE CREATURE LISTS ====
    game_map = creature.current_map
    # sight/hearing already cached at top

    # Use the creature's per-tick cached perception when possible. The
    # cache is invalidated whenever the creature's location changes and
    # the caller passes a tick counter through observation_tick to
    # compel a rebuild once per step. Falls back to a fresh scan when
    # no cache is available (old call sites / tests).
    if hasattr(creature, 'get_perception') and observation_tick is not None:
        visible, heard_only = creature.get_perception(observation_tick)
    else:
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

    # ==== SINGLE PASS OVER VISIBLE CREATURES ====
    # Iterates the visible list ONCE and collects every downstream stat
    # in one sweep. Sections 18 (spatial_features), 20 (census), and
    # portions of 22 (per-slot) read from these pre-computed locals
    # instead of re-scanning visible multiple times.
    v_creatures = [c for _, c in visible]
    n_vis = len(v_creatures)
    _my_species = creature.species
    _my_sex = creature.sex
    _my_deity = creature.deity
    _my_uid = creature.uid
    _my_mother = getattr(creature, 'mother_uid', None)
    _my_father = getattr(creature, 'father_uid', None)
    _my_partner = creature.partner_uid
    _loans = creature.loans
    _loans_given = creature.loans_given

    c_same_sp = 0
    c_diff_sp = 0
    c_male = 0
    c_female = 0
    c_male_same = 0
    c_female_same = 0
    c_child = 0
    c_adult = 0
    n_allies = 0
    n_enemies = 0
    c_same_deity = 0
    c_equipped = 0
    c_pregnant = 0
    c_sleeping = 0
    c_abom = 0
    hp_ratio_sum = 0.0
    dist_sum = 0.0
    min_dist = None
    min_ally_dist = None
    min_enemy_dist = None
    min_same_sp_dist = None
    min_opp_sex_dist = None
    c_enemy_equipped = 0
    enemy_hp_sum = 0.0
    ally_hp_sum = 0.0
    all_ge_hp_max = True
    all_le_hp_max = True
    c_potential_mates = 0
    c_relatives = 0
    c_parents_visible = 0
    partner_visible = False
    c_debtors = 0
    c_creditors = 0
    c_deity_same_visible = 0
    c_deity_diff_visible = 0

    enemies = []  # [(d, c), ...]
    allies = []
    ally_dists = []
    enemy_dists = []

    # Per-creature data used by the per-slot loop and social topology,
    # keyed by uid. Populated in the single-pass below so downstream
    # sections can avoid re-looking-up the same fields.
    # Each entry: (hp_cur, hp_max, has_equip)
    v_data: dict = {}

    # Crowding and flee vector (section 18) accumulators
    crowd_radius = 3
    nearby_count = 0
    nearby_cx_sum = 0
    nearby_cy_sum = 0
    # Capacity used on current tile by visible creatures (section 16)
    tile_capacity_used = 0
    tile_creatures_same = 0

    from classes.creature import SIZE_UNITS as _SIZE_UNITS_CENSUS
    _my_tile_loc = creature.location

    for d, c in visible:
        c_loc = c.location
        c_stats_active = c.stats.active
        c_hp_max_val = c_stats_active[Stat.HP_MAX]()
        c_hp_cur_val = c_stats_active[Stat.HP_CURR]()
        c_species = c.species
        c_sex = c.sex
        c_deity = c.deity

        dist_sum += d
        if min_dist is None or d < min_dist:
            min_dist = d

        same_species = c_species == _my_species
        if same_species:
            c_same_sp += 1
            if min_same_sp_dist is None or d < min_same_sp_dist:
                min_same_sp_dist = d
        else:
            c_diff_sp += 1

        if c_sex == 'male':
            c_male += 1
            if same_species:
                c_male_same += 1
        elif c_sex == 'female':
            c_female += 1
            if same_species:
                c_female_same += 1

        if c_sex != _my_sex:
            if min_opp_sex_dist is None or d < min_opp_sex_dist:
                min_opp_sex_dist = d
            if c.is_adult and not c.is_pregnant and same_species:
                c_potential_mates += 1

        if c.is_child:
            c_child += 1
        if c.is_adult:
            c_adult += 1

        rel = rels.get(c.uid)
        rel_val = rel[0] if rel else 0
        has_equip = bool(c.equipment)
        # Stash the per-creature facts that the per-slot loop needs
        v_data[c.uid] = (c_hp_cur_val, c_hp_max_val, has_equip)
        if rel_val > 5:
            n_allies += 1
            allies.append((d, c))
            ally_dists.append(d)
            ally_hp_sum += c_hp_cur_val
            if min_ally_dist is None or d < min_ally_dist:
                min_ally_dist = d
        elif rel_val < -5:
            n_enemies += 1
            enemies.append((d, c))
            enemy_dists.append(d)
            enemy_hp_sum += c_hp_cur_val
            if min_enemy_dist is None or d < min_enemy_dist:
                min_enemy_dist = d
            if has_equip:
                c_enemy_equipped += 1

        if _my_deity and c_deity == _my_deity:
            c_same_deity += 1
            c_deity_same_visible += 1
        elif c_deity and c_deity != _my_deity and _my_deity:
            c_deity_diff_visible += 1

        if has_equip:
            c_equipped += 1
        if c.is_pregnant:
            c_pregnant += 1
        if getattr(c, 'is_sleeping', False):
            c_sleeping += 1
        if c.is_abomination:
            c_abom += 1

        hp_ratio_sum += c_hp_cur_val / max(1, c_hp_max_val)

        if hp_max < c_hp_max_val:
            all_ge_hp_max = False
        if hp_max > c_hp_max_val:
            all_le_hp_max = False

        c_uid = c.uid
        c_mother = getattr(c, 'mother_uid', None)
        c_father = getattr(c, 'father_uid', None)
        if (_my_mother == c_uid or _my_father == c_uid
                or c_mother == _my_uid or c_father == _my_uid):
            c_relatives += 1
        if c_uid == _my_mother or c_uid == _my_father:
            c_parents_visible += 1
        if _my_partner and c_uid == _my_partner:
            partner_visible = True
        if c_uid in _loans_given:
            c_debtors += 1
        if c_uid in _loans:
            c_creditors += 1

        # Crowding (section 18)
        if d <= crowd_radius:
            nearby_count += 1
            nearby_cx_sum += c_loc.x
            nearby_cy_sum += c_loc.y
        # Same-tile capacity (section 16)
        if c_loc == _my_tile_loc:
            tile_capacity_used += _SIZE_UNITS_CENSUS.get(getattr(c, 'size', 'medium'), 4)
            tile_creatures_same += 1

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
    # Capacity (pre-computed in single-pass)
    from classes.creature import SIZE_UNITS, TILE_CAPACITY
    obs.append(tile_capacity_used / TILE_CAPACITY)
    obs.append(tile_creatures_same / 5.0)
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
    # Resource on current tile (3)
    res_type = getattr(tile, 'resource_type', None) if tile else None
    res_amt  = getattr(tile, 'resource_amount', 0) if tile else 0
    res_max  = getattr(tile, 'resource_max', 0) if tile else 0
    obs.append(1.0 if res_type else 0.0)                                  # has_resource
    obs.append(res_amt / max(1, res_max) if res_max > 0 else 0.0)         # resource_fill (0=empty, 1=full)
    obs.append(1.0 if (res_type and res_amt <= 0) else 0.0)               # resource_depleted

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
    # Combined tile scan: purpose tiles + water tiles in ONE pass over
    # the O(sight²) diamond area. Used here for purpose distances and
    # again later in section 22c (water awareness).
    from classes.actions import TILE_PURPOSES
    _purpose_dists = {}
    water_min_d = None
    water_best = None
    item_min_d = None
    item_best = None
    food_min_d = None
    food_best = None
    _z = creature.location.z
    _tiles = game_map.tiles
    if tile:
        for ddx in range(-sight, sight + 1):
            _abs_ddx = abs(ddx)
            for ddy in range(-sight, sight + 1):
                manhat = _abs_ddx + abs(ddy)
                if manhat > sight:
                    continue
                pt = _tiles.get(MapKey(cx + ddx, cy + ddy, _z))
                if pt is None:
                    continue
                pt_purpose = getattr(pt, 'purpose', None)
                if pt_purpose:
                    if pt_purpose not in _purpose_dists or manhat < _purpose_dists[pt_purpose]:
                        _purpose_dists[pt_purpose] = manhat
                if getattr(pt, 'liquid', False) and getattr(pt, 'depth', 0) >= 1:
                    if water_min_d is None or manhat < water_min_d:
                        water_min_d = manhat
                        water_best = (ddx, ddy)
                pt_inv = pt.inventory.items
                if pt_inv or getattr(pt, 'gold', 0) > 0:
                    if item_min_d is None or manhat < item_min_d:
                        item_min_d = manhat
                        item_best = (ddx, ddy)
                    if any(getattr(i, 'is_food', False) for i in pt_inv):
                        if food_min_d is None or manhat < food_min_d:
                            food_min_d = manhat
                            food_best = (ddx, ddy)
    # Also scan visible objects with purpose (scaled by purpose_distance)
    for _dobj, obj in visible:
        obj_purpose = getattr(obj, 'purpose', None)
        if obj_purpose:
            d = abs(cx - obj.location.x) + abs(cy - obj.location.y)
            max_range = sight * getattr(obj, 'purpose_distance', 0.5)
            if d <= max_range:
                if obj_purpose not in _purpose_dists or d < _purpose_dists[obj_purpose]:
                    _purpose_dists[obj_purpose] = d
    for p in TILE_PURPOSES:
        d = _purpose_dists.get(p)
        if d is not None:
            obs.append(1.0 - min(d, sight) / sight)
        else:
            obs.append(0.0)

    # ==== SECTION 17: SPATIAL WALLS + OPENNESS (25) ====
    from classes.creature import Creature as _CreatureRef
    _tg = _CreatureRef._tile_grid
    if _tg is not None:
        _sw_vals = _tg.spatial_walls(cx, cy, sight)
        obs.extend(_sw_vals)  # all 25 floats including exit direction
    else:
        from classes.maps import DIRECTION_BOUNDS as _DB
        _dirs8 = [(0,-1),(0,1),(1,0),(-1,0),(1,-1),(-1,-1),(1,1),(-1,1)]
        for dx, dy in _dirs8:
            d = 0
            _bd = _DB.get((dx, dy))
            for step in range(1, sight + 1):
                prev = game_map.tiles.get(MapKey(cx + dx*(step-1), cy + dy*(step-1), creature.location.z))
                t = game_map.tiles.get(MapKey(cx + dx*step, cy + dy*step, creature.location.z))
                if not (t and t.walkable):
                    break
                if _bd and prev:
                    _exit, _entry = _bd
                    if not getattr(prev.bounds, _exit, True) or not getattr(t.bounds, _entry, True):
                        break
                d = step
            obs.append(d / max(1, sight))

        _cur_tile = game_map.tiles.get(creature.location)
        for dx, dy in _dirs8:
            t = game_map.tiles.get(MapKey(cx+dx, cy+dy, creature.location.z))
            passable = bool(t and t.walkable)
            if passable and _cur_tile and (dx, dy) in _DB:
                _exit, _entry = _DB[(dx, dy)]
                if not getattr(_cur_tile.bounds, _exit, True) or not getattr(t.bounds, _entry, True):
                    passable = False
            obs.append(1.0 if passable else 0.0)

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

        adj_walk = sum(1 for dx, dy in _dirs8[:4]
                       if game_map.tiles.get(MapKey(cx+dx, cy+dy, creature.location.z))
                       and game_map.tiles[MapKey(cx+dx, cy+dy, creature.location.z)].walkable)
        obs.append(1.0 if adj_walk <= 2 else 0.0)
        obs.append(1.0 if adj_walk >= 6 else 0.0)
        obs.append(1.0 if adj_walk <= 2 else 0.0)

    # Direction to nearest exit (included in TileGrid.spatial_walls when available)
    if _tg is None:
        obs.append(0.0)
        obs.append(0.0)

    # ==== SECTION 18: SPATIAL FEATURE LOCATIONS (12) ====
    # Directions reuse the enemies/allies lists pre-computed in the
    # single-pass census. _avg_dir is a single-pass reduction.
    def _avg_dir(targets):
        if not targets:
            return 0.0, 0.0
        n = len(targets)
        sx = 0
        sy = 0
        for t in targets:
            loc = t[1].location
            sx += loc.x - cx
            sy += loc.y - cy
        dx = sx / n
        dy = sy / n
        mag = max(1, abs(dx) + abs(dy))
        return dx / mag, dy / mag

    # Items direction + distance (from combined tile scan)
    if item_best is not None:
        imag = max(1, abs(item_best[0]) + abs(item_best[1]))
        obs.append(item_best[0] / imag)
        obs.append(item_best[1] / imag)
    else:
        obs.extend([0.0, 0.0])

    ex, ey = _avg_dir(enemies)
    obs.append(ex); obs.append(ey)
    ax, ay = _avg_dir(allies)
    obs.append(ax); obs.append(ay)
    # Food direction + nearest item/food distances (from combined tile scan)
    if food_best is not None:
        fmag = max(1, abs(food_best[0]) + abs(food_best[1]))
        obs.append(food_best[0] / fmag)
        obs.append(food_best[1] / fmag)
    else:
        obs.extend([0.0, 0.0])
    obs.append(item_min_d / sight if item_min_d is not None else 1.0)
    obs.append(food_min_d / sight if food_min_d is not None else 1.0)
    obs.append(1.0 if food_min_d is not None else 0.0)  # food_visible flag
    obs.append(len(visible) / 10.0)  # tiles_with_creatures (approx)

    # Crowding metrics — nearby_count/cx/cy accumulated in single-pass
    obs.append(nearby_count / 8.0)
    obs.append(1.0 if nearby_count >= 5 else 0.0)
    if nearby_count > 0:
        crowd_cx = nearby_cx_sum / nearby_count
        crowd_cy = nearby_cy_sum / nearby_count
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
    # All counts were accumulated in the single-pass earlier. This
    # section just emits them in the canonical order.
    obs.append(n_vis / 20.0)
    obs.append(c_same_sp / 20.0)
    obs.append(c_diff_sp / 20.0)
    obs.append(c_male / 20.0)
    obs.append(c_female / 20.0)
    obs.append(c_male_same / 20.0)
    obs.append(c_female_same / 20.0)
    obs.append(c_child / 20.0)
    obs.append(c_adult / 20.0)
    obs.append(n_allies / 10.0)
    obs.append(n_enemies / 10.0)
    obs.append((n_vis - n_allies - n_enemies) / 10.0)
    obs.append(c_same_deity / 10.0)
    obs.append(0.0)  # opposed_deity (need god lookup)
    obs.append(c_equipped / 10.0)
    obs.append(c_pregnant / 10.0)
    obs.append(c_sleeping / 10.0)
    obs.append(c_abom / 10.0)
    obs.append(hp_ratio_sum / max(1, n_vis))
    obs.append((dist_sum / max(1, n_vis)) / sight)
    obs.append(min_dist / sight if min_dist is not None else 1.0)
    obs.append(min_ally_dist / sight if min_ally_dist is not None else 1.0)
    obs.append(min_enemy_dist / sight if min_enemy_dist is not None else 1.0)
    obs.append(min_same_sp_dist / sight if min_same_sp_dist is not None else 1.0)
    obs.append(min_opp_sex_dist / sight if min_opp_sex_dist is not None else 1.0)
    obs.append(c_enemy_equipped / 5.0)
    obs.append(enemy_hp_sum / 100.0 if enemies else 0.0)
    obs.append(ally_hp_sum / 100.0 if allies else 0.0)
    obs.append(1.0 if n_enemies > n_allies + 1 else 0.0)
    obs.append(1.0 if n_allies > n_enemies + 1 else 0.0)
    obs.append(1.0 if all_ge_hp_max and v_creatures else 0.0)
    obs.append(1.0 if all_le_hp_max and v_creatures else 0.0)
    obs.append(c_potential_mates / 5.0)
    obs.append(sum(1 for i in tile_items if isinstance(i, Egg)) / 5.0)
    obs.append(c_relatives / 3.0)
    obs.append(c_parents_visible / 2.0)
    obs.append(1.0 if partner_visible else 0.0)
    obs.append(c_debtors / 5.0)
    obs.append(c_creditors / 5.0)
    if hasattr(creature, 'attractiveness_rank_nearby'):
        _rank = creature.attractiveness_rank_nearby()
        obs.append(_rank)
        obs.append(0.5 - _rank if _my_sex == 'male' else _rank - 0.5)
    else:
        obs.append(0.5)
        obs.append(0.0)
    obs.append(1.0 if _my_deity and c_deity_same_visible > c_deity_diff_visible else 0.0)
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

    # ==== SECTION 22: PER-SLOT CREATURE (51 x 10 = 510) ====
    # Persistent-slot design: each of the 10 slots holds a specific
    # creature uid across ticks. When a creature leaves visibility
    # their slot clears to zeros; when they return (or a new creature
    # arrives) the first empty slot is filled. This gives the NN a
    # stable per-creature signal the whole time that creature is in
    # sight, instead of a scrambled closest-sorted list.
    #
    # Size numerology per slot:
    #   base fields that were already there (kept): ~41
    #   replaced placeholder zeros with real math (same size): 4
    #   NEW fields added: 6
    #     - relative_size (my size units / their size units)
    #     - threat_them_to_me (valuation-style)
    #     - threat_me_to_them
    #     - approaching (1 if they moved toward me last tick)
    #     - fleeing (1 if they moved away)
    #     - slot_occupied (1 if this slot has a creature, else 0)
    #   Total per slot: 51. Total section: 510.
    from classes.creature import SIZE_UNITS as _SIZE_UNITS
    slot_entries = creature.update_perception_slots(visible)
    # Constants lifted out of the slot loop
    my_size_u = _SIZE_UNITS.get(creature.size, 4)
    _old_min_norm = max(1, creature.OLD_MIN)
    _my_hp_cur = hp_cur
    _has_debt = hasattr(creature, 'debt_owed_to')
    _my_rumor = creature.rumor_opinion if hasattr(creature, 'rumor_opinion') else None
    _my_desirability_fn = creature.desirability if hasattr(creature, 'desirability') else None
    _last_seen = creature._last_seen_positions
    # Keep a quick lookup of current positions so we can update the
    # last-seen table AFTER we've computed approaching/fleeing.
    new_seen: dict = {}
    for slot_idx, other, dist in slot_entries:
        if other is None:
            obs.extend([0.0] * PER_ENGAGED_SIZE)
            continue

        o_loc = other.location
        dx = o_loc.x - cx
        dy = o_loc.y - cy
        mag = max(1, abs(dx) + abs(dy))
        o_uid = other.uid
        rel = rels.get(o_uid)
        o_rels = GRAPH.edges_from(other.uid)
        other_rel = o_rels.get(_my_uid)
        o_equip = other.equipment
        o_equip_len = len(o_equip)
        o_sex = other.sex
        o_species = other.species
        o_deity = other.deity
        o_is_child = other.is_child
        o_is_pregnant = other.is_pregnant
        o_is_abom = other.is_abomination
        o_mother = getattr(other, 'mother_uid', None)
        o_father = getattr(other, 'father_uid', None)

        # Reuse census-cached HP (no extra stat getter calls)
        cached = v_data.get(o_uid)
        if cached is not None:
            their_hp_cur, their_hp_max, _cached_has_equip = cached
        else:
            o_stats_active = other.stats.active
            their_hp_cur = o_stats_active[Stat.HP_CURR]()
            their_hp_max = o_stats_active[Stat.HP_MAX]()
        other_hp = their_hp_cur / max(1, their_hp_max)

        obs.append(dist / sight)
        obs.append(dx / mag)
        obs.append(dy / mag)
        obs.append(_clamp(rel[0] / 20.0) if rel else 0.0)
        obs.append(_clamp(other_rel[0] / 20.0) if other_rel else 0.0)
        obs.append(rel[1] / (rel[1] + 5) if rel else 0.0)
        obs.append(1.0 / (1 + rel[1]) if rel else 1.0)
        obs.append(_clamp(_my_rumor(o_uid, 0) / 10.0) if _my_rumor else 0.0)
        obs.append(other_hp)
        obs.append(1.0 if o_equip else 0.0)
        obs.append(1.0 if o_species == _my_species else 0.0)
        obs.append(1.0 if o_deity == _my_deity and _my_deity else 0.0)
        obs.append(1.0 if _my_deity and o_deity and o_deity != _my_deity else 0.0)
        obs.append(1.0 if o_sex == 'male' else 0.0)
        obs.append(1.0 if o_sex == 'female' else 0.0)
        obs.append(1.0 if o_is_child else 0.0)
        obs.append(1.0 if (o_uid == _my_mother or o_uid == _my_father) else 0.0)
        obs.append(1.0 if (o_mother == _my_uid or o_father == _my_uid) else 0.0)
        obs.append(1.0 if o_uid == _my_partner else 0.0)
        obs.append(1.0 if o_is_pregnant else 0.0)
        obs.append(1.0 if o_is_abom else 0.0)
        obs.append(1.0 if getattr(other, 'is_sleeping', False) else 0.0)
        obs.append(1.0 if getattr(other, 'is_guarding', False) else 0.0)
        obs.append(1.0 if getattr(other, 'is_blocking', False) else 0.0)
        obs.append(_ln(creature.debt_owed_to(o_uid, 0) + 1) / 5.0
                   if _has_debt else 0.0)
        obs.append(_ln(other.debt_owed_to(_my_uid, 0) + 1) / 5.0
                   if hasattr(other, 'debt_owed_to') else 0.0)
        # Size one-hot (unrolled — SIZE_CATEGORIES has 6 values but
        # typical per-slot iteration was 6 len-comparisons per slot)
        o_size = other.size
        for sz in SIZE_CATEGORIES:
            obs.append(1.0 if o_size == sz else 0.0)
        obs.append(other.age / _old_min_norm)
        obs.append(1.0 if other_hp < 0.5 else 0.0)
        obs.append(1.0 if other_hp < 0.2 else 0.0)
        obs.append(1.0 if o_equip_len > 3 else 0.0)
        obs.append(1.0 if o_equip_len <= 1 else 0.0)

        # Threat scores (these still call into methods that do their
        # own stat lookups — a future optimization could cache them
        # per visible creature in the single-pass, but it's not a
        # top hotspot now)
        threat_to_me = creature._threat_score_against(other)
        threat_to_them = other._threat_score_against(creature)
        obs.append(_clamp(threat_to_me / max(1, _my_hp_cur) / 2))
        obs.append(_clamp(threat_to_them / max(1, their_hp_cur) / 2))

        # Approaching/fleeing from last-seen cache
        last = _last_seen.get(o_uid)
        if last is not None:
            last_dist = abs(cx - last[0]) + abs(cy - last[1])
            if dist < last_dist:
                approaching = 1.0
                fleeing = 0.0
            elif dist > last_dist:
                approaching = 0.0
                fleeing = 1.0
            else:
                approaching = 0.0
                fleeing = 0.0
        else:
            approaching = 0.0
            fleeing = 0.0
        obs.append(fleeing)
        obs.append(approaching)

        # other_allies: count how many visible creatures this `other`
        # considers allies. Still O(N) per slot, but with a direct
        # loop instead of a generator expression.
        other_allies = 0
        for vc in v_creatures:
            or_rel = o_rels.get(vc.uid)
            if or_rel and or_rel[0] > 5:
                other_allies += 1
        obs.append(1.0 if other_allies > 0 else 0.0)
        obs.append(other_allies / 5.0)
        obs.append(_my_desirability_fn(other, creature) if _my_desirability_fn else 0.0)
        obs.append(1.0 if (o_sex != _my_sex and other.is_adult
                           and not o_is_pregnant
                           and o_species == _my_species) else 0.0)

        their_size_u = _SIZE_UNITS.get(o_size, 4)
        obs.append(_clamp(my_size_u / max(1, their_size_u) / 2.0))
        obs.append(_clamp(threat_to_me / 20.0))
        obs.append(_clamp(threat_to_them / 20.0))
        obs.append(1.0 if (rel and rel[0] < -5) else 0.0)
        obs.append(1.0 if (rel and rel[0] > 5) else 0.0)
        obs.append(1.0)  # slot_occupied

        new_seen[o_uid] = (o_loc.x, o_loc.y)

    # Replace the last-seen cache with only currently-slotted creatures
    # (anyone not seen this tick shouldn't influence next tick's delta)
    creature._last_seen_positions = new_seen

    # ==== SECTION 22b: SOCIAL TOPOLOGY (17) ====
    # Simple cohesion (6) + Laplacian eigenvalues (4) + rest-of-crowd (7).
    # See classes/social_topology.py for the math. This gives the NN a
    # compact read on the structure of the visible social environment:
    # "am I in a unified group?", "are there factions?", "is anyone
    # dangerous beyond my top 10?"
    from classes.social_topology import compute_social_topology
    slot_creatures_only = [entry[1] for entry in slot_entries]
    topology = compute_social_topology(creature, visible, slot_creatures_only)
    obs.extend(topology)

    # ==== SECTION 22c: WATER AWARENESS (5) ====
    # For non-swimmers, water is deadly and we want a strong signal
    # that the NN can learn to avoid. Four floats describe the
    # spatial gradient; a fifth is a "I am in water right now" flag.
    #
    #   nearest_water_dist   : Manhattan distance to nearest water
    #                          tile in sight. Normalized by sight
    #                          range. 0 = I am standing on water.
    #                          1.0 = no water visible.
    #   nearest_water_dx     : unit-vector x component toward water
    #                          (0 if no water visible)
    #   nearest_water_dy     : unit-vector y component
    #   water_danger_flag    : 1 if I am on water AND I can't swim
    #                          (about to drown)
    #   can_swim             : creature's swim capability, so the
    #                          NN learns "distance to water matters
    #                          only if can_swim == 0"
    # water_min_d and water_best were collected in the combined tile
    # scan above (section 16b). Reuse — no second O(sight²) pass.
    nearest_water_dist = 1.0
    water_dx = 0.0
    water_dy = 0.0
    if water_min_d is not None:
        nearest_water_dist = water_min_d / sight
        if water_best is not None and (water_best[0] != 0 or water_best[1] != 0):
            mag = max(1, abs(water_best[0]) + abs(water_best[1]))
            water_dx = water_best[0] / mag
            water_dy = water_best[1] / mag
    obs.append(nearest_water_dist)
    obs.append(water_dx)
    obs.append(water_dy)
    can_swim = 1.0 if getattr(creature, 'can_swim', False) else 0.0
    in_water = 1.0 if (tile and getattr(tile, 'liquid', False)) else 0.0
    obs.append(in_water * (1.0 - can_swim))  # water_danger_flag
    obs.append(can_swim)

    # ==== SECTION 22d: HEARING (12) ====
    # Sound events emitted by other creatures during this tick — see
    # classes/sound.py. Gives the NN awareness of activity outside its
    # visual range: combat to the east, harvesting to the north, etc.
    from classes.sound import hearing_observation
    obs.extend(hearing_observation(creature, observation_tick or 0))

    # ==== SECTION 23: WORLD / TIME (6) ====
    # Simplified: 2 time floats (is_daytime, light_level) + 4 god balances.
    # Previous 9-value time block (sin/cos hour, sun/moon elevations, phases,
    # day-of-year) collapsed into the two values that actually drive behavior.
    if game_clock:
        obs.append(1.0 if game_clock.is_day else 0.0)
        light = game_clock.sun_elevation if game_clock.is_day else game_clock.moon_brightness * game_clock.moon_elevation
        obs.append(light)
    else:
        obs.extend([0.0] * 2)

    if world_data:
        for pair in [('Aelora','Xarith'), ('Solmara','Vaelkor'),
                     ('Verithan','Nyssara'), ('Sylvaine','Mortheus')]:
            obs.append(world_data.get_balance(pair[0]))
    else:
        obs.extend([0.0] * 4)

    # ==== SECTION 23b: MONSTER PERCEPTION SLOTS (30) ====
    # 5 slots × 6 fields each (distance, size_norm, threat, is_fleeing,
    # pack_size, in_territory). Zero when no monsters visible, which
    # is the normal case for curriculum stages 1-14.
    visible_monsters = []
    from classes.monster import Monster as _Monster
    m_map = creature.current_map
    if m_map is not None:
        mx, my = creature.location.x, creature.location.y
        for mon in _Monster.on_same_map(m_map):
            d = abs(mon.location.x - mx) + abs(mon.location.y - my)
            if d <= sight:
                visible_monsters.append((d, mon))
        visible_monsters.sort(key=lambda p: p[0])
    _section_starts['monster_slots'] = len(obs)

    _MON_SIZE_NORM = {'tiny': 0.0, 'small': 0.2, 'medium': 0.4,
                      'large': 0.6, 'huge': 0.8, 'colossal': 1.0}
    MAX_MON_SLOTS = 5
    for i in range(MAX_MON_SLOTS):
        if i < len(visible_monsters):
            dist, mon = visible_monsters[i]
            # distance normalized to sight range
            obs.append(min(1.0, dist / max(1, sight)))
            obs.append(_MON_SIZE_NORM.get(getattr(mon, 'size', 'medium'), 0.4))
            # rough threat score: STR + weapon damage (if any)
            mstr = mon.stats.active[Stat.STR]() if hasattr(mon, 'stats') else 10
            mdmg = mon.stats.active[Stat.MELEE_DMG]() if hasattr(mon, 'stats') else 0
            threat = (mstr + mdmg) / 40.0
            obs.append(min(1.0, threat))
            obs.append(1.0 if getattr(mon, '_is_fleeing', False) else 0.0)
            pack_sz = mon.pack.size if getattr(mon, 'pack', None) else 1
            obs.append(min(1.0, pack_sz / 10.0))
            # in_territory: is the creature inside this monster's pack territory?
            in_terr = 0.0
            if getattr(mon, 'pack', None) is not None:
                center = mon.pack.territory_center
                dx = creature.location.x - center.x
                dy = creature.location.y - center.y
                if math.sqrt(dx * dx + dy * dy) <= mon.pack.territory_radius():
                    in_terr = 1.0
            obs.append(in_terr)
        else:
            obs.extend([0.0] * 6)

    # ==== SECTION 23c: MONSTER SUMMARY (3) ====
    # monster_count_nearby, nearest_monster_distance, in_any_monster_territory
    _section_starts['monster_summary'] = len(obs)
    obs.append(min(1.0, len(visible_monsters) / 10.0))
    if visible_monsters:
        obs.append(visible_monsters[0][0] / max(1, sight))
    else:
        obs.append(1.0)  # 1.0 = nothing nearby (max normalized distance)
    # in_any_monster_territory: does any Pack's territory circle cover this tile?
    in_any_terr = 0.0
    try:
        from classes.pack import Pack as _Pack
        for pack in _Pack.all():
            if pack.game_map is not creature.current_map:
                continue
            center = pack.territory_center
            dx = creature.location.x - center.x
            dy = creature.location.y - center.y
            if math.sqrt(dx * dx + dy * dy) <= pack.territory_radius():
                in_any_terr = 1.0
                break
    except Exception:
        pass
    obs.append(in_any_terr)

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
    obs.append(GRAPH.count_from(creature.uid) / 20.0)
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

    # Record final length + propagate section starts for SECTION_RANGES
    _section_starts['_end'] = len(obs)
    global _LAST_SECTION_STARTS
    _LAST_SECTION_STARTS = dict(_section_starts)
    return obs


# Module-level snapshot of the most recent build's section starts.
# Used to refresh SECTION_RANGES after the first build.
_LAST_SECTION_STARTS: dict = {}


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
    'self_hunger':      (171, 177),      # +1 desperation float
    'self_quest':       (177, 187),
    'self_goal':        (187, 208),
    'self_schedule':    (208, 218),      # +10 job/schedule floats
    'self_movement':    (218, 226),
    'self_genetics':    (226, 233),
    'self_identity':    (233, 258),
    'self_reputation':  (258, 264),
    'tile_deep':        (264, 285),
    'tile_liquid':      (285, 310),
    'spatial_walls':    (310, 335),
    'spatial_features': (335, 351),
    'tile_items':       (351, 378),
    'census_visible':   (378, 423),
    'census_audible':   (423, 426),
    'per_engaged':      (426, 696),
    'world_time':       (696, 702),       # shrunk from 13 to 6 (time simplified)
    'monster_slots':    (702, 732),       # pre-allocated 5 slots x 6 floats
    'monster_summary':  (732, 735),       # count, nearest dist, in_territory
    'temporal':         (735, 749),
    'trends':           (749, 760),
    'time_since':       (760, 772),
    'reward_signals':   (772, 789),
    'transforms':       (789, OBSERVATION_SIZE),
}


def _refresh_monster_section_ranges():
    """Overwrite monster_slots/monster_summary ranges with actual offsets
    captured during the OBSERVATION_SIZE probe. The earlier section ranges
    are approximate and based on pre-refactor layouts; the monster
    sections sit after per_engaged at a position that depends on the
    precise sizes of earlier dynamic sections (per_engaged grows with
    species count, for example).
    """
    starts = _LAST_SECTION_STARTS
    if 'monster_slots' in starts and 'monster_summary' in starts:
        SECTION_RANGES['monster_slots'] = (
            starts['monster_slots'], starts['monster_summary'])
        SECTION_RANGES['monster_summary'] = (
            starts['monster_summary'], starts['monster_summary'] + 3)


# Refresh monster section ranges now that the probe has run
_refresh_monster_section_ranges()

# Semantic groups for easy mask building
SECTION_GROUPS = {
    'social': ['self_social', 'self_reputation', 'census_visible',
               'census_audible', 'per_engaged'],
    'combat': ['self_combat', 'self_weapon'],
    'vision': ['spatial_walls', 'spatial_features', 'tile_deep', 'tile_items',
               'census_visible', 'per_engaged', 'monster_slots', 'monster_summary'],
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
    all_rels = list(GRAPH.edges_from(creature.uid).values())
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
