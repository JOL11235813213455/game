"""
Gods and piety system.

8 gods in 4 opposed pairs. Each action in the game feeds a god's counter.
Creatures have a deity (or None) and piety (0-1).

World balance is the cumulative sum of actions per dichotomy.
Piety drifts from exposure to opposing worship.
"""
from __future__ import annotations
from classes.trackable import Trackable


class God:
    """A single deity with domain and action alignments."""

    def __init__(self, name: str, domain: str, opposed_god: str = None,
                 aligned_actions: list[str] = None,
                 opposed_actions: list[str] = None,
                 description: str = ''):
        self.name = name
        self.domain = domain
        self.opposed_god = opposed_god
        self.aligned_actions = aligned_actions or []
        self.opposed_actions = opposed_actions or []
        self.description = description
        self.action_count: int = 0  # global counter of aligned actions


# Default pantheon — 4 opposed pairs
DEFAULT_GODS = [
    God('Aelora', 'order', opposed_god='Xarith',
        aligned_actions=['guard', 'follow', 'block_stance', 'wait'],
        opposed_actions=['flee', 'break_pair_bond'],
        description='Goddess of Order — structure, discipline, loyalty'),
    God('Xarith', 'chaos', opposed_god='Aelora',
        aligned_actions=['flee', 'steal', 'break_pair_bond'],
        opposed_actions=['guard', 'follow', 'block_stance'],
        description='God of Chaos — freedom, disruption, unpredictability'),
    God('Solmara', 'compassion', opposed_god='Vaelkor',
        aligned_actions=['talk', 'trade', 'share_rumor', 'bribe', 'bond_with_child', 'heal'],
        opposed_actions=['melee_attack', 'ranged_attack', 'intimidate', 'force_pairing'],
        description='Goddess of Compassion — kindness, diplomacy, nurture'),
    God('Vaelkor', 'wrath', opposed_god='Solmara',
        aligned_actions=['melee_attack', 'ranged_attack', 'grapple', 'intimidate', 'force_pairing'],
        opposed_actions=['talk', 'trade', 'share_rumor', 'bribe'],
        description='God of Wrath — violence, dominance, conquest'),
    God('Verithan', 'truth', opposed_god='Nyssara',
        aligned_actions=['trade', 'share_rumor', 'solicit_rumor', 'search'],
        opposed_actions=['deceive', 'steal'],
        description='God of Truth — honesty, knowledge, discovery'),
    God('Nyssara', 'lies', opposed_god='Verithan',
        aligned_actions=['deceive', 'steal', 'sneak'],
        opposed_actions=['trade', 'share_rumor', 'search'],
        description='Goddess of Lies — deception, shadow, secrets'),
    God('Sylvaine', 'life', opposed_god='Mortheus',
        aligned_actions=['heal', 'propose_pairing', 'use_item', 'pickup'],
        opposed_actions=['eat_egg', 'kill'],
        description='Goddess of Life — growth, fertility, restoration'),
    God('Mortheus', 'death', opposed_god='Sylvaine',
        aligned_actions=['eat_egg', 'kill', 'cast_spell_damage'],
        opposed_actions=['heal', 'propose_pairing'],
        description='God of Death — destruction, endings, entropy'),
]


