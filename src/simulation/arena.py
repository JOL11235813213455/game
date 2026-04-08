"""
Random arena generator for headless RL training.

Generates varied maps with obstacles, places creatures with randomized
stats, and returns a ready-to-simulate environment.
"""
from __future__ import annotations
import random
from classes.maps import Map, MapKey, Tile
from classes.creature import Creature, RandomWanderBehavior
from classes.inventory import Weapon, Wearable, Slot
from classes.stats import Stat


BASE_STATS = [Stat.STR, Stat.VIT, Stat.AGL, Stat.PER, Stat.INT, Stat.CHR, Stat.LCK]


def random_stats(profile: str = 'balanced') -> dict:
    """Generate random base stats with a profile bias.

    Profiles:
      balanced: all stats 8-14
      fighter:  high STR/VIT, low INT/CHR
      mage:    high INT/CHR, low STR/VIT
      rogue:   high AGL/PER, low STR/VIT
      random:  fully random 3-18
    """
    if profile == 'random':
        return {s: random.randint(3, 18) for s in BASE_STATS}

    base = {s: random.randint(8, 14) for s in BASE_STATS}

    if profile == 'fighter':
        base[Stat.STR] = random.randint(14, 18)
        base[Stat.VIT] = random.randint(12, 16)
        base[Stat.INT] = random.randint(4, 10)
        base[Stat.CHR] = random.randint(4, 10)
    elif profile == 'mage':
        base[Stat.INT] = random.randint(14, 18)
        base[Stat.CHR] = random.randint(12, 16)
        base[Stat.STR] = random.randint(4, 10)
        base[Stat.VIT] = random.randint(6, 12)
    elif profile == 'rogue':
        base[Stat.AGL] = random.randint(14, 18)
        base[Stat.PER] = random.randint(14, 18)
        base[Stat.STR] = random.randint(6, 12)
        base[Stat.VIT] = random.randint(6, 12)

    return base


def random_weapon() -> Weapon:
    """Create a random weapon."""
    templates = [
        ('Sword', 5, 1, [Slot.HAND_R]),
        ('Axe', 7, 1, [Slot.HAND_R]),
        ('Dagger', 3, 1, [Slot.HAND_R]),
        ('Spear', 4, 2, [Slot.HAND_R]),
        ('Bow', 4, 8, [Slot.HAND_L, Slot.HAND_R]),
    ]
    name, dmg, rng, slots = random.choice(templates)
    return Weapon(
        name=name, weight=random.uniform(1.0, 5.0), value=random.uniform(3.0, 15.0),
        slots=slots, slot_count=len(slots), damage=dmg, range=rng,
    )


def generate_arena(cols: int = 20, rows: int = 20,
                   num_creatures: int = 6,
                   obstacle_density: float = 0.1,
                   profiles: list[str] = None) -> dict:
    """Generate a random arena with creatures.

    Args:
        cols, rows: map dimensions
        num_creatures: how many creatures to place
        obstacle_density: fraction of tiles that are unwalkable (0.0–1.0)
        profiles: list of stat profiles for creatures (cycles if shorter)

    Returns:
        dict with keys: map, creatures, cols, rows
    """
    profiles = profiles or ['balanced', 'fighter', 'mage', 'rogue', 'random']

    # Generate map with random obstacles
    tiles = {}
    for x in range(cols):
        for y in range(rows):
            walkable = random.random() >= obstacle_density
            tiles[MapKey(x, y, 0)] = Tile(walkable=walkable)

    # Ensure entrance is walkable
    tiles[MapKey(0, 0, 0)] = Tile(walkable=True)
    game_map = Map(tile_set=tiles, entrance=(0, 0),
                   x_max=cols, y_max=rows)

    # Place creatures on random walkable tiles
    walkable_tiles = [k for k, t in tiles.items() if t.walkable]
    random.shuffle(walkable_tiles)

    creatures = []
    for i in range(min(num_creatures, len(walkable_tiles))):
        loc = walkable_tiles[i]
        profile = profiles[i % len(profiles)]
        stats = random_stats(profile)
        level = random.randint(1, 5)
        stats[Stat.LVL] = level

        c = Creature(
            current_map=game_map,
            location=loc,
            name=f'{profile.capitalize()}_{i}',
            stats=stats,
            behavior=RandomWanderBehavior(),
            move_interval=500,
        )

        # Give some creatures weapons
        if random.random() < 0.6:
            w = random_weapon()
            c.inventory.items.append(w)
            c.equip(w)

        creatures.append(c)

    return {
        'map': game_map,
        'creatures': creatures,
        'cols': cols,
        'rows': rows,
    }
