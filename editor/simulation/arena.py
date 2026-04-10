"""
Random arena generator for headless RL training.

Generates varied maps with obstacles, spawns creatures with full
genetics, sex, species, age, deity, equipment, and gold.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
import random
from classes.maps import Map, MapKey, Tile
from classes.creature import Creature, RandomWanderBehavior
from classes.inventory import Weapon, Wearable, Consumable, Slot
from classes.stats import Stat
from classes.genetics import generate_chromosomes, express, apply_genetics
from classes.gods import DEFAULT_GODS


BASE_STATS = [Stat.STR, Stat.VIT, Stat.AGL, Stat.PER, Stat.INT, Stat.CHR, Stat.LCK]

# Species defaults (just human for now — add more species here)
SPECIES_DEFAULTS = {
    'human': {
        Stat.STR: 10, Stat.VIT: 10, Stat.AGL: 10, Stat.PER: 10,
        Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10,
        'size': 'medium', 'prudishness': 0.5,
    },
}


def random_stats(profile: str = 'balanced') -> dict:
    """Generate random base stats with a profile bias."""
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
    elif profile == 'social':
        base[Stat.CHR] = random.randint(14, 18)
        base[Stat.INT] = random.randint(12, 16)
        base[Stat.PER] = random.randint(12, 16)
        base[Stat.STR] = random.randint(4, 10)

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


def random_armor() -> Wearable:
    """Create random armor piece."""
    templates = [
        ('Leather Cap', Slot.HEAD, {Stat.ARMOR: 1}),
        ('Chain Shirt', Slot.CHEST, {Stat.ARMOR: 3, Stat.AGL: -1}),
        ('Iron Helm', Slot.HEAD, {Stat.ARMOR: 2}),
        ('Boots', Slot.FEET, {Stat.MOVE_SPEED: 0, Stat.ARMOR: 1}),
        ('Shield', Slot.HAND_L, {Stat.BLOCK: 3, Stat.ARMOR: 1}),
    ]
    name, slot, buffs = random.choice(templates)
    return Wearable(
        name=name, weight=random.uniform(1.0, 8.0), value=random.uniform(2.0, 12.0),
        slots=[slot], slot_count=1, buffs=buffs,
    )


def random_consumable() -> Consumable:
    """Create a random consumable."""
    templates = [
        ('Health Potion', {Stat.HP_CURR: 5}, 0, 3),
        ('Stamina Tonic', {Stat.STAM_REGEN: 3}, 10.0, 5),
        ('Strength Draught', {Stat.STR: 3}, 15.0, 8),
    ]
    name, buffs, duration, value = random.choice(templates)
    return Consumable(
        name=name, weight=0.3, value=value, quantity=random.randint(1, 3),
        buffs=buffs, duration=duration,
    )


def spawn_creature(game_map: Map, location: MapKey,
                   species: str = 'human',
                   profile: str = 'balanced',
                   age: int = None,
                   sex: str = None,
                   deity: str = None,
                   behavior=None,
                   name: str = None,
                   observation_mask: str = None) -> Creature:
    """Spawn a fully-realized creature with genetics, equipment, gold, deity.

    This is the canonical creature spawner for training and gameplay.
    """
    species_data = SPECIES_DEFAULTS.get(species, SPECIES_DEFAULTS['human'])

    # Sex
    if sex is None:
        sex = random.choice(('male', 'female'))

    # Chromosomes + genetic stat modification
    chromosomes = generate_chromosomes(sex)
    genetic_mods = express(chromosomes)
    species_stats = {k: v for k, v in species_data.items() if isinstance(k, Stat)}
    base_stats = apply_genetics(species_stats, genetic_mods)

    # Profile overlay (training diversity)
    profile_stats = random_stats(profile)
    # Blend: 60% genetics + 40% profile for training variety
    final_stats = {}
    for s in BASE_STATS:
        gen_val = base_stats.get(s, 10)
        prof_val = profile_stats.get(s, 10)
        final_stats[s] = max(1, int(gen_val * 0.6 + prof_val * 0.4))

    # Level
    level = random.randint(1, 5)
    final_stats[Stat.LVL] = level

    # Age
    if age is None:
        age = random.randint(18, 200)  # adults for training

    # Deity
    if deity is None:
        if random.random() < 0.7:  # 70% have a deity
            deity = random.choice([g.name for g in DEFAULT_GODS])

    # Prudishness
    prudishness = species_data.get('prudishness', 0.5)
    prudishness += random.uniform(-0.2, 0.2)
    prudishness = max(0.0, min(1.0, prudishness))

    # Name
    if name is None:
        name = f'{species}_{sex[0]}_{random.randint(1000, 9999)}'

    # Create creature
    c = Creature(
        current_map=game_map,
        location=location,
        name=name,
        species=species,
        stats=final_stats,
        sex=sex,
        age=age,
        prudishness=prudishness,
        chromosomes=chromosomes,
        behavior=behavior or RandomWanderBehavior(),
        move_interval=500,
        size=species_data.get('size', 'medium'),
    )

    # Deity + piety
    c.deity = deity
    if deity:
        c.piety = random.uniform(0.1, 0.8)

    # Gold
    c.gold = random.randint(5, 50 + level * 20)

    # Equipment
    if random.random() < 0.7:
        w = random_weapon()
        c.inventory.items.append(w)
        c.equip(w)
        c._item_prices[id(w)] = w.value

    if random.random() < 0.5:
        a = random_armor()
        c.inventory.items.append(a)
        c.equip(a)
        c._item_prices[id(a)] = a.value

    # Consumables
    if random.random() < 0.4:
        cons = random_consumable()
        c.inventory.items.append(cons)

    # Observation mask
    if observation_mask:
        c.observation_mask = observation_mask

    return c


def generate_arena(cols: int = 20, rows: int = 20,
                   num_creatures: int = 6,
                   obstacle_density: float = 0.1,
                   profiles: list[str] = None,
                   species_mix: dict[str, float] = None,
                   mask_probability: float = 0.0,
                   mask_pool: list[str] = None) -> dict:
    """Generate a random arena with fully-realized creatures.

    Args:
        cols, rows: map dimensions
        num_creatures: how many creatures to place
        obstacle_density: fraction of unwalkable tiles (0.0-1.0)
        profiles: stat profiles to cycle through
        species_mix: {species: probability} for species selection
        mask_probability: chance each creature gets an observation mask
        mask_pool: list of mask preset names to draw from

    Returns:
        dict with keys: map, creatures, cols, rows
    """
    profiles = profiles or ['balanced', 'fighter', 'mage', 'rogue', 'social', 'random']
    species_mix = species_mix or {'human': 1.0}
    mask_pool = mask_pool or ['socially_deaf', 'blind', 'fearless', 'feral',
                              'impulsive', 'nearsighted']

    # Normalize species probabilities
    species_list = list(species_mix.keys())
    species_weights = [species_mix[s] for s in species_list]

    # Generate map with random obstacles
    tiles = {}
    for x in range(cols):
        for y in range(rows):
            walkable = random.random() >= obstacle_density
            tiles[MapKey(x, y, 0)] = Tile(walkable=walkable)

    tiles[MapKey(0, 0, 0)] = Tile(walkable=True)

    # Scatter purpose tiles — creates small clusters of purposeful areas
    from classes.actions import TILE_PURPOSES
    used_purposes = random.sample(TILE_PURPOSES,
                                  min(6, len(TILE_PURPOSES)))
    walkable_keys = [k for k, t in tiles.items() if t.walkable]
    for purpose in used_purposes:
        if not walkable_keys:
            break
        center = random.choice(walkable_keys)
        # Small 3x3 cluster
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                pk = MapKey(center.x + dx, center.y + dy, 0)
                if pk in tiles and tiles[pk].walkable:
                    tiles[pk].purpose = purpose

    game_map = Map(tile_set=tiles, entrance=(0, 0),
                   x_max=cols, y_max=rows)

    walkable_tiles = [k for k, t in tiles.items() if t.walkable]
    random.shuffle(walkable_tiles)

    creatures = []
    for i in range(min(num_creatures, len(walkable_tiles))):
        loc = walkable_tiles[i]
        profile = profiles[i % len(profiles)]
        species = random.choices(species_list, weights=species_weights, k=1)[0]

        # Maybe apply observation mask
        mask = None
        if mask_probability > 0 and random.random() < mask_probability:
            mask = random.choice(mask_pool)

        c = spawn_creature(
            game_map=game_map,
            location=loc,
            species=species,
            profile=profile,
            observation_mask=mask,
        )
        creatures.append(c)

    # Give some creatures pre-existing relationships
    for c in creatures:
        for other in creatures:
            if other is c:
                continue
            if random.random() < 0.3:
                c.record_interaction(other, random.uniform(-5, 10))

    return {
        'map': game_map,
        'creatures': creatures,
        'cols': cols,
        'rows': rows,
    }


def _load_db_items():
    """Load all items from the DB and return instantiated objects by key."""
    import sqlite3, json
    from pathlib import Path as P
    from classes.inventory import CLASS_MAP, Slot as S
    db = P(__file__).parent.parent.parent / 'src' / 'data' / 'game.db'
    if not db.exists():
        return {}
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    items = {}
    slot_map = {}
    for r in con.execute('SELECT item_key, slot FROM item_slots'):
        slot_map.setdefault(r['item_key'], []).append(S(r['slot']))
    for r in con.execute('SELECT * FROM items'):
        cls = CLASS_MAP.get(r['class'])
        if cls is None:
            continue
        kw = dict(name=r['name'], weight=r['weight'] or 0, value=r['value'] or 0,
                  inventoriable=bool(r['inventoriable']),
                  buffs=json.loads(r['buffs'] or '{}'))
        if r['sprite_name']:
            kw['sprite_name'] = r['sprite_name']
        if r['class'] in ('Stackable','Consumable','Ammunition'):
            kw['max_stack_size'] = r['max_stack_size'] or 99
            kw['quantity'] = r['quantity'] or 1
        if r['class'] == 'Consumable':
            kw['duration'] = r['duration'] or 0
        if r['class'] == 'Ammunition':
            kw['damage'] = r['damage'] or 0
            kw['destroy_on_use_probability'] = r['destroy_on_use_probability'] or 1.0
            kw['recoverable'] = bool(r['recoverable']) if r['recoverable'] is not None else True
        if r['class'] in ('Weapon','Wearable'):
            kw['slots'] = slot_map.get(r['key'], [])
            kw['slot_count'] = r['slot_count'] or 1
            kw['durability_max'] = r['durability_max'] or 100
            kw['durability_current'] = r['durability_current'] or 100
        if r['class'] == 'Weapon':
            kw['damage'] = r['damage'] or 0
            kw['attack_time_ms'] = r['attack_time_ms'] or 500
            kw['range'] = r['range'] or 1
        try:
            items[r['key']] = cls(**kw)
        except Exception:
            pass
    con.close()
    return items


def generate_trade_scenario(cols: int = 25, rows: int = 25,
                            num_creatures: int = 10) -> dict:
    """Generate an asymmetric trading scenario.

    One creature (the merchant) gets every item in the DB and no gold.
    All other creatures get lots of gold and no items.
    Items are also scattered on random tiles.

    Watch: items flow from merchant to buyers via trade,
    gold flows from buyers to merchant, items get dropped and picked up.
    """
    db_items = _load_db_items()
    if not db_items:
        print('Warning: no items in DB, using default arena')
        return generate_arena(cols=cols, rows=rows, num_creatures=num_creatures)

    tiles = {}
    for x in range(cols):
        for y in range(rows):
            walkable = random.random() >= 0.05
            tiles[MapKey(x, y, 0)] = Tile(walkable=walkable)
    tiles[MapKey(0, 0, 0)] = Tile(walkable=True)
    game_map = Map(tile_set=tiles, entrance=(0, 0), x_max=cols, y_max=rows)

    walkable_tiles = [k for k, t in tiles.items() if t.walkable]
    random.shuffle(walkable_tiles)

    creatures = []

    # Creature 0: THE MERCHANT — all items, no gold
    merchant = spawn_creature(
        game_map=game_map, location=walkable_tiles[0],
        species='human', profile='social', name='Merchant',
        age=40,
    )
    merchant.gold = 0
    # Give one copy of every item
    import copy
    for key, item in db_items.items():
        item_copy = copy.deepcopy(item)
        merchant.inventory.items.append(item_copy)
        merchant._item_prices[id(item_copy)] = item_copy.value
    creatures.append(merchant)

    # Creatures 1-N: BUYERS — lots of gold, no items
    species_options = ['human', 'orc']
    for i in range(1, min(num_creatures, len(walkable_tiles))):
        species = random.choice(species_options)
        c = spawn_creature(
            game_map=game_map, location=walkable_tiles[i],
            species=species,
            profile=random.choice(['fighter', 'mage', 'rogue', 'balanced']),
        )
        # Clear inventory, give lots of gold
        c.inventory.items.clear()
        c.equipment.clear()
        c.gold = random.randint(100, 500)
        creatures.append(c)

    # Scatter some items on random tiles
    for i, (key, item) in enumerate(db_items.items()):
        if i >= 15:
            break
        tile_key = walkable_tiles[num_creatures + i] if num_creatures + i < len(walkable_tiles) else walkable_tiles[-1]
        tile = tiles[tile_key]
        item_copy = copy.deepcopy(item)
        tile.inventory.items.append(item_copy)

    # Scatter gold on some tiles
    for i in range(10):
        idx = num_creatures + 15 + i
        if idx < len(walkable_tiles):
            tiles[walkable_tiles[idx]].gold = random.randint(10, 50)

    # Pre-existing relationships
    for c in creatures:
        for other in creatures:
            if other is c:
                continue
            if random.random() < 0.3:
                c.record_interaction(other, random.uniform(-3, 8))

    return {
        'map': game_map,
        'creatures': creatures,
        'cols': cols,
        'rows': rows,
    }
