"""
Headless smoke tests for core creature mechanics.
Run from src/:  python -m tests.test_mechanics
"""
import sys
from pathlib import Path

# Ensure src/ is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from classes.maps import Map, MapKey, Tile
from classes.creature import Creature
from classes.inventory import (
    Item, Weapon, Wearable, Consumable, Stackable, Slot, Inventory
)
from classes.stats import Stat

PASS = 0
FAIL = 0


def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def make_map(cols=10, rows=10):
    """Create a simple map with walkable tiles."""
    tiles = {}
    for x in range(cols):
        for y in range(rows):
            tiles[MapKey(x, y, 0)] = Tile(walkable=True)
    return Map(tile_set=tiles, entrance=(0, 0), x_max=cols, y_max=rows)


def make_creature(game_map, x=0, y=0, **kwargs):
    """Create a creature at a given location with default stats."""
    defaults = {Stat.STR: 14, Stat.VIT: 12, Stat.AGL: 10,
                Stat.PER: 10, Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10}
    defaults.update(kwargs.pop('stats', {}))
    return Creature(
        current_map=game_map,
        location=MapKey(x, y, 0),
        name=kwargs.pop('name', 'TestCreature'),
        stats=defaults,
        **kwargs,
    )


# ==========================================================================
print("\n=== Stats ===")
m = make_map()
c = make_creature(m, stats={Stat.STR: 16, Stat.AGL: 14, Stat.VIT: 12})

check("STR active = 16", c.stats.active[Stat.STR]() == 16)
check("MELEE_DMG = dmod(16) = 3", c.stats.active[Stat.MELEE_DMG]() == 3)
check("MOVE_SPEED = 4 + dmod(14) = 6 TPS", c.stats.active[Stat.MOVE_SPEED]() == 6)
check("CARRY_WEIGHT = 50 + dmod(16)*20 = 110", c.stats.active[Stat.CARRY_WEIGHT]() == 110)

# ==========================================================================
print("\n=== Pickup / Drop ===")
m2 = make_map()
c2 = make_creature(m2, x=3, y=3)
tile = m2.tiles[MapKey(3, 3, 0)]

sword = Item(name='Sword', weight=5.0, inventoriable=True)
tile.inventory.items.append(sword)

check("Sword on tile", sword in tile.inventory.items)
check("Pickup succeeds", c2.pickup(sword))
check("Sword in creature inventory", sword in c2.inventory.items)
check("Sword NOT on tile", sword not in tile.inventory.items)

check("Drop succeeds", c2.drop(sword))
check("Sword back on tile", sword in tile.inventory.items)
check("Sword NOT in creature inventory", sword not in c2.inventory.items)

# Pickup from wrong tile
c2_far = make_creature(m2, x=0, y=0, name='FarCreature')
check("Pickup from wrong tile fails", not c2_far.pickup(sword))

# Non-inventoriable
boulder = Item(name='Boulder', weight=1.0, inventoriable=False)
tile.inventory.items.append(boulder)
check("Non-inventoriable pickup fails", not c2.pickup(boulder))
tile.inventory.items.remove(boulder)

# ==========================================================================
print("\n=== Encumbrance ===")
m3 = make_map()
c3 = make_creature(m3, x=0, y=0, stats={Stat.STR: 10})  # CARRY_WEIGHT = 50
tile3 = m3.tiles[MapKey(0, 0, 0)]

carry_cap = c3.stats.active[Stat.CARRY_WEIGHT]()
check(f"Carry weight capacity = {carry_cap}", carry_cap == 50)

heavy = Item(name='Anvil', weight=51.0, inventoriable=True)
tile3.inventory.items.append(heavy)
check("Too heavy to pick up", not c3.pickup(heavy))
check("Anvil still on tile", heavy in tile3.inventory.items)

light = Item(name='Feather', weight=1.0, inventoriable=True)
tile3.inventory.items.append(light)
check("Light item pickup OK", c3.pickup(light))
check(f"Carried weight = {c3.carried_weight}", c3.carried_weight == 1.0)

# ==========================================================================
print("\n=== Equip / Unequip ===")
m4 = make_map()
c4 = make_creature(m4, x=0, y=0, stats={Stat.STR: 14})

helmet = Wearable(name='Iron Helm', weight=3.0, slots=[Slot.HEAD], slot_count=1,
                  buffs={Stat.ARMOR: 5})
c4.inventory.items.append(helmet)

armor_before = c4.stats.active[Stat.ARMOR]()
check(f"Armor before equip = {armor_before}", armor_before == 0)

