"""
Item valuation and trade pricing system.

Each item's value is computed from the creature's perspective using:
1. Raw KPI (burst damage, damage prevention, stat delta, etc.)
2. Decompounding formula for time-preference weighted total value
3. Three-value pricing: paid, worth-to-me, worth-to-them
4. Surplus splitting via CHR/sentiment/desperation for NPC trades

All value deltas use ln(new/old) for symmetric comparison.
"""
from __future__ import annotations
import math
from classes.stats import Stat


# ---------------------------------------------------------------------------
# KPI Metrics
# ---------------------------------------------------------------------------

def _burst_damage(creature) -> float:
    """Max damage from full stamina dump without refresh."""
    from classes.inventory import Weapon
    from classes.creature import Creature

    weapon = creature.equipment.get(Slot.HAND_R) or creature.equipment.get(Slot.HAND_L)

    if weapon and isinstance(weapon, Weapon):
        dmg_per_swing = weapon.damage + (creature.stats.active[Stat.MELEE_DMG]())
        cost_per_swing = max(5, 10 - (creature.stats.active[Stat.STR]() - 10) // 2)
    else:
        # Unarmed
        dmg_per_swing = max(1, creature.stats.active[Stat.MELEE_DMG]())
        cost_per_swing = 5

    stamina = creature.stats.active[Stat.MAX_STAMINA]()
    swings = max(1, stamina // max(1, cost_per_swing))
    return dmg_per_swing * swings


# Need Slot imported at module level for _burst_damage
from classes.inventory import Slot


def _damage_prevented(creature, incoming_damage: float = 10.0) -> float:
    """Expected damage prevented per typical incoming attack.

    Combines dodge probability and armor absorption probability.
    Uses creature's own offensive stats as the assumed attacker baseline.
    """
    # Assume attacker is roughly as capable as self
    attacker_accuracy = creature.stats.active[Stat.ACCURACY]()

    dodge = creature.stats.active[Stat.DODGE]()
    dodge_prob = max(0.05, min(0.95, 0.5 + (dodge - attacker_accuracy) * 0.025))

    armor = creature.stats.active[Stat.ARMOR]()
    weapon_dc = incoming_damage  # approximate weapon DC from damage
    if weapon_dc <= 0:
        armor_prob = 1.0
    else:
        armor_prob = min(0.95, max(0.0, armor / weapon_dc))

    # Expected damage taken = raw × P(not dodged) × P(not absorbed)
    expected_taken = incoming_damage * (1 - dodge_prob) * (1 - armor_prob)
    return incoming_damage - expected_taken


def _stat_delta_score(creature, item) -> float:
    """Score the net stat change from equipping an item.

    Temporarily applies buffs, measures all derived stat changes.
    Used for items whose primary value is stat modification (rings, amulets).
    """
    if not item.buffs:
        return item.value  # no buffs → fall back to base value

    before = creature.stats.snapshot()

    mods = []
    for stat, amount in item.buffs.items():
        mods.append(creature.stats.add_mod('_kpi_eval', stat, amount))

    after = creature.stats.snapshot()

    for mod in mods:
        creature.stats.remove_mod(mod)

    # Sum absolute deltas — each stat point is equally weighted here
    # because the decompounding + pricing layer handles relative importance
    score = 0.0
    for stat in after:
        delta = after[stat] - before.get(stat, 0)
        score += abs(delta)

    return score


# ---------------------------------------------------------------------------
# KPI Metric Registry
# ---------------------------------------------------------------------------

def compute_raw_kpi(item, creature) -> float:
    """Compute the raw KPI for an item given a creature's context.

    The item's kpi_metric field (if set) determines which calculation.
    Falls back to stat_delta_score for items without a specific metric.
    """
    from classes.inventory import Weapon, Wearable, Consumable, Ammunition

    metric = getattr(item, 'kpi_metric', None)

    if metric == 'burst_damage' or (metric is None and isinstance(item, Weapon)):
        # Simulate equipping this weapon
        from classes.inventory import Slot as S
        current = creature.equipment.get(S.HAND_R)

        # Temporarily swap
        if current:
            creature.stats.remove_mods_by_source(f'equip_{current.uid}')
        for stat, amount in item.buffs.items():
            creature.stats.add_mod('_kpi_swap', stat, amount)

        kpi = _burst_damage(creature)

        # Restore
        creature.stats.remove_mods_by_source('_kpi_swap')
        if current:
            for stat, amount in current.buffs.items():
                creature.stats.add_mod(f'equip_{current.uid}', stat, amount)

        # Add weapon's own damage
        kpi += item.damage * 3  # weight weapon base damage

        return max(0.001, kpi)

    elif metric == 'damage_reduction' or (metric is None and isinstance(item, Wearable)):
        # Simulate equipping this armor
        current_slot = item.slots[0] if item.slots else None
        current = creature.equipment.get(current_slot) if current_slot else None

        if current:
            creature.stats.remove_mods_by_source(f'equip_{current.uid}')
        for stat, amount in item.buffs.items():
            creature.stats.add_mod('_kpi_swap', stat, amount)

        kpi = _damage_prevented(creature)

        creature.stats.remove_mods_by_source('_kpi_swap')
        if current:
            for stat, amount in current.buffs.items():
                creature.stats.add_mod(f'equip_{current.uid}', stat, amount)

        return max(0.001, kpi)

    elif metric == 'heal_value' or (metric is None and isinstance(item, Consumable)):
        heal = getattr(item, 'damage', 0)  # consumables use damage field for heal
        buff_total = sum(abs(v) for v in item.buffs.values())
        duration = getattr(item, 'duration', 0)
        return max(0.001, heal + buff_total * max(1, duration))

    elif metric == 'ammo_value' or (metric is None and isinstance(item, Ammunition)):
        return max(0.001, item.damage)

    else:
        # Generic: stat delta score
        return max(0.001, _stat_delta_score(creature, item))


# ---------------------------------------------------------------------------
# Decompounding Formula
# ---------------------------------------------------------------------------

def decompounded_value(base_kpi: float, remaining_uses: int) -> float:
    """Time-preference weighted total value of an item.

    Formula: sum((base_kpi^(1/d)) - 1 + (1.5 * base_kpi) for d in 1..remaining_uses)

    Components per remaining use:
      Floor:   1.5 × base_kpi — stable value per use
      Premium: base_kpi^(1/d) - 1 — diminishing time-preference bonus
    """
    if remaining_uses <= 0:
        return 0.0
    if base_kpi <= 0:
        return 0.0

    total = 0.0
    for d in range(1, remaining_uses + 1):
        premium = (base_kpi ** (1.0 / d)) - 1.0
        floor = 1.5 * base_kpi
        total += premium + floor

    return total


# ---------------------------------------------------------------------------
# Three-Value Pricing
# ---------------------------------------------------------------------------

def worth_to_creature(item, creature) -> float:
    """What an item is worth TO a specific creature in gold-equivalent.

    Combines raw KPI with decompounding based on remaining durability/uses.
    """
    raw = compute_raw_kpi(item, creature)

    # Remaining uses
    if hasattr(item, 'durability_current') and hasattr(item, 'durability_max'):
        remaining = max(1, item.durability_current)
    elif hasattr(item, 'quantity'):
        remaining = max(1, item.quantity)
    else:
        remaining = 100  # non-depletable items get a high assumed life

    return decompounded_value(raw, remaining)


def min_sell_price(item, creature) -> float:
    """Minimum price a creature would accept to sell this item.

    max(what_i_paid, what_its_worth_to_me)
    """
    paid = creature._item_prices.get(id(item), item.value)
    worth = worth_to_creature(item, creature)
    return max(paid, worth)


def max_buy_price(item, creature) -> float:
    """Maximum price a creature would pay for this item.

    Equal to what it's worth to them.
    """
    return worth_to_creature(item, creature)


# ---------------------------------------------------------------------------
# Surplus Splitting (NPC-to-NPC Trade Pricing)
# ---------------------------------------------------------------------------

def compute_trade_price(item, seller, buyer) -> dict:
    """Compute the trade price for an item between two creatures.

    Returns dict:
        feasible: bool — can a deal be made?
        price: float — the agreed price
        surplus: float — total surplus in the deal
        buyer_surplus: float — buyer's gain
        seller_surplus: float — seller's gain
        seller_min: float
        buyer_max: float
    """
    s_min = min_sell_price(item, seller)
    b_max = max_buy_price(item, buyer)

    result = {
        'feasible': False, 'price': 0.0, 'surplus': 0.0,
        'buyer_surplus': 0.0, 'seller_surplus': 0.0,
        'seller_min': s_min, 'buyer_max': b_max,
    }

    if b_max < s_min:
        return result  # No overlap — no deal

    surplus = b_max - s_min
    result['feasible'] = True
    result['surplus'] = surplus

    # CHR-based split
    seller_chr = (seller.stats.active[Stat.CHR]() - 10) // 2
    buyer_chr = (buyer.stats.active[Stat.CHR]() - 10) // 2

    seller_persuasion = seller.stats.active[Stat.PERSUASION]()
    buyer_persuasion = buyer.stats.active[Stat.PERSUASION]()

    seller_pull = seller_chr + seller_persuasion + 10
    buyer_pull = buyer_chr + buyer_persuasion + 10

    seller_share = seller_pull / max(1, seller_pull + buyer_pull)

    # Sentiment adjustment: friends give better deals
    rel = buyer.get_relationship(seller)
    if rel:
        sentiment_shift = rel[0] / (abs(rel[0]) + 20) * 0.2
        seller_share = max(0.1, min(0.9, seller_share - sentiment_shift))

    # Desperation adjustments
    # Disposable wealth = gold - liabilities
    buyer_disposable = buyer.gold - getattr(buyer, 'liabilities', 0)
    seller_disposable = seller.gold - getattr(seller, 'liabilities', 0)

    # Buyer desperate: item worth > half their disposable wealth
    if buyer_disposable > 0 and b_max > buyer_disposable * 0.5:
        seller_share = min(0.9, seller_share + 0.1)

    # Seller desperate: disposable wealth near zero or negative
    if seller_disposable < 20:
        seller_share = max(0.1, seller_share - 0.1)
        # Really desperate: will go down to purchase price
        if seller_disposable <= 0:
            paid = seller._item_prices.get(id(item), item.value)
            s_min = paid  # override min_sell to purchase price

    price = s_min + (surplus * seller_share)
    result['price'] = price
    result['buyer_surplus'] = b_max - price
    result['seller_surplus'] = price - s_min

    return result


def trade_reward(my_surplus: float, my_wealth: float) -> float:
    """Compute RL reward for a trade outcome.

    Uses ln(1 + surplus/wealth) — scaled by how much the surplus
    matters relative to total wealth.
    """
    if my_wealth <= 0:
        my_wealth = 1.0
    return math.log(1.0 + my_surplus / my_wealth)