class WorldData(Trackable):
    """Global world state — singleton, saved via pickle.

    Tracks god action counters, world balance, and any global state
    needed for quest conditions and piety calculations.
    """

    def __init__(self):
        super().__init__()
        self.gods: dict[str, God] = {}
        self.dichotomies: dict[str, tuple[str, str]] = {}
        # Global quest/world state flags (for quest conditions)
        self.flags: dict[str, object] = {}
        self._init_default_pantheon()

    def _init_default_pantheon(self):
        """Set up the default 8 gods in 4 pairs (fresh copies)."""
        for god in DEFAULT_GODS:
            self.gods[god.name] = God(
                name=god.name, domain=god.domain, opposed_god=god.opposed_god,
                aligned_actions=list(god.aligned_actions),
                opposed_actions=list(god.opposed_actions),
                description=god.description,
            )
        # Build dichotomy pairs
        seen = set()
        for god in self.gods.values():
            if god.name in seen or god.opposed_god in seen:
                continue
            if god.opposed_god and god.opposed_god in self.gods:
                key = f'{god.domain}_vs_{self.gods[god.opposed_god].domain}'
                self.dichotomies[key] = (god.name, god.opposed_god)
                seen.add(god.name)
                seen.add(god.opposed_god)

    def record_action(self, action_name: str):
        """Record a global action. Increments the aligned god's counter."""
        for god in self.gods.values():
            if action_name in god.aligned_actions:
                god.action_count += 1

    def get_balance(self, god_name: str) -> float:
        """Get the world balance for a god's dichotomy.

        Returns positive if this god's side is winning, negative if losing.
        Range: roughly -1.0 to 1.0 (normalized).
        """
        god = self.gods.get(god_name)
        if god is None or god.opposed_god is None:
            return 0.0
        opposed = self.gods.get(god.opposed_god)
        if opposed is None:
            return 0.0
        total = god.action_count + opposed.action_count
        if total == 0:
            return 0.0
        return (god.action_count - opposed.action_count) / total

    def get_god_for_action(self, action_name: str) -> str | None:
        """Return the god name aligned with an action, or None."""
        for god in self.gods.values():
            if action_name in god.aligned_actions:
                return god.name
        return None

    def get_opposed_god(self, god_name: str) -> str | None:
        """Return the name of the opposed god."""
        god = self.gods.get(god_name)
        return god.opposed_god if god else None

    def is_opposed(self, god_a: str, god_b: str) -> bool:
        """Check if two gods are directly opposed."""
        ga = self.gods.get(god_a)
        return ga is not None and ga.opposed_god == god_b

    def is_aligned_axis(self, god_a: str, god_b: str) -> bool:
        """Check if two gods are on the same axis (same or opposed)."""
        if god_a == god_b:
            return True
        return self.is_opposed(god_a, god_b)

    def set_flag(self, key: str, value: object):
        """Set a world state flag (for quest conditions)."""
        self.flags[key] = value

    def get_flag(self, key: str, default=None) -> object:
        """Get a world state flag."""
        return self.flags.get(key, default)


# Piety constants
PIETY_DRIFT_BASE = 0.01       # base drift per witnessed act
PIETY_MAX_ACTS_PER_CYCLE = 10  # max acts that count before cooldown
PIETY_CONVERSION_THRESHOLD = 5  # must accumulate this much before attaining new god
PIETY_MIN_FOR_GOD = 0.0       # piety must drop to this to lose god


def compute_piety_drift(my_piety: float, opposing_nearby_piety: float) -> float:
    """Compute piety drift per witnessed opposing act.

    Returns the amount of piety lost per act (positive number).
    """
    if my_piety <= 0 or opposing_nearby_piety <= 0:
        return 0.0
    influence = opposing_nearby_piety / (my_piety + opposing_nearby_piety + 1)
    return influence * PIETY_DRIFT_BASE


def update_creature_piety(creature, action_name: str, world: WorldData,
                          visible_creatures: list):
    """Update a creature's piety based on a witnessed action.

    Called when creature witnesses another creature performing an action.
    """
    if creature.deity is None:
        return

    my_god = world.gods.get(creature.deity)
    if my_god is None:
        return

    action_god_name = world.get_god_for_action(action_name)
    if action_god_name is None:
        return

    # Check if this action is on our axis at all
    if not world.is_aligned_axis(creature.deity, action_god_name):
        return  # unrelated axis — no effect

    # Aligned action: reinforce piety
    if action_god_name == creature.deity:
        creature.piety = min(1.0, creature.piety + 0.005)
        return

    # Opposing action: drift piety down
    # Sum opposing piety from visible creatures
    opposing_piety = 0.0
    opposed_name = my_god.opposed_god
    for other in visible_creatures:
        if other is creature:
            continue
        if getattr(other, 'deity', None) == opposed_name:
            opposing_piety += getattr(other, 'piety', 0)

    if opposing_piety <= 0:
        return

    drift = compute_piety_drift(creature.piety, opposing_piety)
    creature.piety = max(0.0, creature.piety - drift)

    # If piety drops to 0, lose god
    if creature.piety <= PIETY_MIN_FOR_GOD:
        creature.deity = None
        creature.piety = 0.0