check("Equip helmet", c4.equip(helmet))
check("Helmet in equipment", c4.equipped_in(Slot.HEAD) is helmet)
check("Helmet NOT in inventory", helmet not in c4.inventory.items)
armor_after = c4.stats.active[Stat.ARMOR]()
check(f"Armor after equip = {armor_after} (expected 5)", armor_after == 5)

check("Unequip helmet", c4.unequip(Slot.HEAD))
check("Helmet back in inventory", helmet in c4.inventory.items)
armor_back = c4.stats.active[Stat.ARMOR]()
check(f"Armor after unequip = {armor_back} (expected 0)", armor_back == 0)

# Two-handed weapon
greatsword = Weapon(name='Greatsword', weight=8.0,
                    slots=[Slot.HAND_L, Slot.HAND_R], slot_count=2,
                    damage=10, buffs={Stat.MELEE_DMG: 4})
c4.inventory.items.append(greatsword)
check("Equip 2h weapon", c4.equip(greatsword))
check("Occupies HAND_L", c4.equipped_in(Slot.HAND_L) is greatsword)
check("Occupies HAND_R", c4.equipped_in(Slot.HAND_R) is greatsword)

# STR 14 → dmod = 2, + 4 from greatsword buff = 6
melee_with = c4.stats.active[Stat.MELEE_DMG]()
check(f"MELEE_DMG with greatsword = {melee_with} (base 2 + 4 = 6)", melee_with == 6)

check("Unequip from HAND_L clears both", c4.unequip(Slot.HAND_L))
check("HAND_R also cleared", c4.equipped_in(Slot.HAND_R) is None)

# ==========================================================================
print("\n=== Requirements ===")
m5 = make_map()
weak = make_creature(m5, x=0, y=0, stats={Stat.STR: 8}, name='Weakling')

heavy_axe = Weapon(name='Battle Axe', weight=6.0,
                   slots=[Slot.HAND_R], slot_count=1,
                   damage=8, requirements={Stat.STR: 12})
weak.inventory.items.append(heavy_axe)
check("Weak creature can't equip (STR 8 < 12)", not weak.equip(heavy_axe))
check("Axe still in inventory", heavy_axe in weak.inventory.items)

strong = make_creature(m5, x=1, y=0, stats={Stat.STR: 14}, name='Strong')
strong.inventory.items.append(heavy_axe)
weak.inventory.items.remove(heavy_axe)
check("Strong creature can equip (STR 14 >= 12)", strong.equip(heavy_axe))

# ==========================================================================
print("\n=== Movement ===")
m6 = make_map(cols=5, rows=5)
c6 = make_creature(m6, x=2, y=2)
check("Starts at (2,2)", c6.location.x == 2 and c6.location.y == 2)

c6.move(1, 0, 5, 5)
check("Move east → (3,2)", c6.location.x == 3 and c6.location.y == 2)

c6.move(0, -1, 5, 5)
check("Move north → (3,1)", c6.location.x == 3 and c6.location.y == 1)

# Can't move off map
c6.move(-10, 0, 5, 5)
check("Clamped at west edge (0,1)", c6.location.x == 0 and c6.location.y == 1)

# ==========================================================================
print("\n=== Relationships ===")
m7 = make_map()
a = make_creature(m7, x=0, y=0, name='Alice')
b = make_creature(m7, x=1, y=0, name='Bob')

a.record_interaction(b, 5.0)
a.record_interaction(b, -2.0)
rel = a.get_relationship(b)
check(f"Sentiment = {rel[0]} (expected 3.0)", rel[0] == 3.0)
check(f"Count = {rel[1]} (expected 2)", rel[1] == 2)
check(f"Min = {rel[2]} (expected -2.0)", rel[2] == -2.0)
check(f"Max = {rel[3]} (expected 5.0)", rel[3] == 5.0)

conf = a.relationship_confidence(b)
check(f"Confidence = {conf:.2f} (expected 2/7 ≈ 0.29)", abs(conf - 2/7) < 0.01)

curiosity = a.curiosity_toward(b)
check(f"Curiosity = {curiosity:.2f} (expected 1/3 ≈ 0.33)", abs(curiosity - 1/3) < 0.01)

stranger = make_creature(m7, x=2, y=0, name='Stranger')
check("Curiosity toward stranger = 1.0", a.curiosity_toward(stranger) == 1.0)

