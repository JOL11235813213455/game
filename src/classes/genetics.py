"""
Chromosome-based genetics system.

Each creature has two chromosomes of 14 genes (2 per base stat).
Males are XY, females are XX. Gene values are 0-15.

Gene positions:
  0-1: STR, 2-3: VIT, 4-5: AGL, 6-7: PER, 8-9: INT, 10-11: CHR, 12-13: LCK

Sex-linked biases during generation:
  Y chromosome: slight bias toward STR (+0-1), INT (+0-1), PER (+0-1)
  Second X:     slight bias toward VIT (+0-1), AGL (+0-1), CHR (+0-1)
  LCK: encoded on both X and Y — no sex bias
"""
from __future__ import annotations
import random
from classes.stats import Stat

# Gene position → Stat mapping (2 genes per stat)
GENE_STAT_MAP = {
    0: Stat.STR, 1: Stat.STR,
    2: Stat.VIT, 3: Stat.VIT,
    4: Stat.AGL, 5: Stat.AGL,
    6: Stat.PER, 7: Stat.PER,
    8: Stat.INT, 9: Stat.INT,
    10: Stat.CHR, 11: Stat.CHR,
    12: Stat.LCK, 13: Stat.LCK,
}

NUM_GENES = 14

# Stats biased on Y (male-favored)
Y_BIAS_STATS = {Stat.STR, Stat.INT, Stat.PER}
# Stats biased on second X (female-favored)
X_BIAS_STATS = {Stat.VIT, Stat.AGL, Stat.CHR}

MUTATION_RATE = 0.02
INBRED_MUTATION_RATE = 0.15


def _random_gene() -> int:
    """Random gene value 0-15."""
    return random.randint(0, 15)


def _biased_gene(stat: Stat, bias_stats: set, bias_amount: int = 2) -> int:
    """Gene with slight upward bias for certain stats."""
    base = random.randint(0, 15)
    if stat in bias_stats:
        base = min(15, base + random.randint(0, bias_amount))
    return base


def generate_chromosomes(sex: str) -> tuple[list[int], list[int]]:
    """Generate a pair of chromosomes for a new creature.

    Args:
        sex: 'male' or 'female'

    Returns:
        (chromosome_a, chromosome_b) — each is a list of 14 ints (0-15)
        For males: (X, Y). For females: (X, X).
    """
    # First chromosome is always X-type
    x1 = []
    for i in range(NUM_GENES):
        stat = GENE_STAT_MAP[i]
        x1.append(_random_gene())

    if sex == 'male':
        # Y chromosome: bias toward STR, INT, PER
        y = []
        for i in range(NUM_GENES):
            stat = GENE_STAT_MAP[i]
            y.append(_biased_gene(stat, Y_BIAS_STATS))
        return (x1, y)
    else:
        # Second X: bias toward VIT, AGL, CHR
        x2 = []
        for i in range(NUM_GENES):
            stat = GENE_STAT_MAP[i]
            x2.append(_biased_gene(stat, X_BIAS_STATS))
        return (x1, x2)


def inherit(mother_chroms: tuple[list[int], list[int]],
            father_chroms: tuple[list[int], list[int]],
            child_sex: str,
            inbreeding_closeness: int = 0) -> tuple[list[int], list[int]]:
    """Create child chromosomes via Mendelian inheritance.

    Mother is XX, father is XY.
    Child gets one gene per position from each parent:
      - From mother: random pick between her two X chromosomes at each position
      - From father: if child is female, gets father's X; if male, gets father's Y

    Args:
        mother_chroms: (X1, X2) mother's chromosomes
        father_chroms: (X, Y) father's chromosomes
        child_sex: 'male' or 'female'
        inbreeding_closeness: 0 = none, 1 = siblings, 2 = cousins, 3 = distant
            Higher closeness = more mutations biased toward bad values

    Returns:
        (chromosome_a, chromosome_b) for the child
    """
    mut_rate = inbreeding_mutation_rate(inbreeding_closeness)
    bad_bias = inbreeding_closeness > 0

    # From mother: random gene from X1 or X2 at each position
    child_from_mother = []
    for i in range(NUM_GENES):
        gene = mother_chroms[0][i] if random.random() < 0.5 else mother_chroms[1][i]
        if random.random() < mut_rate:
            gene = random.randint(0, 7) if bad_bias else _random_gene()
        child_from_mother.append(gene)

    # From father: X chromosome for daughters, Y for sons
    father_chrom_idx = 1 if child_sex == 'male' else 0
    child_from_father = []
    for i in range(NUM_GENES):
        gene = father_chroms[father_chrom_idx][i]
        if random.random() < mut_rate:
            gene = random.randint(0, 7) if bad_bias else _random_gene()
        child_from_father.append(gene)

    return (child_from_mother, child_from_father)


