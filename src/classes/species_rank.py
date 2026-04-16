"""Species-configurable rank formulas — Phase 4 extension.

Pack members are ordered by a per-species formula so sentient
species (CHR-driven leadership, wealth-driven merchants) don't
have to mirror the bestial "physical might" rule that works for
monster packs.

Four formulas supported:
  * might  — STR + AGL (raw physical dominance, default for beasts
             and monsters)
  * wealth — gold / 10
  * social — CHR * 2 + level
  * hybrid — weighted blend: STR + AGL + CHR*1.5 + level*2 + gold/100
             (the default for sentient species without an explicit
             override)

The rank formula lives in the species row (for creatures) or
monster_species row (for monsters). See the Pack.rerank path.
"""
from __future__ import annotations


def rank_score(entity, formula: str = 'hybrid') -> float:
    """Compute a rank score for ordering pack members.

    ``entity`` is any object with a ``stats`` attribute plus optional
    ``gold`` / ``level`` fields. Returns a float — higher = more
    dominant. Missing fields default to 0 so partial entities don't
    crash ranking.
    """
    from classes.stats import Stat
    stats = getattr(entity, 'stats', None)
    if stats is None:
        return 0.0

    def _stat(s):
        try:
            return stats.active[s]()
        except Exception:
            return 0

    gold = getattr(entity, 'gold', 0) or 0
    level = 0
    try:
        level = stats.base.get(Stat.LVL, 0) or 0
    except Exception:
        pass

    if formula == 'might':
        return float(_stat(Stat.STR) + _stat(Stat.AGL))
    if formula == 'wealth':
        return float(gold) / 10.0
    if formula == 'social':
        return float(_stat(Stat.CHR) * 2 + level)
    # hybrid (default)
    return (float(_stat(Stat.STR))
            + float(_stat(Stat.AGL))
            + float(_stat(Stat.CHR)) * 1.5
            + float(level) * 2.0
            + float(gold) / 100.0)


def formula_for_species(species_name: str) -> str:
    """Look up the rank formula for a given species name.

    Checks monster_species first (monster packs), then species
    (creature packs). Falls back to 'might' for backwards compat
    with existing monster-only packs.
    """
    # Monster species check — monster species don't carry rank_formula
    # yet. Monsters always use 'might' (default / existing behavior).
    try:
        from data.db import MONSTER_SPECIES
        if species_name in MONSTER_SPECIES:
            return MONSTER_SPECIES[species_name].get('rank_formula', 'might')
    except Exception:
        pass
    # Creature species check
    try:
        from data.db import SPECIES
        if species_name in SPECIES:
            return SPECIES[species_name].get('rank_formula', 'hybrid')
    except Exception:
        pass
    return 'might'