# ==========================================================================
print("\n=== Rumors ===")
a.receive_rumor(b, stranger.uid, sentiment=-5.0, confidence=0.8, tick=100)
opinion = a.rumor_opinion(stranger.uid, current_tick=100)
check(f"Rumor opinion of stranger = {opinion:.2f} (negative)", opinion < 0)

# ==========================================================================
print("\n=== HP Regen ===")
m8 = make_map()
c8 = make_creature(m8, x=0, y=0, stats={Stat.VIT: 14, Stat.LVL: 10})

hp_max = c8.stats.active[Stat.HP_MAX]()
check(f"HP_MAX = {hp_max} (should be large enough)", hp_max > 20)
c8.stats.base[Stat.HP_CURR] = 1
hp_before = c8.stats.active[Stat.HP_CURR]()

# Simulate being hit at tick 0, then processing regen ticks
c8.on_hit(0)
delay_s = c8.stats.active[Stat.HP_REGEN_DELAY]()
delay_ms = int(delay_s * 1000)

# Before delay: no regen
c8._do_hp_regen(delay_ms - 1)
check("No regen before delay", c8.stats.active[Stat.HP_CURR]() == hp_before)

# After delay: regen kicks in (fibonacci: 1, 1, 2, 3, ...)
c8._do_hp_regen(delay_ms + 1)
hp_after = c8.stats.active[Stat.HP_CURR]()
check(f"HP after first regen tick: {hp_before} → {hp_after}", hp_after == hp_before + 1)

# Fibonacci: (1,1) → heal 1, advance to (1,2)
# Next: heal 1, advance to (2,3)
# Next: heal 2, advance to (3,5)
c8._do_hp_regen(delay_ms + 2001)
hp_after2 = c8.stats.active[Stat.HP_CURR]()
check(f"HP after 2nd regen (fib=1): {hp_after} → {hp_after2}", hp_after2 == hp_after + 1)

c8._do_hp_regen(delay_ms + 3001)
hp_after3 = c8.stats.active[Stat.HP_CURR]()
check(f"HP after 3rd regen (fib=2): {hp_after2} → {hp_after3}", hp_after3 == hp_after2 + 2)

c8._do_hp_regen(delay_ms + 4001)
hp_after4 = c8.stats.active[Stat.HP_CURR]()
check(f"HP after 4th regen (fib=3): {hp_after3} → {hp_after4}", hp_after4 == hp_after3 + 3)

# ==========================================================================
print("\n=== Stat Contests ===")
m9 = make_map()
attacker = make_creature(m9, x=0, y=0, stats={Stat.PER: 18}, name='Attacker')
defender = make_creature(m9, x=1, y=0, stats={Stat.AGL: 18}, name='Defender')

# Run many contests to check statistical distribution
wins = sum(1 for _ in range(1000)
           if attacker.stats.contest(defender.stats, 'accuracy_vs_dodge')[0])
check(f"Accuracy vs dodge: {wins}/1000 wins (expected ~50%)", 200 < wins < 800)

# ==========================================================================
print("\n=== Leveling ===")
m10 = make_map()
c10 = make_creature(m10, x=0, y=0)
old_lvl = c10.stats.base[Stat.LVL]
old_points = c10.stats.unspent_stat_points

c10.gain_exp(100)
check(f"EXP gained: {c10.stats.base[Stat.EXP]}", c10.stats.base[Stat.EXP] >= 100)

# Allocate stat point
if c10.stats.unspent_stat_points > 0:
    str_before = c10.stats.base[Stat.STR]
    check("Allocate STR point", c10.stats.allocate_stat_point(Stat.STR))
    check(f"STR increased {str_before} → {c10.stats.base[Stat.STR]}",
          c10.stats.base[Stat.STR] == str_before + 1)

# ==========================================================================
print("\n=== Sex & Age ===")
m11 = make_map()
c_male = make_creature(m11, x=0, y=0, sex='male', name='Male')
c_rand = make_creature(m11, x=1, y=0, name='Random')

check("Explicit sex = male", c_male.sex == 'male')
check("Random sex is male or female", c_rand.sex in ('male', 'female'))

c_young = make_creature(m11, x=0, y=1, age=5, name='Young')
c_adult = make_creature(m11, x=1, y=1, age=100, name='Adult')
c_old = make_creature(m11, x=2, y=1, age=400, name='Old')
check("age=5 → young", c_young.age_class == 'young')
check("age=100 → adult", c_adult.age_class == 'adult')
check("age=400 → old", c_old.age_class == 'old')

# ==========================================================================
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
if FAIL:
    sys.exit(1)
else:
    print("All tests passed!")