def express(chromosomes: tuple[list[int], list[int]]) -> dict[Stat, int]:
    """Express chromosomes into stat modifiers.

    Dominance: higher value at each position is expressed.
    Sum dominant values per stat pair, then scale to a -3 to +3 range
    relative to a neutral midpoint.

    Returns:
        {Stat: modifier} where modifier is roughly -3 to +3
    """
    # Sum dominant values per stat
    stat_sums: dict[Stat, int] = {}
    for i in range(NUM_GENES):
        stat = GENE_STAT_MAP[i]
        dominant = max(chromosomes[0][i], chromosomes[1][i])
        stat_sums[stat] = stat_sums.get(stat, 0) + dominant

    # Each stat has 2 genes, max dominant value 15 each → range 0-30
    # Midpoint = 15 (two genes averaging 7.5 each)
    # Scale: (sum - 15) / 5, clamped to -3..+3
    modifiers = {}
    for stat, total in stat_sums.items():
        mod = (total - 15) / 5.0
        modifiers[stat] = max(-3, min(3, round(mod)))

    return modifiers


def apply_genetics(species_stats: dict, genetic_mods: dict[Stat, int]) -> dict:
    """Apply genetic modifiers to species base stats.

    Args:
        species_stats: {Stat: value} species defaults
        genetic_mods: {Stat: modifier} from express()

    Returns:
        {Stat: adjusted_value} — species base + genetic modifier
    """
    result = dict(species_stats)
    for stat, mod in genetic_mods.items():
        if stat in result:
            result[stat] = max(1, result[stat] + mod)
    return result


def check_inbreeding(mother_uid: int, father_uid: int,
                     lineage: dict[int, tuple[int | None, int | None]],
                     generations: int = 3) -> int:
    """Check if two creatures share a common ancestor within N generations.

    Returns the **closest generation** at which a common ancestor is found:
      1 = share a parent (siblings), 2 = share grandparent, 3 = share great-grandparent.
      0 = no common ancestor within the checked range.

    Closer common ancestor = more severe inbreeding effects.
    """
    def _ancestors_by_depth(uid: int, max_depth: int) -> dict[int, int]:
        """Return {ancestor_uid: closest_generation_depth}."""
        result = {}
        stack = [(uid, 0)]
        while stack:
            current, depth = stack.pop()
            if current is None or depth > max_depth:
                continue
            if depth > 0:  # don't include self
                if current not in result or depth < result[current]:
                    result[current] = depth
            entry = lineage.get(current)
            if entry:
                m, f = entry
                stack.append((m, depth + 1))
                stack.append((f, depth + 1))
        return result

    mother_anc = _ancestors_by_depth(mother_uid, generations)
    father_anc = _ancestors_by_depth(father_uid, generations)

    shared = set(mother_anc.keys()) & set(father_anc.keys())
    if not shared:
        return 0

    # Return the closest shared ancestor (minimum generation distance)
    return min(min(mother_anc[a], father_anc[a]) for a in shared)


def inbreeding_mutation_rate(closeness: int) -> float:
    """Return mutation rate based on inbreeding closeness.

    0 = no inbreeding → normal 2%
    1 = siblings → 20%
    2 = share grandparent → 12%
    3 = share great-grandparent → 7%

    Closer ancestor = dramatically worse mutations.
    """
    if closeness <= 0:
        return MUTATION_RATE
    # Exponential decay from 20% at closeness=1
    return min(0.25, 0.20 / closeness)
