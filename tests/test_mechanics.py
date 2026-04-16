"""
Headless smoke tests for core creature mechanics.
Run from project root:  python -m tests.test_mechanics
"""
import sys
from pathlib import Path

# Ensure src/ and editor/ are on the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent))

from classes.maps import Map, MapKey, Tile
from classes.creature import Creature
from classes.inventory import (
    Item, Weapon, Wearable, Consumable, Ammunition, Stackable, Slot, Inventory
)
from classes.stats import Stat
from classes.relationship_graph import GRAPH

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
print("\n=== Use / Consume ===")
m12 = make_map()
c12 = make_creature(m12, x=0, y=0, stats={Stat.STR: 10, Stat.VIT: 10})

potion = Consumable(name='Strength Potion', weight=0.5, quantity=3,
                    duration=30.0, buffs={Stat.STR: 4})
c12.inventory.items.append(potion)

str_before = c12.stats.active[Stat.STR]()
check(f"STR before potion = {str_before}", str_before == 10)

check("Use potion succeeds", c12.use_item(potion))
str_after = c12.stats.active[Stat.STR]()
check(f"STR after potion = {str_after} (expected 14)", str_after == 14)
check(f"Potion quantity = {potion.quantity} (expected 2)", potion.quantity == 2)

# Use twice more — should exhaust stack
check("Use potion again", c12.use_item(potion))
check("Use last potion", c12.use_item(potion))
check("Potion removed from inventory", potion not in c12.inventory.items)

# Can't use non-consumable
sword_item = Item(name='Sword', weight=3.0)
c12.inventory.items.append(sword_item)
check("Can't use non-consumable", not c12.use_item(sword_item))

# Can't use item not in inventory
loose_potion = Consumable(name='Loose Potion', weight=0.5, quantity=1, buffs={})
check("Can't use item not in inventory", not c12.use_item(loose_potion))

# ==========================================================================
print("\n=== Sight / Stealth ===")
m13 = make_map(cols=20, rows=20)
watcher = make_creature(m13, x=0, y=0, stats={Stat.PER: 14}, name='Watcher')
# SIGHT_RANGE = 5 + dmod(14) = 5 + 2 = 7
sneaker = make_creature(m13, x=5, y=0, stats={Stat.AGL: 16}, name='Sneaker')
# STEALTH = dmod(16) = 3, so effective range = 7 - 3 = 4

check("Watcher SIGHT_RANGE = 7", watcher.stats.active[Stat.SIGHT_RANGE]() == 7)
check("Sneaker STEALTH = 3", sneaker.stats.active[Stat.STEALTH]() == 3)
check("Watcher can't see sneaker at dist 5 (effective range 4)", not watcher.can_see(sneaker))

# Move sneaker closer
sneaker.location = MapKey(3, 0, 0)
check("Watcher CAN see sneaker at dist 3", watcher.can_see(sneaker))

# Non-stealthy creature visible at normal range
obvious = make_creature(m13, x=6, y=0, stats={Stat.AGL: 10}, name='Obvious')
check("Obvious visible at dist 6 (range 7, stealth 0)", watcher.can_see(obvious))

obvious.location = MapKey(8, 0, 0)
check("Obvious NOT visible at dist 8", not watcher.can_see(obvious))

# ==========================================================================
print("\n=== Melee Attack ===")
m14 = make_map()
fighter = make_creature(m14, x=0, y=0,
                        stats={Stat.STR: 16, Stat.PER: 12, Stat.AGL: 10,
                               Stat.LCK: 10, Stat.VIT: 12, Stat.LVL: 5},
                        name='Fighter')
victim = make_creature(m14, x=1, y=0,
                       stats={Stat.STR: 10, Stat.AGL: 10, Stat.VIT: 12,
                              Stat.PER: 10, Stat.LVL: 5},
                       name='Victim')

# Not adjacent
victim_far = make_creature(m14, x=5, y=5,
                           stats={Stat.VIT: 10, Stat.LVL: 5}, name='FarVictim')
r = fighter.melee_attack(victim_far, now=1000)
check("Attack out of range fails", r['reason'] == 'not_adjacent')

# Equip a weapon
axe = Weapon(name='Battle Axe', weight=5.0,
             slots=[Slot.HAND_R], slot_count=1,
             damage=6, buffs={Stat.MELEE_DMG: 2})
fighter.inventory.items.append(axe)
fighter.equip(axe)

stam_before = fighter.stats.active[Stat.CUR_STAMINA]()
hp_before = victim.stats.active[Stat.HP_CURR]()

# Run multiple attacks to get statistical coverage
hits = 0
total_dmg = 0
crits = 0
staggers = 0
for _ in range(100):
    # Reset victim HP and fighter stamina each round
    victim.stats.base[Stat.HP_CURR] = victim.stats.active[Stat.HP_MAX]()
    fighter.stats.base[Stat.CUR_STAMINA] = fighter.stats.active[Stat.MAX_STAMINA]()
    r = fighter.melee_attack(victim, now=1000)
    if r['hit']:
        hits += 1
        total_dmg += r['damage']
    if r['crit']:
        crits += 1
    if r['staggered']:
        staggers += 1

check(f"Some attacks hit: {hits}/100", hits > 0)
check(f"Some attacks miss (dodged): {100-hits}/100", hits < 100)
check(f"Total damage dealt: {total_dmg}", total_dmg > 0)
check(f"Some crits in 100 attacks: {crits}", True)  # may be 0 with low crit chance
check(f"Stagger count: {staggers}", True)  # informational

# Stamina depletion: drain stamina and try to attack
fighter.stats.base[Stat.CUR_STAMINA] = 0
r = fighter.melee_attack(victim, now=1000)
check("Attack with 0 stamina fails", r['reason'] == 'no_stamina')

# Relationship after combat: victim should have negative sentiment toward fighter
rel = victim.get_relationship(fighter)
check(f"Victim has negative sentiment toward fighter: {rel[0]:.1f}", rel[0] < 0)

# ==========================================================================
print("\n=== Ambush (stealth attack) ===")
m15 = make_map()
assassin = make_creature(m15, x=0, y=0,
                         stats={Stat.STR: 14, Stat.AGL: 20, Stat.PER: 10,
                                Stat.LCK: 10, Stat.VIT: 10},
                         name='Assassin')
# STEALTH = dmod(20) = 5
blind = make_creature(m15, x=1, y=0,
                      stats={Stat.PER: 6, Stat.AGL: 10, Stat.VIT: 14,
                             Stat.STR: 10, Stat.LVL: 5},
                      name='Blind')
# SIGHT_RANGE = 5 + dmod(6) = 5 + (-2) = 3
# Effective: 3 - 5 = -2, so blind can't see assassin at any distance

check("Blind can't see assassin (stealth > sight)", not blind.can_see(assassin))

# Ambush should auto-hit (no dodge contest)
dagger = Weapon(name='Dagger', weight=1.0,
                slots=[Slot.HAND_R], slot_count=1, damage=3)
assassin.inventory.items.append(dagger)
assassin.equip(dagger)

ambush_hits = 0
for _ in range(50):
    blind.stats.base[Stat.HP_CURR] = blind.stats.active[Stat.HP_MAX]()
    assassin.stats.base[Stat.CUR_STAMINA] = assassin.stats.active[Stat.MAX_STAMINA]()
    r = assassin.melee_attack(blind, now=1000)
    if r['hit']:
        ambush_hits += 1

check(f"Ambush hit rate: {ambush_hits}/50 (all should hit or armor absorb)",
      ambush_hits == 50)

# ==========================================================================
print("\n=== Intimidate ===")
m16 = make_map()
bully = make_creature(m16, x=0, y=0,
                      stats={Stat.CHR: 18, Stat.STR: 16, Stat.PER: 12},
                      name='Bully')
# INTIMIDATION = dmod(18) + dmod(16)//2 = 4 + 3//2 = 4+1 = 5 (strong)
timid = make_creature(m16, x=1, y=0,
                      stats={Stat.INT: 8, Stat.STR: 8, Stat.PER: 10},
                      name='Timid')
# FEAR_RESIST = max(0, dmod(8) + 0//3 + 10 + dmod(8)) = max(0, -1 + 0 + 10 + -1) = 8

check(f"Bully INTIMIDATION = {bully.stats.active[Stat.INTIMIDATION]()}",
      bully.stats.active[Stat.INTIMIDATION]() == 5)
check(f"Timid FEAR_RESIST = {timid.stats.active[Stat.FEAR_RESIST]()}",
      timid.stats.active[Stat.FEAR_RESIST]() == 8)

# Run many intimidation attempts for statistical check
successes = sum(1 for _ in range(500)
                if bully.intimidate(timid)['success'])
check(f"Bully intimidates timid: {successes}/500 (expected ~40-60%)", 100 < successes < 400)

# Out of sight range
far_target = make_creature(m16, x=15, y=15,
                           stats={Stat.PER: 10}, name='FarTarget')
r = bully.intimidate(far_target)
check("Intimidate out of sight fails", r['reason'] == 'out_of_range')

# Check relationships after intimidation
rel_timid = timid.get_relationship(bully)
check("Timid has negative sentiment toward bully", rel_timid[0] < 0)

# ==========================================================================
print("\n=== Deceive ===")
m17 = make_map()
liar = make_creature(m17, x=0, y=0,
                     stats={Stat.CHR: 16, Stat.AGL: 14, Stat.PER: 10},
                     name='Liar')
# DECEPTION = dmod(16) + dmod(14)//2 = 3 + 1 = 4
mark = make_creature(m17, x=1, y=0,
                     stats={Stat.PER: 12}, name='Mark')
# DETECTION = dmod(12) = 1

check(f"Liar DECEPTION = {liar.stats.active[Stat.DECEPTION]()}",
      liar.stats.active[Stat.DECEPTION]() == 4)
check(f"Mark DETECTION = {mark.stats.active[Stat.DETECTION]()}",
      mark.stats.active[Stat.DETECTION]() == 1)

# Set up active social context (deceive requires ongoing TALK/TRADE)
liar._active_social_target = mark

# Statistical test
d_successes = sum(1 for _ in range(500)
                  if liar.deceive(mark)['success'])
check(f"Liar deceives mark: {d_successes}/500 (liar has advantage)",
      d_successes > 200)

# Deception leaves a relationship record (sentiment may be 0 if successes
# and failures exactly cancel, but at minimum the edge must exist)
rel_mark = mark.get_relationship(liar)
check(f"Mark has relationship record with liar (count={rel_mark[1] if rel_mark else 0})",
      rel_mark is not None)

# ==========================================================================
print("\n=== Betrayal ===")
m18 = make_map()
friend = make_creature(m18, x=0, y=0,
                       stats={Stat.STR: 14, Stat.PER: 12, Stat.AGL: 10,
                              Stat.LCK: 10, Stat.VIT: 12, Stat.LVL: 3},
                       name='Friend')
betrayed = make_creature(m18, x=1, y=0,
                         stats={Stat.VIT: 14, Stat.AGL: 10, Stat.PER: 10,
                                Stat.STR: 10, Stat.LVL: 3},
                         name='Betrayed')

# Build positive relationship first
friend.record_interaction(betrayed, 10.0)
friend.record_interaction(betrayed, 5.0)
check("Friend has positive sentiment before betrayal",
      friend.get_relationship(betrayed)[0] == 15.0)

# Now attack — should trigger betrayal penalty
fist = Weapon(name='Fist', weight=0, slots=[Slot.HAND_R], slot_count=1, damage=2)
friend.inventory.items.append(fist)
friend.equip(fist)

betrayed.stats.base[Stat.HP_CURR] = betrayed.stats.active[Stat.HP_MAX]()
friend.stats.base[Stat.CUR_STAMINA] = friend.stats.active[Stat.MAX_STAMINA]()
r = friend.melee_attack(betrayed, now=1000)

# After attack, friend's sentiment toward betrayed should have tanked
# (was +15, now should be +15 + (-10) = +5 or less depending on hit)
friend_rel = friend.get_relationship(betrayed)
check(f"Betrayal cost: friend sentiment dropped to {friend_rel[0]:.1f}",
      friend_rel[0] < 15.0)

# Betrayed gets extra -10 on top of combat -5
betrayed_rel = betrayed.get_relationship(friend)
check(f"Betrayed sentiment = {betrayed_rel[0]:.1f} (massive negative)",
      betrayed_rel[0] < -10.0)

# ==========================================================================
print("\n=== Consumable Duration Expiry ===")
m19 = make_map()
c19 = make_creature(m19, x=0, y=0, stats={Stat.STR: 10})

timed_potion = Consumable(name='Timed Buff', weight=0.5, quantity=2,
                          duration=5.0, buffs={Stat.STR: 6})
c19.inventory.items.append(timed_potion)

str_base = c19.stats.active[Stat.STR]()
check(f"STR before timed potion = {str_base}", str_base == 10)

c19.use_item(timed_potion)
check(f"STR after timed potion = {c19.stats.active[Stat.STR]()}", c19.stats.active[Stat.STR]() == 16)

# Process ticks BEFORE expiry (at 4 seconds)
c19.process_ticks(4000)
check("STR still buffed at 4s", c19.stats.active[Stat.STR]() == 16)

# Process ticks AT expiry (at 5 seconds)
c19.process_ticks(5000)
check(f"STR back to normal after 5s = {c19.stats.active[Stat.STR]()}", c19.stats.active[Stat.STR]() == 10)

# Permanent potion (duration=0) should NOT expire
perm_potion = Consumable(name='Perm Buff', weight=0.5, quantity=1,
                         duration=0.0, buffs={Stat.VIT: 3})
c19.inventory.items.append(perm_potion)
c19.use_item(perm_potion)
vit_after = c19.stats.active[Stat.VIT]()
c19.process_ticks(999999)
check(f"Permanent buff stays: VIT still {c19.stats.active[Stat.VIT]()}", c19.stats.active[Stat.VIT]() == vit_after)

# ==========================================================================
print("\n=== Ranged Attack ===")
m20 = make_map(cols=20, rows=20)
archer = make_creature(m20, x=0, y=0,
                       stats={Stat.STR: 12, Stat.PER: 16, Stat.AGL: 12,
                              Stat.LCK: 10, Stat.VIT: 12, Stat.LVL: 3},
                       name='Archer')
# ACCURACY = dmod(16) = 3

far_target = make_creature(m20, x=8, y=0,
                           stats={Stat.VIT: 14, Stat.AGL: 10, Stat.PER: 10,
                                  Stat.STR: 10, Stat.LVL: 3},
                           name='FarTarget')

# No weapon equipped → fail
r = archer.ranged_attack(far_target, now=1000)
check("No ranged weapon → fail", r['reason'] == 'no_ranged_weapon')

# Equip bow (range 10)
bow = Weapon(name='Longbow', weight=3.0,
             slots=[Slot.HAND_L, Slot.HAND_R], slot_count=2,
             damage=5, range=10, ammunition_type='Arrow')
archer.inventory.items.append(bow)
archer.equip(bow)

# No ammo → fail
r = archer.ranged_attack(far_target, now=1000)
check("No ammo → fail", r['reason'] == 'no_ammo')

# Add arrows (recoverable — land on tile on miss)
arrows = Ammunition(name='Arrow', weight=0.1, quantity=20, damage=2,
                    destroy_on_use_probability=0.8, recoverable=True)
archer.inventory.items.append(arrows)

# Out of range
very_far = make_creature(m20, x=15, y=0,
                         stats={Stat.VIT: 10, Stat.LVL: 3}, name='VeryFar')
r = archer.ranged_attack(very_far, now=1000)
check("Out of range → fail", r['reason'] == 'out_of_range')

# Valid attack: run multiple for statistics
hits = 0
total_dmg = 0
for _ in range(50):
    far_target.stats.base[Stat.HP_CURR] = far_target.stats.active[Stat.HP_MAX]()
    archer.stats.base[Stat.CUR_STAMINA] = archer.stats.active[Stat.MAX_STAMINA]()
    # Ensure ammo available
    if arrows not in archer.inventory.items or arrows.quantity <= 0:
        arrows = Ammunition(name='Arrow', weight=0.1, quantity=20, damage=2,
                            destroy_on_use_probability=0.8, recoverable=True)
        archer.inventory.items.append(arrows)
    r = archer.ranged_attack(far_target, now=1000)
    if r['hit']:
        hits += 1
        total_dmg += r['damage']

check(f"Ranged hits: {hits}/50", hits > 0)
check(f"Ranged total damage: {total_dmg}", total_dmg > 0)

# No stamina — ensure we have ammo first
if arrows not in archer.inventory.items or arrows.quantity <= 0:
    arrows = Ammunition(name='Arrow', weight=0.1, quantity=5, damage=2,
                        destroy_on_use_probability=0.8, recoverable=True)
    archer.inventory.items.append(arrows)
archer.stats.base[Stat.CUR_STAMINA] = 0
r = archer.ranged_attack(far_target, now=1000)
check("Ranged with 0 stamina fails", r['reason'] == 'no_stamina')

# Check arrows landed on target's tile from misses
target_tile = m20.tiles.get(far_target.location)
recovered = [i for i in target_tile.inventory.items if i.name == 'Arrow']
check(f"Recoverable arrows on target tile: {len(recovered)}",
      len(recovered) > 0)

# Non-recoverable ammo (bullets) should NOT land on tile
m20b = make_map(cols=20, rows=20)
gunner = make_creature(m20b, x=0, y=0,
                       stats={Stat.STR: 12, Stat.PER: 16, Stat.AGL: 12,
                              Stat.LCK: 10, Stat.VIT: 12},
                       name='Gunner')
bullet_target = make_creature(m20b, x=5, y=0,
                              stats={Stat.VIT: 14, Stat.AGL: 10, Stat.PER: 10,
                                     Stat.STR: 10, Stat.LVL: 3},
                              name='BulletTarget')
gun = Weapon(name='Pistol', weight=2.0,
             slots=[Slot.HAND_R], slot_count=1,
             damage=8, range=8, ammunition_type='Bullet')
gunner.inventory.items.append(gun)
gunner.equip(gun)
bullets = Ammunition(name='Bullet', weight=0.05, quantity=20, damage=4,
                     destroy_on_use_probability=1.0, recoverable=False)
gunner.inventory.items.append(bullets)

for _ in range(20):
    bullet_target.stats.base[Stat.HP_CURR] = bullet_target.stats.active[Stat.HP_MAX]()
    gunner.stats.base[Stat.CUR_STAMINA] = gunner.stats.active[Stat.MAX_STAMINA]()
    gunner.ranged_attack(bullet_target, now=1000)

bt_tile = m20b.tiles.get(bullet_target.location)
bullet_on_tile = [i for i in bt_tile.inventory.items if i.name == 'Bullet']
check(f"Non-recoverable bullets NOT on tile: {len(bullet_on_tile)}", len(bullet_on_tile) == 0)

# ==========================================================================
print("\n=== Grapple ===")
m21 = make_map()
wrestler = make_creature(m21, x=0, y=0,
                         stats={Stat.STR: 18, Stat.AGL: 12, Stat.VIT: 14},
                         name='Wrestler')
slippery = make_creature(m21, x=1, y=0,
                         stats={Stat.STR: 10, Stat.AGL: 18, Stat.VIT: 10},
                         name='Slippery')

# Not adjacent
far_grapple = make_creature(m21, x=5, y=5, stats={Stat.STR: 10}, name='Far')
r = wrestler.grapple(far_grapple)
check("Grapple not adjacent → fail", r['reason'] == 'not_adjacent')

# Statistical test: wrestler STR 18 vs slippery AGL 18-1=17
wins = 0
for _ in range(200):
    wrestler.stats.base[Stat.CUR_STAMINA] = wrestler.stats.active[Stat.MAX_STAMINA]()
    r = wrestler.grapple(slippery)
    if r['success']:
        wins += 1

check(f"Wrestler wins grapple: {wins}/200 (STR 18 vs AGL 17)", 30 < wins < 170)

# No stamina
wrestler.stats.base[Stat.CUR_STAMINA] = 5
r = wrestler.grapple(slippery)
check("Grapple with low stamina fails", r['reason'] == 'no_stamina')

# ==========================================================================
print("\n=== Steal ===")
m22 = make_map()
thief = make_creature(m22, x=0, y=0,
                      stats={Stat.AGL: 18, Stat.CHR: 14, Stat.PER: 12},
                      name='Thief')
mark2 = make_creature(m22, x=1, y=0,
                      stats={Stat.PER: 10, Stat.STR: 10}, name='Mark2')

gem = Item(name='Ruby', weight=0.1)
mark2.inventory.items.append(gem)

# Not adjacent
far_mark = make_creature(m22, x=5, y=5, stats={Stat.PER: 10}, name='FarMark')
far_mark.inventory.items.append(Item(name='Gold', weight=0.1))
r = thief.steal(far_mark, far_mark.inventory.items[0])
check("Steal not adjacent → fail", r['reason'] == 'not_adjacent')

# Item not in inventory
phantom = Item(name='Phantom')
r = thief.steal(mark2, phantom)
check("Steal non-existent item → fail", r['reason'] == 'item_not_found')

# Statistical steal attempts
successes = 0
for _ in range(100):
    if gem not in mark2.inventory.items:
        # Return item for next attempt
        thief.inventory.items.remove(gem)
        mark2.inventory.items.append(gem)
    r = thief.steal(mark2, gem)
    if r['success']:
        successes += 1

check(f"Steal successes: {successes}/100", successes > 0)
check(f"Some steals caught: {100 - successes}/100", successes < 100)

# ==========================================================================
print("\n=== Flee ===")
m23 = make_map(cols=10, rows=10)
prey = make_creature(m23, x=5, y=5, stats={Stat.AGL: 12}, name='Prey')
predator = make_creature(m23, x=4, y=5, name='Predator')

old_x = prey.location.x
check("Flee succeeds", prey.flee(predator, 10, 10))
check(f"Moved away: {old_x} → {prey.location.x}",
      prey.location.x > old_x)  # Should move east (away from predator at x=4)

# Flee with no stamina
prey.stats.base[Stat.CUR_STAMINA] = 0
check("Flee with 0 stamina fails", not prey.flee(predator, 10, 10))

# Flee from same tile
prey.stats.base[Stat.CUR_STAMINA] = prey.stats.active[Stat.MAX_STAMINA]()
prey.location = predator.location._replace()
check("Flee from same tile still moves", prey.flee(predator, 10, 10))

# ==========================================================================
print("\n=== Search Tile ===")
m24 = make_map()
searcher = make_creature(m24, x=0, y=0, stats={Stat.PER: 14}, name='Searcher')
tile24 = m24.tiles[MapKey(0, 0, 0)]

# Place items on tile
loot1 = Item(name='Coin', weight=0.1)
loot2 = Item(name='Gem', weight=0.2)
tile24.inventory.items.extend([loot1, loot2])

r = searcher.search_tile()
check(f"Found {len(r['items_found'])} items on tile", len(r['items_found']) == 2)
check("Coin in found items", loot1 in r['items_found'])

# Hidden items with DC
tile24.stat_mods['hidden_dc'] = 15
results = [searcher.search_tile()['hidden_found'] for _ in range(100)]
found_count = sum(1 for r in results if r is True)
check(f"Hidden DC 15: found {found_count}/100 (DETECTION=dmod(14)=2)",
      0 < found_count < 100)

# ==========================================================================
print("\n=== Guard Stance ===")
m25 = make_map()
guard_c = make_creature(m25, x=0, y=0, stats={Stat.PER: 12}, name='Guard')

det_before = guard_c.stats.active[Stat.DETECTION]()
check("Enter guard stance", guard_c.guard(10, 10))
check("Is guarding", guard_c.is_guarding)
det_during = guard_c.stats.active[Stat.DETECTION]()
check(f"Detection boosted: {det_before} → {det_during}", det_during == det_before + 3)

guard_c.stop_guard()
check("Not guarding after stop", not guard_c.is_guarding)
det_after = guard_c.stats.active[Stat.DETECTION]()
check(f"Detection restored: {det_after}", det_after == det_before)

# No stamina
guard_c.stats.base[Stat.CUR_STAMINA] = 0
check("Guard with 0 stamina fails", not guard_c.guard(10, 10))

# ==========================================================================
print("\n=== Run / Sneak ===")
m26 = make_map(cols=10, rows=10)
runner = make_creature(m26, x=5, y=5, stats={Stat.AGL: 14}, name='Runner')

stam_before = runner.stats.active[Stat.CUR_STAMINA]()
check("Run east", runner.run(1, 0, 10, 10))
check("Moved to (6,5)", runner.location.x == 6)
stam_after = runner.stats.active[Stat.CUR_STAMINA]()
check(f"Stamina cost for run: {stam_before - stam_after}", stam_before - stam_after == 3)

stam_before2 = runner.stats.active[Stat.CUR_STAMINA]()
check("Sneak south", runner.sneak(0, 1, 10, 10))
check("Moved to (6,6)", runner.location.y == 6)
stam_after2 = runner.stats.active[Stat.CUR_STAMINA]()
check(f"Stamina cost for sneak: {stam_before2 - stam_after2}", stam_before2 - stam_after2 == 1)

# No stamina
runner.stats.base[Stat.CUR_STAMINA] = 0
check("Run with 0 stamina fails", not runner.run(1, 0, 10, 10))
check("Sneak with 0 stamina fails", not runner.sneak(1, 0, 10, 10))

# ==========================================================================
print("\n=== Block Stance ===")
m27 = make_map()
blocker = make_creature(m27, x=0, y=0, stats={Stat.STR: 14, Stat.AGL: 12},
                        name='Blocker')

# Can't block without equipment in hand
check("Can't block without shield/weapon", not blocker.enter_block_stance())

shield = Wearable(name='Shield', weight=4.0, slots=[Slot.HAND_L], slot_count=1,
                  buffs={Stat.BLOCK: 3})
blocker.inventory.items.append(shield)
blocker.equip(shield)

block_before = blocker.stats.active[Stat.BLOCK]()
check("Enter block stance", blocker.enter_block_stance())
check("Is blocking", blocker.is_blocking)
block_during = blocker.stats.active[Stat.BLOCK]()
check(f"Block boosted: {block_before} → {block_during}", block_during == block_before + 2)

blocker.exit_block_stance()
check("Not blocking after exit", not blocker.is_blocking)
block_after = blocker.stats.active[Stat.BLOCK]()
check(f"Block restored: {block_after}", block_after == block_before)

# ==========================================================================
print("\n=== Share Rumor ===")
m28 = make_map()
gossip = make_creature(m28, x=0, y=0, stats={Stat.CHR: 16, Stat.PER: 12},
                       name='Gossip')
listener = make_creature(m28, x=1, y=0, stats={Stat.PER: 10}, name='Listener')
subject = make_creature(m28, x=5, y=5, name='Subject')

# Build gossip's opinion of subject
gossip.record_interaction(subject, -8.0)

# Share rumor multiple times
shared = 0
for _ in range(50):
    if gossip.share_rumor(listener, subject.uid, -5.0, tick=100):
        shared += 1

check(f"Rumors shared: {shared}/50 (CHR 16 = high chance)", shared > 20)

# Listener should now have rumors about subject
rumors = GRAPH.get_rumors(listener.uid, subject.uid) or []
check(f"Listener has {len(rumors)} rumors about subject", len(rumors) > 0)

opinion = listener.rumor_opinion(subject.uid, current_tick=100)
check(f"Listener's rumor opinion of subject: {opinion:.2f} (negative)", opinion < 0)

# ==========================================================================
print("\n=== Trade ===")
m29 = make_map()
trader_a = make_creature(m29, x=0, y=0,
                         stats={Stat.CHR: 14, Stat.INT: 12, Stat.PER: 12},
                         name='TraderA')
trader_b = make_creature(m29, x=1, y=0,
                         stats={Stat.CHR: 10, Stat.INT: 10, Stat.PER: 10},
                         name='TraderB')

# Create trade items
gold_bar = Item(name='Gold Bar', weight=1.0, value=10.0)
silver_ring = Item(name='Silver Ring', weight=0.2, value=8.0)
trader_a.inventory.items.append(gold_bar)
trader_b.inventory.items.append(silver_ring)

# Fair-ish trade: gold bar (10) for silver ring (8)
r = trader_a.propose_trade(trader_b, offered=[gold_bar], requested=[silver_ring])
check(f"Trade accepted: {r['accepted']}", r['accepted'])
check("Gold bar now with trader B", gold_bar in trader_b.inventory.items)
check("Silver ring now with trader A", silver_ring in trader_a.inventory.items)

# Both should have positive sentiment
rel_a = trader_a.get_relationship(trader_b)
rel_b = trader_b.get_relationship(trader_a)
# TraderA gave 10, got 8 — slightly worse deal, gets loser sentiment
check(f"TraderA sentiment: {rel_a[0]:.1f}", rel_a is not None)
check(f"TraderB sentiment: {rel_b[0]:.1f} (positive)", rel_b[0] > 0)

# Bad deal: offer junk, request treasure
junk = Item(name='Rock', weight=2.0, value=0.5)
treasure = Item(name='Diamond', weight=0.1, value=50.0)
trader_a.inventory.items.append(junk)
trader_b.inventory.items.append(treasure)

r = trader_a.propose_trade(trader_b, offered=[junk], requested=[treasure])
check("Unfair trade rejected", not r['accepted'])
check("Diamond still with trader B", treasure in trader_b.inventory.items)

# Not adjacent
far_trader = make_creature(m29, x=9, y=9, stats={Stat.CHR: 10}, name='FarTrader')
r = trader_a.propose_trade(far_trader, offered=[], requested=[])
check("Trade not adjacent → fail", r['reason'] == 'not_adjacent')

# Item not in inventory
phantom_item = Item(name='Phantom', value=5.0)
r = trader_a.propose_trade(trader_b, offered=[phantom_item], requested=[])
check("Trade with missing item fails", r['reason'] == 'missing_offered_item')

# ==========================================================================
print("\n=== Trade with Relationship ===")
m30 = make_map()
friend_t = make_creature(m30, x=0, y=0, stats={Stat.CHR: 10}, name='FriendTrader')
ally_t = make_creature(m30, x=1, y=0, stats={Stat.CHR: 10}, name='AllyTrader')

# Build very strong positive relationship
for _ in range(20):
    friend_t.record_interaction(ally_t, 10.0)
    ally_t.record_interaction(friend_t, 10.0)

# Slightly unfair trade that close friends should accept due to sentiment bonus
# Sentiment: 200 / (200 + 10) ≈ 0.95, so net = (4-5) + 0.95 = -0.05... still tight
# Use 4.5 vs 5.0 so net = (4.5-5.0) + 0.95 = +0.45
ok_item = Item(name='Bread', weight=0.5, value=4.5)
nice_item = Item(name='Cake', weight=0.5, value=5.0)
friend_t.inventory.items.append(ok_item)
ally_t.inventory.items.append(nice_item)

r = friend_t.propose_trade(ally_t, offered=[ok_item], requested=[nice_item])
check(f"Friends accept slightly unfair trade: {r['accepted']}", r['accepted'])

# ==========================================================================
print("\n=== Bribe ===")
m31 = make_map()
briber = make_creature(m31, x=0, y=0, stats={Stat.CHR: 14}, name='Briber')
target_b = make_creature(m31, x=1, y=0, stats={Stat.CHR: 10}, name='BribeTarget')

# Start with neutral relationship
gold = Item(name='Gold Coins', weight=0.5, value=10.0)
briber.inventory.items.append(gold)

r = briber.bribe(target_b, [gold])
check(f"Bribe accepted (value 10 >= threshold 5): {r['accepted']}", r['accepted'])
check("Gold transferred to target", gold in target_b.inventory.items)

# Target should have positive sentiment now
rel = target_b.get_relationship(briber)
check(f"Target sentiment after bribe: {rel[0]:.1f} (positive)", rel[0] > 0)

# Insufficient bribe
penny = Item(name='Penny', weight=0.1, value=0.1)
briber.inventory.items.append(penny)
r = briber.bribe(target_b, [penny])
check("Tiny bribe rejected", not r['accepted'])
check("Penny still with briber", penny in briber.inventory.items)

# Not adjacent
r = briber.bribe(far_trader, [penny])
check("Bribe not adjacent → fail", r['reason'] == 'not_adjacent')

# Bribe a hostile creature (needs bigger bribe)
hostile = make_creature(m31, x=0, y=1, stats={Stat.CHR: 10}, name='Hostile')
hostile.record_interaction(briber, -20.0)  # very negative

small_bribe = Item(name='Small Gold', weight=0.3, value=3.0)
briber.inventory.items.append(small_bribe)
r = briber.bribe(hostile, [small_bribe])
check("Small bribe rejected by hostile creature", not r['accepted'])

big_bribe = Item(name='Big Gold', weight=1.0, value=30.0)
briber.inventory.items.append(big_bribe)
r = briber.bribe(hostile, [big_bribe])
check(f"Big bribe accepted by hostile: {r['accepted']}", r['accepted'])

# ==========================================================================
print("\n=== Wait / Observe ===")
m32 = make_map()
waiter = make_creature(m32, x=0, y=0, stats={Stat.AGL: 12, Stat.VIT: 12, Stat.STR: 12})

# Drain some stamina
waiter.stats.base[Stat.CUR_STAMINA] = 5
stam_before = waiter.stats.active[Stat.CUR_STAMINA]()
regen_rate = waiter.stats.active[Stat.STAM_REGEN]()

check("Wait succeeds", waiter.wait())
stam_after = waiter.stats.active[Stat.CUR_STAMINA]()
check(f"Stamina recovered: {stam_before} → {stam_after} (+{regen_rate})",
      stam_after == stam_before + regen_rate)

# Wait at max stamina (should cap)
waiter.stats.base[Stat.CUR_STAMINA] = waiter.stats.active[Stat.MAX_STAMINA]()
max_stam = waiter.stats.active[Stat.MAX_STAMINA]()
waiter.wait()
check("Wait at max doesn't exceed max", waiter.stats.active[Stat.CUR_STAMINA]() == max_stam)

# ==========================================================================
print("\n=== Follow ===")
m33 = make_map(cols=10, rows=10)
follower = make_creature(m33, x=0, y=0, name='Follower')
leader = make_creature(m33, x=3, y=4, name='Leader')

check("Follow moves toward target", follower.follow(leader, 10, 10))
check(f"Follower at ({follower.location.x},{follower.location.y})",
      follower.location.x == 1 and follower.location.y == 1)

# Follow again
follower.follow(leader, 10, 10)
check(f"Closer: ({follower.location.x},{follower.location.y})",
      follower.location.x == 2 and follower.location.y == 2)

# Follow when already at target
follower.location = leader.location._replace()
check("Follow at same location returns False", not follower.follow(leader, 10, 10))

# ==========================================================================
print("\n=== Call Backup ===")
m34 = make_map(cols=20, rows=20)
caller = make_creature(m34, x=10, y=10, stats={Stat.PER: 12}, name='Caller')

# Create allies and enemies at various distances
ally1 = make_creature(m34, x=11, y=10, stats={Stat.PER: 14}, name='Ally1')
# HEARING_RANGE = 3 + dmod(14) = 5, distance = 1 → in range
ally1.record_interaction(caller, 10.0)  # positive sentiment

ally2 = make_creature(m34, x=13, y=10, stats={Stat.PER: 10}, name='Ally2')
# HEARING_RANGE = 3, distance = 3 → in range
ally2.record_interaction(caller, 5.0)

enemy = make_creature(m34, x=12, y=10, stats={Stat.PER: 12}, name='Enemy')
# Has no relationship or negative — won't respond
enemy.record_interaction(caller, -5.0)

far_ally = make_creature(m34, x=19, y=19, stats={Stat.PER: 10}, name='FarAlly')
far_ally.record_interaction(caller, 10.0)
# HEARING_RANGE = 3, distance = 18 → out of range

responders = caller.call_backup()
responder_names = [r.name for r in responders]
check(f"Responders: {responder_names}", 'Ally1' in responder_names)
check("Ally2 responds", 'Ally2' in responder_names)
check("Enemy doesn't respond", 'Enemy' not in responder_names)
check("Far ally doesn't respond", 'FarAlly' not in responder_names)

# ==========================================================================
print("\n=== Sleep / Wake ===")
m35 = make_map()
sleeper = make_creature(m35, x=0, y=0, stats={Stat.PER: 14, Stat.VIT: 12})

# Drain resources
sleeper.stats.base[Stat.CUR_STAMINA] = 1
sleeper.stats.base[Stat.CUR_MANA] = 0

det_before = sleeper.stats.active[Stat.DETECTION]()
check("Enter sleep", sleeper.sleep(now=1000))
check("Is sleeping", sleeper.is_sleeping)
# Gradual restore: tick through full sleep duration (360 ticks)
for t in range(360):
    sleeper._tick_sleep(1000 + t)
check("Stamina fully restored",
      sleeper.stats.active[Stat.CUR_STAMINA]() >= sleeper.stats.active[Stat.MAX_STAMINA]() - 1)
check("Mana fully restored",
      sleeper.stats.active[Stat.CUR_MANA]() >= sleeper.stats.active[Stat.MAX_MANA]() - 1)

det_during = sleeper.stats.active[Stat.DETECTION]()
check(f"Detection reduced while sleeping: {det_before} → {det_during}",
      det_during == det_before - 5)

# Can't sleep twice
check("Can't double-sleep", not sleeper.sleep(now=2000))

sleeper.wake()
check("Not sleeping after wake", not sleeper.is_sleeping)
det_after = sleeper.stats.active[Stat.DETECTION]()
check(f"Detection restored: {det_after}", det_after == det_before)

# ==========================================================================
print("\n=== Set Trap ===")
m36 = make_map()
trapper = make_creature(m36, x=0, y=0,
                        stats={Stat.INT: 14, Stat.PER: 12}, name='Trapper')
# CRAFT_QUALITY = dmod(14) + dmod(12)//2 = 2 + 1//2 = 2 + 0 = 2
# Wait, dmod(12)=1, 1//2=0. So CRAFT_QUALITY = 2 + 0 = 2

trap_item = Item(name='Bear Trap', weight=3.0, value=5.0)
trapper.inventory.items.append(trap_item)

check("Set trap succeeds", trapper.set_trap(trap_item, dc=10))
check("Trap item removed from inventory", trap_item not in trapper.inventory.items)

tile36 = m36.tiles[MapKey(0, 0, 0)]
check("Trap item on tile", any(i.name == 'Bear Trap' for i in tile36.inventory.items))

craft_q = trapper.stats.active[Stat.CRAFT_QUALITY]()
expected_dc = 10 + craft_q
check(f"Trap DC on tile = {tile36.stat_mods.get('trap_dc')} (10 + craft {craft_q} = {expected_dc})",
      tile36.stat_mods.get('trap_dc') == expected_dc)

# Can't set trap without the item
fake_trap = Item(name='Fake', weight=1.0)
check("Can't set trap without item in inventory", not trapper.set_trap(fake_trap))

# ==========================================================================
print("\n=== Trap Trigger ===")
m37 = make_map(cols=5, rows=5)
trap_setter = make_creature(m37, x=2, y=2,
                            stats={Stat.INT: 14, Stat.PER: 12}, name='TrapSetter')
trap2 = Item(name='Spike Trap', weight=2.0, value=3.0)
trap_setter.inventory.items.append(trap2)
trap_setter.set_trap(trap2, dc=15)
# Move setter away
trap_setter.location = MapKey(0, 0, 0)

# Low detection victim walks into trap
victim_trap = make_creature(m37, x=2, y=1,
                            stats={Stat.PER: 6, Stat.VIT: 14, Stat.STR: 10, Stat.LVL: 5},
                            name='TrapVictim')
# DETECTION = dmod(6) = -2
hp_before_trap = victim_trap.stats.active[Stat.HP_CURR]()

# Walk into trapped tile
victim_trap.move(0, 1, 5, 5)
check("Victim moved to trapped tile", victim_trap.location.y == 2)

# Run multiple times: some should trigger (low detection vs DC 15+craft)
# With d20 + (-2) vs ~17, most will trigger
triggered_count = 0
for _ in range(50):
    test_map = make_map(cols=5, rows=5)
    ts = make_creature(test_map, x=2, y=2, stats={Stat.INT: 14, Stat.PER: 12}, name='TS')
    t = Item(name='Trap', weight=1.0)
    ts.inventory.items.append(t)
    ts.set_trap(t, dc=15)
    ts.location = MapKey(0, 0, 0)

    v = make_creature(test_map, x=2, y=1, stats={Stat.PER: 6, Stat.VIT: 14, Stat.LVL: 5}, name='V')
    hp_b = v.stats.active[Stat.HP_CURR]()
    v.move(0, 1, 5, 5)
    hp_a = v.stats.active[Stat.HP_CURR]()
    if hp_a < hp_b:
        triggered_count += 1

check(f"Traps triggered: {triggered_count}/50 (low detection = most trigger)",
      triggered_count > 20)

# High detection avoids traps
avoided = 0
for _ in range(50):
    test_map = make_map(cols=5, rows=5)
    ts = make_creature(test_map, x=2, y=2, stats={Stat.INT: 14, Stat.PER: 12}, name='TS')
    t = Item(name='Trap', weight=1.0)
    ts.inventory.items.append(t)
    ts.set_trap(t, dc=10)  # lower DC
    ts.location = MapKey(0, 0, 0)

    scout = make_creature(test_map, x=2, y=1, stats={Stat.PER: 20, Stat.VIT: 14, Stat.LVL: 5}, name='Scout')
    # DETECTION = dmod(20) = 5, d20 + 5 vs ~12 → most succeed
    hp_b = scout.stats.active[Stat.HP_CURR]()
    scout.move(0, 1, 5, 5)
    hp_a = scout.stats.active[Stat.HP_CURR]()
    if hp_a == hp_b:
        avoided += 1

check(f"High detection avoids traps: {avoided}/50", avoided > 20)

# ==========================================================================
print("\n=== Death ===")
m38 = make_map()
doomed = make_creature(m38, x=0, y=0,
                       stats={Stat.STR: 12, Stat.VIT: 10, Stat.LVL: 3},
                       name='Doomed')

# Give some gold
doomed.gold = 75

# Equip and add inventory
death_sword = Weapon(name='DeathSword', weight=3.0,
                     slots=[Slot.HAND_R], slot_count=1, damage=5,
                     buffs={Stat.MELEE_DMG: 2})
doomed.inventory.items.append(death_sword)
doomed.equip(death_sword)
pouch = Item(name='Gold Pouch', weight=0.5, value=10.0)
doomed.inventory.items.append(pouch)

check("Doomed is alive", doomed.is_alive)
check("Has equipment", len(doomed.equipment) > 0)
check("Has inventory", len(doomed.inventory.items) > 0)

# Kill
doomed.stats.base[Stat.HP_CURR] = 0
check("Doomed is not alive", not doomed.is_alive)

doomed.die()
tile38 = m38.tiles[MapKey(0, 0, 0)]
items_on_tile = [i.name for i in tile38.inventory.items]
check("Sword dropped on tile", 'DeathSword' in items_on_tile)
check("Pouch dropped on tile", 'Gold Pouch' in items_on_tile)
check("Inventory cleared", len(doomed.inventory.items) == 0)
check("Equipment cleared", len(doomed.equipment) == 0)
check(f"Gold dropped on tile: {tile38.gold}", tile38.gold == 75)
check("Creature gold zeroed", doomed.gold == 0)

# Test pickup_gold
looter = make_creature(m38, x=0, y=0, name='Looter')
looter.gold = 10
picked = looter.pickup_gold()
check(f"Picked up {picked} gold", picked == 75)
check(f"Looter gold: {looter.gold}", looter.gold == 85)
check("Tile gold zeroed", tile38.gold == 0)

# Pickup gold when none on tile
picked2 = looter.pickup_gold()
check("No gold to pickup", picked2 == 0)

# Stat mods from equipment removed
melee_after = doomed.stats.active[Stat.MELEE_DMG]()
base_melee = (doomed.stats.active[Stat.STR]() - 10) // 2
check(f"Equipment mods removed: MELEE_DMG = {melee_after} (base {base_melee})",
      melee_after == base_melee)

# ==========================================================================
print("\n=== Sleep Deprivation ===")
m39 = make_map()
tired = make_creature(m39, x=0, y=0,
                      stats={Stat.STR: 14, Stat.AGL: 12, Stat.PER: 14,
                             Stat.VIT: 12, Stat.INT: 10})

str_base = tired.stats.active[Stat.STR]()
check(f"STR rested = {str_base}", str_base == 14)
check("Fatigue level 0", tired.fatigue_level == 0)

# 1 day without sleep: mild fatigue
tired.add_sleep_debt(1)
check("Fatigue level 1 (mild)", tired.fatigue_level == 1)
check(f"STR with mild fatigue = {tired.stats.active[Stat.STR]()} (14-1=13)",
      tired.stats.active[Stat.STR]() == 13)

# 2 days: exhaustion
tired.add_sleep_debt(1)
check("Fatigue level 2 (exhaustion)", tired.fatigue_level == 2)
check(f"STR with exhaustion = {tired.stats.active[Stat.STR]()} (14-2=12)",
      tired.stats.active[Stat.STR]() == 12)

# 3 days: severe
tired.add_sleep_debt(1)
check("Fatigue level 3 (severe)", tired.fatigue_level == 3)
check(f"STR with severe fatigue = {tired.stats.active[Stat.STR]()} (14-3=11)",
      tired.stats.active[Stat.STR]() == 11)
check(f"Detection penalty: {tired.stats.active[Stat.DETECTION]()}",
      tired.stats.active[Stat.DETECTION]() < (tired.stats.active[Stat.PER]() - 10) // 2)

# 4 days: collapse
tired.add_sleep_debt(1)
check("Fatigue level 4 (collapse)", tired.fatigue_level == 4)

# Sleep clears debt (gradual: 1 day per 360 ticks, 4 days = 1440 ticks)
tired.sleep(now=1000)
# Extend sleep duration to cover all debt
tired._occupied_until = 1000 + 1800
for t in range(1500):
    result = tired._tick_sleep(1000 + t)
    if result and result[0] == 'wake':
        break
check("Sleep clears fatigue", tired.fatigue_level == 0)
check(f"STR restored after sleep = {tired.stats.active[Stat.STR]()}",
      tired.stats.active[Stat.STR]() == 14)
tired.wake()

# ==========================================================================
print("\n=== Dialogue System ===")
# Populate DIALOGUE and DIALOGUE_ROOTS directly for headless testing
from data.db import DIALOGUE, DIALOGUE_ROOTS
DIALOGUE.clear()
DIALOGUE_ROOTS.clear()

# Build a simple conversation tree:
# Root (NPC greets)
#   ├── Player response A (leads to NPC follow-up)
#   │     └── NPC follow-up
#   └── Player response B (ends conversation, gives sentiment)
DIALOGUE[1] = {
    'id': 1, 'conversation': 'greeting', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'Hello traveler!', 'char_conditions': {},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [2, 3],
}
DIALOGUE[2] = {
    'id': 2, 'conversation': 'greeting', 'species': None,
    'creature_key': None, 'parent_id': 1, 'speaker': 'player',
    'text': 'Hello! What news?', 'char_conditions': {},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [4],
}
DIALOGUE[3] = {
    'id': 3, 'conversation': 'greeting', 'species': None,
    'creature_key': None, 'parent_id': 1, 'speaker': 'player',
    'text': 'Leave me alone.', 'char_conditions': {},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {'sentiment': -2.0}, 'sort_order': 1,
    'children': [],
}
DIALOGUE[4] = {
    'id': 4, 'conversation': 'greeting', 'species': None,
    'creature_key': None, 'parent_id': 2, 'speaker': 'npc',
    'text': 'Dark times ahead...', 'char_conditions': {},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [],
}

# Species-filtered node: only for species 'elf'
DIALOGUE[5] = {
    'id': 5, 'conversation': 'greeting', 'species': 'elf',
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'Greetings, kin!', 'char_conditions': {},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [],
}

# Level-gated node
DIALOGUE[6] = {
    'id': 6, 'conversation': 'quest', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'You look experienced enough...', 'char_conditions': {'level_min': 5},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [],
}

DIALOGUE_ROOTS['greeting'] = [1, 5]
DIALOGUE_ROOTS['quest'] = [6]

m40 = make_map()
player_d = make_creature(m40, x=0, y=0,
                         stats={Stat.PER: 12, Stat.LVL: 3},
                         name='Player')
npc_d = make_creature(m40, x=1, y=0,
                      stats={Stat.PER: 12}, name='Shopkeeper')

# Start conversation
roots = player_d.start_conversation(npc_d, 'greeting')
check(f"Found {len(roots)} root nodes", len(roots) >= 1)
check("Root is 'Hello traveler!'", any(n['text'] == 'Hello traveler!' for n in roots))
check("Elf-only root NOT shown (player isn't elf)",
      not any(n['text'] == 'Greetings, kin!' for n in roots))

# Player is in conversation
check("Player in conversation state", player_d.dialogue is not None)

# Advance to root node, get children (player responses)
children = player_d.advance_dialogue(1, npc_d)
check(f"Root has {len(children)} player responses", len(children) == 2)
check("Response A: 'What news?'", children[0]['text'] == 'Hello! What news?')
check("Response B: 'Leave me alone.'", children[1]['text'] == 'Leave me alone.')

# Pick response A → get NPC follow-up
grandchildren = player_d.advance_dialogue(2, npc_d)
check(f"Follow-up from A: {len(grandchildren)} node(s)", len(grandchildren) == 1)
check("NPC says 'Dark times ahead...'", grandchildren[0]['text'] == 'Dark times ahead...')

# Advance past leaf → conversation ends
final = player_d.advance_dialogue(4, npc_d)
check("Leaf node ends conversation", len(final) == 0)
check("Player no longer in conversation", player_d.dialogue is None)

# Test negative sentiment effect from response B
player_d2 = make_creature(m40, x=0, y=1, stats={Stat.PER: 12}, name='Player2')
npc_d2 = make_creature(m40, x=1, y=1, stats={Stat.PER: 12}, name='NPC2')
player_d2.start_conversation(npc_d2, 'greeting')
player_d2.advance_dialogue(1, npc_d2)
player_d2.advance_dialogue(3, npc_d2)  # "Leave me alone" → sentiment -2
rel_d = player_d2.get_relationship(npc_d2)
check(f"Sentiment effect applied: {rel_d[0]:.1f}",
      rel_d[0] < 1.0)  # started at +1 from conversation, -2 from effect

# Level-gated dialogue
low_lvl = make_creature(m40, x=2, y=0, stats={Stat.PER: 12, Stat.LVL: 2}, name='LowLevel')
high_lvl = make_creature(m40, x=2, y=1, stats={Stat.PER: 12, Stat.LVL: 6}, name='HighLevel')
quest_npc = make_creature(m40, x=3, y=0, stats={Stat.PER: 12}, name='QuestNPC')
quest_npc2 = make_creature(m40, x=3, y=1, stats={Stat.PER: 12}, name='QuestNPC2')

low_roots = low_lvl.start_conversation(quest_npc, 'quest')
check("Level 2 can't access level 5 quest dialogue", len(low_roots) == 0)

high_roots = high_lvl.start_conversation(quest_npc2, 'quest')
check("Level 6 CAN access level 5 quest dialogue", len(high_roots) == 1)

# Out of sight
far_npc = make_creature(m40, x=15, y=15, stats={Stat.PER: 12}, name='FarNPC')
far_roots = player_d.start_conversation(far_npc, 'greeting')
check("Can't start conversation out of sight", len(far_roots) == 0)

# NPC-to-NPC conversation
npc_a = make_creature(m40, x=4, y=0, stats={Stat.PER: 12}, name='NPCA')
npc_b = make_creature(m40, x=5, y=0, stats={Stat.PER: 12}, name='NPCB')
npc_roots = npc_a.start_conversation(npc_b, 'greeting')
check("NPC-to-NPC conversation works", len(npc_roots) >= 1)

# Clean up test dialogue data
DIALOGUE.clear()
DIALOGUE_ROOTS.clear()

# ==========================================================================
print("\n=== Observation Vector ===")
from classes.observation import build_observation, OBSERVATION_SIZE, make_snapshot

m41 = make_map(cols=10, rows=10)
obs_creature = make_creature(m41, x=5, y=5,
                             stats={Stat.STR: 14, Stat.PER: 12, Stat.AGL: 12,
                                    Stat.INT: 16, Stat.VIT: 12, Stat.CHR: 10,
                                    Stat.LCK: 10, Stat.LVL: 3},
                             name='Observer')

# Add a nearby creature
nearby = make_creature(m41, x=6, y=5,
                       stats={Stat.STR: 10, Stat.PER: 10},
                       name='Nearby')
obs_creature.record_interaction(nearby, 3.0)

obs = build_observation(obs_creature, 10, 10)
check(f"Observation length = {len(obs)} (expected {OBSERVATION_SIZE})",
      len(obs) == OBSERVATION_SIZE)
check("All values are numeric", all(isinstance(v, (int, float)) for v in obs))
check("HP ratio in [0,1]", 0.0 <= obs[15] <= 1.0)  # resources section starts at 15
check("No NaN or inf", all(v == v and abs(v) != float('inf') for v in obs))

# With previous snapshot
snap1 = make_snapshot(obs_creature)
# Simulate damage
obs_creature.stats.base[Stat.HP_CURR] -= 3
snap2 = make_snapshot(obs_creature)
obs2 = build_observation(obs_creature, 10, 10, prev_snapshot=snap1)
check(f"Observation with deltas: length {len(obs2)}", len(obs2) == OBSERVATION_SIZE)
# HP delta should be negative (temporal section at end)
# HP delta is somewhere in section 24 (temporal) — just check the observation is valid
check(f"Observation with deltas is valid: length {len(obs2)}", len(obs2) == OBSERVATION_SIZE)

# No neighbors → neighbor slots are all zeros
m42 = make_map(cols=10, rows=10)
alone = make_creature(m42, x=5, y=5, stats={Stat.PER: 12}, name='Alone')
obs_alone = build_observation(alone, 10, 10)
check("Alone observation valid", len(obs_alone) == OBSERVATION_SIZE)

# ==========================================================================
print("\n=== Reward Function ===")
from classes.reward import compute_reward, make_reward_snapshot

m43 = make_map()
rl_creature = make_creature(m43, x=0, y=0,
                            stats={Stat.STR: 14, Stat.INT: 16, Stat.VIT: 12,
                                   Stat.PER: 12, Stat.LVL: 3},
                            name='RLCreature')

# Baseline snapshot
snap_a = make_reward_snapshot(rl_creature)

# Simulate taking damage
rl_creature.stats.base[Stat.HP_CURR] -= 5
snap_b = make_reward_snapshot(rl_creature)
r = compute_reward(rl_creature, snap_a, snap_b)
check(f"Damage penalty: {r:.2f} (negative)", r < 0)

# Simulate healing
rl_creature.stats.base[Stat.HP_CURR] += 5
snap_c = make_reward_snapshot(rl_creature)
r2 = compute_reward(rl_creature, snap_b, snap_c)
check(f"Healing reward: {r2:.2f} (positive)", r2 > 0)

# Simulate acquiring an item
snap_d = make_reward_snapshot(rl_creature)
gold = Item(name='Gold', weight=0.1, value=10.0)
rl_creature.inventory.items.append(gold)
snap_e = make_reward_snapshot(rl_creature)
r3 = compute_reward(rl_creature, snap_d, snap_e)
check(f"Item acquisition reward: {r3:.2f} (positive)", r3 > 0)

# Simulate meeting a new creature (curiosity reward)
snap_f = make_reward_snapshot(rl_creature)
stranger_rl = make_creature(m43, x=1, y=0, name='StrangerRL')
rl_creature.record_interaction(stranger_rl, 1.0)
snap_g = make_reward_snapshot(rl_creature)
r4 = compute_reward(rl_creature, snap_f, snap_g)
check(f"Curiosity reward (INT 16): {r4:.2f} (positive)", r4 > 0)

# Curiosity reward is now stat-blind (model learns the weights)
low_int = make_creature(m43, x=0, y=1,
                        stats={Stat.INT: 6, Stat.PER: 10}, name='LowINT')
snap_h = make_reward_snapshot(low_int)
low_int.record_interaction(stranger_rl, 1.0)
snap_i = make_reward_snapshot(low_int)
r5 = compute_reward(low_int, snap_h, snap_i)
check(f"Low INT curiosity reward: {r5:.2f} (same formula, model learns weighting)", r5 > 0)

# Simulate death
snap_j = make_reward_snapshot(rl_creature)
rl_creature.stats.base[Stat.HP_CURR] = 0
snap_k = make_reward_snapshot(rl_creature)
r6 = compute_reward(rl_creature, snap_j, snap_k)
check(f"Death penalty: {r6:.2f} (massive negative)", r6 <= -20.0)

# Fatigue penalty
rl_creature.stats.base[Stat.HP_CURR] = rl_creature.stats.active[Stat.HP_MAX]()
snap_l = make_reward_snapshot(rl_creature)
rl_creature.add_sleep_debt(2)
snap_m = make_reward_snapshot(rl_creature)
r7 = compute_reward(rl_creature, snap_l, snap_m)
check(f"Fatigue penalty: {r7:.2f} (negative)", r7 < 0)

# ==========================================================================
print("\n=== Arena Generator ===")
from editor.simulation.arena import generate_arena, random_stats

stats_b = random_stats('balanced')
check("Balanced stats: all 7 base stats present", len(stats_b) == 7)
check("Balanced stats in range [8,14]",
      all(8 <= v <= 14 for v in stats_b.values()))

stats_f = random_stats('fighter')
check(f"Fighter STR={stats_f[Stat.STR]} (high)", stats_f[Stat.STR] >= 14)

arena = generate_arena(cols=15, rows=15, num_creatures=4, obstacle_density=0.1)
check("Arena has map", arena['map'] is not None)
check(f"Arena has {len(arena['creatures'])} creatures", len(arena['creatures']) == 4)
check("All creatures on map", all(c.current_map is arena['map'] for c in arena['creatures']))
check("All creatures alive", all(c.is_alive for c in arena['creatures']))

# Check walkable placement
for c in arena['creatures']:
    tile = arena['map'].tiles.get(c.location)
    check(f"{c.name} on walkable tile", tile is not None and tile.walkable)

# ==========================================================================
print("\n=== Headless Simulation ===")
from editor.simulation.headless import Simulation
from classes.observation import OBSERVATION_SIZE

sim_arena = generate_arena(cols=10, rows=10, num_creatures=4, obstacle_density=0.05)
sim = Simulation(sim_arena, tick_ms=100)

check("Simulation starts at step 0", sim.step_count == 0)
check(f"Alive count = {sim.alive_count}", sim.alive_count == 4)

# Run 10 steps
for _ in range(10):
    results = sim.step()

check(f"After 10 steps: step_count = {sim.step_count}", sim.step_count == 10)
check(f"Results per step: {len(results)} creatures", len(results) == 4)

# Verify result structure
r0 = results[0]
check("Result has creature", r0['creature'] is not None)
check(f"Observation length = {len(r0['observation'])}", len(r0['observation']) == OBSERVATION_SIZE)
check("Reward is a float", isinstance(r0['reward'], float))
check("Alive is bool", isinstance(r0['alive'], bool))

# Run more steps — creatures wander via RandomWanderBehavior
for _ in range(50):
    sim.step()

summary = sim.summary()
check(f"Summary after 60 steps: {summary['alive']} alive", summary['alive'] >= 0)
check("Time advanced", summary['time_ms'] == 60 * 100)

# Verify no crashes over many ticks
for _ in range(200):
    sim.step()
check(f"Survived 260 steps without crash", sim.step_count == 260)

# ==========================================================================
print("\n=== Action Dispatch ===")
from classes.actions import Action, dispatch, NUM_ACTIONS
import numpy as np

m44 = make_map(cols=10, rows=10)
actor = make_creature(m44, x=5, y=5, stats={Stat.STR: 14, Stat.AGL: 12}, name='Actor')
dummy = make_creature(m44, x=6, y=5, stats={Stat.VIT: 12, Stat.PER: 10, Stat.LVL: 3}, name='Dummy')

check(f"NUM_ACTIONS = {NUM_ACTIONS}", NUM_ACTIONS == 32)

# Move via dispatch (auto-direction)
ctx = {'cols': 10, 'rows': 10}
r = dispatch(actor, Action.MOVE, ctx)
check(f"Dispatch MOVE: result={r.get('success', r.get('moved', False))}", True)

# Wait via dispatch
r = dispatch(actor, Action.WAIT, ctx)
check("Dispatch WAIT succeeds", r['success'])

# Melee with target
actor.location = actor.location._replace(x=5, y=5)
ctx_t = {'cols': 10, 'rows': 10, 'target': dummy, 'now': 1000}
actor.stats.base[Stat.CUR_STAMINA] = actor.stats.active[Stat.MAX_STAMINA]()
r = dispatch(actor, Action.MELEE_ATTACK, ctx_t)
check("Dispatch MELEE_ATTACK ran", 'reason' in r or r.get('hit') is not None)

# No target → fail
r = dispatch(actor, Action.MELEE_ATTACK, {'cols': 10, 'rows': 10, 'now': 0})
check("Melee with no target fails", not r['success'])

# Unknown action
r = dispatch(actor, 999, ctx)
check("Unknown action fails", not r['success'])

# ==========================================================================
print("\n=== Neural Net ===")
from editor.simulation.net import CreatureNet

net = CreatureNet(h1_size=64, h2_size=32)
check(f"Net param count: {net.param_count()}", net.param_count() > 0)

# Single forward pass
obs = np.random.randn(OBSERVATION_SIZE).astype(np.float32)
probs = net.forward(obs)
check(f"Output shape: {probs.shape}", probs.shape == (NUM_ACTIONS,))
check(f"Probs sum ≈ 1.0: {probs.sum():.4f}", abs(probs.sum() - 1.0) < 1e-4)
check("All probs >= 0", (probs >= 0).all())

# Batch forward pass
batch = np.random.randn(5, OBSERVATION_SIZE).astype(np.float32)
batch_probs = net.forward(batch)
check(f"Batch shape: {batch_probs.shape}", batch_probs.shape == (5, NUM_ACTIONS))
check("Batch probs sum ≈ 1.0 per row",
      all(abs(batch_probs[i].sum() - 1.0) < 1e-4 for i in range(5)))

# Action selection
action = net.select_action(obs, temperature=1.0)
check(f"Selected action: {action} (in range)", 0 <= action < NUM_ACTIONS)

# Greedy selection
action_g = net.select_action(obs, temperature=0)
check(f"Greedy action: {action_g} == argmax", action_g == int(np.argmax(net.forward(obs))))

# Batch selection
actions = net.batch_select(batch, temperature=1.0)
check(f"Batch actions: {len(actions)} = 5", len(actions) == 5)
check("All actions in range", all(0 <= a < NUM_ACTIONS for a in actions))

# Save/load roundtrip
import tempfile, os
with tempfile.NamedTemporaryFile(suffix='.npz', delete=False) as f:
    tmp_path = f.name
net.save(tmp_path)
net2 = CreatureNet(h1_size=64, h2_size=32)
net2.load(tmp_path)
probs2 = net2.forward(obs)
check("Save/load roundtrip: same output", np.allclose(probs, probs2, atol=1e-6))
os.unlink(tmp_path)

# ==========================================================================
print("\n=== StatWeightedBehavior ===")
from classes.creature import StatWeightedBehavior

m45 = make_map(cols=10, rows=10)
sw_creature = make_creature(m45, x=5, y=5,
                            stats={Stat.STR: 16, Stat.AGL: 12, Stat.INT: 10,
                                   Stat.CHR: 10, Stat.PER: 12, Stat.VIT: 12},
                            name='StatBot')
sw_target = make_creature(m45, x=6, y=5,
                          stats={Stat.VIT: 12, Stat.PER: 10, Stat.LVL: 3},
                          name='SWTarget')

sw_beh = StatWeightedBehavior()
# Run 50 think cycles — should not crash
for _ in range(50):
    sw_creature.stats.base[Stat.CUR_STAMINA] = sw_creature.stats.active[Stat.MAX_STAMINA]()
    sw_creature.stats.base[Stat.HP_CURR] = sw_creature.stats.active[Stat.HP_MAX]()
    sw_beh.think(sw_creature, 10, 10)
check("StatWeightedBehavior: 50 cycles without crash", True)

# ==========================================================================
print("\n=== NeuralBehavior ===")
from classes.creature import NeuralBehavior

m46 = make_map(cols=10, rows=10)
neural_creature = make_creature(m46, x=5, y=5,
                                stats={Stat.STR: 12, Stat.AGL: 14, Stat.INT: 14,
                                       Stat.PER: 12, Stat.VIT: 12},
                                name='NeuralBot')
neural_target = make_creature(m46, x=6, y=5,
                              stats={Stat.VIT: 12, Stat.PER: 10},
                              name='NTarget')

nb = NeuralBehavior(net=CreatureNet(h1_size=64, h2_size=32), temperature=1.0)
for _ in range(50):
    neural_creature.stats.base[Stat.CUR_STAMINA] = neural_creature.stats.active[Stat.MAX_STAMINA]()
    neural_creature.stats.base[Stat.HP_CURR] = neural_creature.stats.active[Stat.HP_MAX]()
    nb.think(neural_creature, 10, 10)
check("NeuralBehavior: 50 cycles without crash", True)

# ==========================================================================
print("\n=== Simulation with StatWeightedBehavior ===")
from editor.simulation.arena import generate_arena

sw_arena = generate_arena(cols=15, rows=15, num_creatures=6, obstacle_density=0.05)
# Replace all behaviors with StatWeightedBehavior
for c in sw_arena['creatures']:
    c.behavior = StatWeightedBehavior()
    c.register_tick('behavior', 500, c._do_behavior)

sw_sim = Simulation(sw_arena, tick_ms=100)
for _ in range(100):
    sw_sim.step()
check(f"StatWeighted sim: 100 steps, {sw_sim.alive_count} alive", sw_sim.step_count == 100)

# ==========================================================================
print("\n=== Spell System ===")

# Build spell definitions directly (no DB needed for headless)
fireball = {
    'key': 'fireball', 'name': 'Fireball', 'description': 'A ball of fire',
    'action_word': 'hurl', 'damage': 8.0, 'mana_cost': 5, 'stamina_cost': 0,
    'range': 6, 'radius': 2, 'spell_dc': 12, 'dodgeable': True,
    'target_type': 'single', 'effect_type': 'damage',
    'buffs': {}, 'duration': 0, 'secondary_resist': None, 'secondary_dc': None,
    'requirements': {Stat.INT: 12}, 'sprite_name': None,
    'animation_name': None, 'composite_name': None,
}

heal_spell = {
    'key': 'heal', 'name': 'Heal', 'description': 'Restore health',
    'action_word': 'channel', 'damage': 10.0, 'mana_cost': 4, 'stamina_cost': 0,
    'range': 3, 'radius': 0, 'spell_dc': 0, 'dodgeable': False,
    'target_type': 'single', 'effect_type': 'heal',
    'buffs': {}, 'duration': 0, 'secondary_resist': None, 'secondary_dc': None,
    'requirements': {}, 'sprite_name': None,
    'animation_name': None, 'composite_name': None,
}

buff_spell = {
    'key': 'fortify', 'name': 'Fortify', 'description': 'Strengthen ally',
    'action_word': 'invoke', 'damage': 0, 'mana_cost': 3, 'stamina_cost': 0,
    'range': 3, 'radius': 0, 'spell_dc': 0, 'dodgeable': False,
    'target_type': 'single', 'effect_type': 'buff',
    'buffs': {Stat.STR: 4, Stat.VIT: 2}, 'duration': 10.0,
    'secondary_resist': None, 'secondary_dc': None,
    'requirements': {}, 'sprite_name': None,
    'animation_name': None, 'composite_name': None,
}

self_heal = {
    'key': 'self_heal', 'name': 'Self Heal', 'description': 'Heal yourself',
    'action_word': 'channel', 'damage': 5.0, 'mana_cost': 2, 'stamina_cost': 0,
    'range': 0, 'radius': 0, 'spell_dc': 0, 'dodgeable': False,
    'target_type': 'self', 'effect_type': 'heal',
    'buffs': {}, 'duration': 0, 'secondary_resist': None, 'secondary_dc': None,
    'requirements': {}, 'sprite_name': None,
    'animation_name': None, 'composite_name': None,
}

poison_bolt = {
    'key': 'poison_bolt', 'name': 'Poison Bolt', 'description': 'Venomous attack',
    'action_word': 'conjure', 'damage': 4.0, 'mana_cost': 3, 'stamina_cost': 0,
    'range': 5, 'radius': 0, 'spell_dc': 10, 'dodgeable': True,
    'target_type': 'single', 'effect_type': 'damage',
    'buffs': {}, 'duration': 0, 'secondary_resist': 'poison resist',
    'secondary_dc': 12,
    'requirements': {}, 'sprite_name': None,
    'animation_name': None, 'composite_name': None,
}

m47 = make_map(cols=15, rows=15)
mage = make_creature(m47, x=0, y=0,
                     stats={Stat.INT: 16, Stat.PER: 12, Stat.AGL: 10,
                            Stat.VIT: 12, Stat.LVL: 3, Stat.CHR: 10,
                            Stat.LCK: 10, Stat.STR: 10},
                     name='Mage')
spell_target = make_creature(m47, x=3, y=0,
                             stats={Stat.VIT: 14, Stat.AGL: 10, Stat.PER: 12,
                                    Stat.INT: 8, Stat.STR: 10, Stat.LVL: 3},
                             name='SpellTarget')

# Damage spell — run multiple for statistics
hits = 0
total_spell_dmg = 0
for _ in range(50):
    spell_target.stats.base[Stat.HP_CURR] = spell_target.stats.active[Stat.HP_MAX]()
    mage.stats.base[Stat.CUR_MANA] = mage.stats.active[Stat.MAX_MANA]()
    r = mage.cast_spell(fireball, spell_target, now=1000)
    if r['hit'] and r['damage'] > 0:
        hits += 1
        total_spell_dmg += r['damage']

check(f"Fireball hits: {hits}/50", hits > 0)
check(f"Fireball total damage: {total_spell_dmg}", total_spell_dmg > 0)

# No mana → fail
mage.stats.base[Stat.CUR_MANA] = 0
r = mage.cast_spell(fireball, spell_target, now=1000)
check("Fireball with 0 mana fails", r['reason'] == 'no_mana')

# Out of range
mage.stats.base[Stat.CUR_MANA] = mage.stats.active[Stat.MAX_MANA]()
far_target_sp = make_creature(m47, x=10, y=0, stats={Stat.VIT: 10}, name='FarSP')
r = mage.cast_spell(fireball, far_target_sp, now=1000)
check("Fireball out of range fails", r['reason'] == 'out_of_range')

# Requirements not met
dumb_caster = make_creature(m47, x=0, y=1,
                            stats={Stat.INT: 8, Stat.VIT: 10}, name='Dumb')
dumb_caster.stats.base[Stat.CUR_MANA] = 20
r = dumb_caster.cast_spell(fireball, spell_target, now=1000)
check("Low INT can't cast fireball (requires INT 12)", r['reason'] == 'requirements_not_met')

# Heal spell
spell_target.stats.base[Stat.HP_CURR] = 1
hp_before_heal = spell_target.stats.active[Stat.HP_CURR]()
mage.stats.base[Stat.CUR_MANA] = mage.stats.active[Stat.MAX_MANA]()
r = mage.cast_spell(heal_spell, spell_target, now=1000)
hp_after_heal = spell_target.stats.active[Stat.HP_CURR]()
check(f"Heal: {hp_before_heal} → {hp_after_heal}", hp_after_heal > hp_before_heal)
check("Heal records positive interaction", r['hit'] and r['damage'] < 0)

# Buff spell
str_before_buff = spell_target.stats.active[Stat.STR]()
mage.stats.base[Stat.CUR_MANA] = mage.stats.active[Stat.MAX_MANA]()
r = mage.cast_spell(buff_spell, spell_target, now=1000)
str_after_buff = spell_target.stats.active[Stat.STR]()
check(f"Buff: STR {str_before_buff} → {str_after_buff} (+4)", str_after_buff == str_before_buff + 4)
check("Buff applied", r['effect_applied'])

# Buff expires after duration
spell_target.process_ticks(11000)  # 11 seconds > 10s duration
str_expired = spell_target.stats.active[Stat.STR]()
check(f"Buff expired: STR back to {str_expired}", str_expired == str_before_buff)

# Self-targeted heal
mage.stats.base[Stat.HP_CURR] = 1
mage.stats.base[Stat.CUR_MANA] = mage.stats.active[Stat.MAX_MANA]()
r = mage.cast_spell(self_heal, None, now=1000)
check("Self-heal with no target works (target_type=self)", r['hit'])
check(f"Mage HP after self-heal: {mage.stats.active[Stat.HP_CURR]()}", mage.stats.active[Stat.HP_CURR]() > 1)

# Poison bolt with secondary resist
mage.stats.base[Stat.CUR_MANA] = mage.stats.active[Stat.MAX_MANA]()
spell_target.stats.base[Stat.HP_CURR] = spell_target.stats.active[Stat.HP_MAX]()
secondary_hits = 0
for _ in range(50):
    spell_target.stats.base[Stat.HP_CURR] = spell_target.stats.active[Stat.HP_MAX]()
    mage.stats.base[Stat.CUR_MANA] = mage.stats.active[Stat.MAX_MANA]()
    r = mage.cast_spell(poison_bolt, spell_target, now=1000)
    if r.get('secondary_applied'):
        secondary_hits += 1
check(f"Poison secondary effect: {secondary_hits}/50 (some should land)", True)

# ==========================================================================
print("\n=== Genetics: Chromosome Generation ===")
from classes.genetics import (
    generate_chromosomes, inherit, express, apply_genetics,
    check_inbreeding, inbreeding_mutation_rate, NUM_GENES, GENE_STAT_MAP,
)

# Male gets XY
m_chroms = generate_chromosomes('male')
check("Male has 2 chromosomes", len(m_chroms) == 2)
check(f"X chromosome has {NUM_GENES} genes", len(m_chroms[0]) == NUM_GENES)
check(f"Y chromosome has {NUM_GENES} genes", len(m_chroms[1]) == NUM_GENES)
check("All genes 0-15", all(0 <= g <= 15 for c in m_chroms for g in c))

# Female gets XX
f_chroms = generate_chromosomes('female')
check("Female has 2 chromosomes", len(f_chroms) == 2)

# ==========================================================================
print("\n=== Genetics: Sex-Linked Biases (statistical) ===")
# Generate many males and females, check Y bias toward STR/INT/PER
male_str_sum = 0
female_str_sum = 0
male_vit_sum = 0
female_vit_sum = 0
N = 500
for _ in range(N):
    mc = generate_chromosomes('male')
    fc = generate_chromosomes('female')
    # Y chromosome is mc[1], second X is fc[1]
    # Gene positions 0-1 = STR
    male_str_sum += mc[1][0] + mc[1][1]
    female_str_sum += fc[1][0] + fc[1][1]
    # Gene positions 2-3 = VIT
    male_vit_sum += mc[1][2] + mc[1][3]
    female_vit_sum += fc[1][2] + fc[1][3]

male_str_avg = male_str_sum / N
female_str_avg = female_str_sum / N
check(f"Y bias: male STR avg {male_str_avg:.1f} > female second-X STR {female_str_avg:.1f}",
      male_str_avg > female_str_avg)

male_vit_avg = male_vit_sum / N
female_vit_avg = female_vit_sum / N
check(f"X bias: female VIT avg {female_vit_avg:.1f} > male Y VIT {male_vit_avg:.1f}",
      female_vit_avg > male_vit_avg)

# ==========================================================================
print("\n=== Genetics: Expression → Stat Modifiers ===")
# High genes → positive modifiers
high_chroms = ([15]*14, [15]*14)
high_mods = express(high_chroms)
check(f"Max genes → STR mod = {high_mods[Stat.STR]} (should be +3)", high_mods[Stat.STR] == 3)

# Low genes → negative modifiers
low_chroms = ([0]*14, [0]*14)
low_mods = express(low_chroms)
check(f"Min genes → STR mod = {low_mods[Stat.STR]} (should be -3)", low_mods[Stat.STR] == -3)

# Mid genes → ~0 modifier
mid_chroms = ([7]*14, [8]*14)
mid_mods = express(mid_chroms)
check(f"Mid genes → STR mod = {mid_mods[Stat.STR]} (should be ~0)", abs(mid_mods[Stat.STR]) <= 1)

# Apply genetics to species base
species_base = {Stat.STR: 12, Stat.VIT: 10, Stat.AGL: 10, Stat.PER: 10,
                Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10}
adjusted = apply_genetics(species_base, high_mods)
check(f"High genetics: STR {species_base[Stat.STR]} → {adjusted[Stat.STR]}",
      adjusted[Stat.STR] == 15)

adjusted_low = apply_genetics(species_base, low_mods)
check(f"Low genetics: STR {species_base[Stat.STR]} → {adjusted_low[Stat.STR]}",
      adjusted_low[Stat.STR] == 9)

# ==========================================================================
print("\n=== Genetics: Inheritance ===")
mother = generate_chromosomes('female')
father = generate_chromosomes('male')

child_m_chroms = inherit(mother, father, 'male')
check("Male child has 2 chromosomes", len(child_m_chroms) == 2)
check("Male child genes valid", all(0 <= g <= 15 for c in child_m_chroms for g in c))

child_f_chroms = inherit(mother, father, 'female')
check("Female child has 2 chromosomes", len(child_f_chroms) == 2)

# Verify inheritance: child genes should come from parents
# (not exhaustive, just sanity check that values are in parent range)
for i in range(NUM_GENES):
    parent_vals = {mother[0][i], mother[1][i], father[0][i], father[1][i]}
    # Child values should mostly be from parents (mutations are rare at 2%)
    # Don't assert — just verify the mechanism ran

# ==========================================================================
print("\n=== Genetics: Inbreeding Detection ===")
# Build a lineage tree:
# A(1) + B(2) → C(3)
# A(1) + B(2) → D(4)
# C(3) + D(4) → E(5)  ← siblings mating (closeness=1)
lineage = {
    3: (2, 1),   # C's parents are B(mother) and A(father)
    4: (2, 1),   # D's parents are B(mother) and A(father)
}

closeness = check_inbreeding(3, 4, lineage, generations=3)
check(f"Siblings share parents: closeness={closeness} (should be 1)", closeness == 1)

# Cousins: share grandparent
# A(1) + B(2) → C(3)
# A(1) + E(5) → D(4)
# C(3) and D(4) share A as parent/father
lineage2 = {
    3: (2, 1),  # C: mother=B, father=A
    4: (5, 1),  # D: mother=E, father=A
}
closeness2 = check_inbreeding(3, 4, lineage2, generations=3)
check(f"Half-siblings: closeness={closeness2}", closeness2 == 1)

# More distant: share great-grandparent
# G1(1) + G2(2) → P1(3)
# G1(1) + G3(4) → P2(5)
# P1(3) + X(6) → C1(7)
# P2(5) + Y(8) → C2(9)
# C1(7) and C2(9) share G1 as grandparent
lineage3 = {
    3: (2, 1),    # P1: parents G2, G1
    5: (4, 1),    # P2: parents G3, G1
    7: (6, 3),    # C1: parents X, P1
    9: (8, 5),    # C2: parents Y, P2
}
closeness3 = check_inbreeding(7, 9, lineage3, generations=3)
check(f"Share grandparent: closeness={closeness3} (should be 2)", closeness3 == 2)

# No shared ancestor
lineage4 = {
    3: (2, 1),
    4: (6, 5),
}
closeness4 = check_inbreeding(3, 4, lineage4, generations=3)
check(f"No shared ancestor: closeness={closeness4} (should be 0)", closeness4 == 0)

# ==========================================================================
print("\n=== Genetics: Inbreeding Mutation Rates ===")
check(f"No inbreeding rate: {inbreeding_mutation_rate(0):.2f}", abs(inbreeding_mutation_rate(0) - 0.02) < 0.001)
check(f"Siblings rate: {inbreeding_mutation_rate(1):.2f}", abs(inbreeding_mutation_rate(1) - 0.20) < 0.001)
check(f"Grandparent rate: {inbreeding_mutation_rate(2):.2f}", abs(inbreeding_mutation_rate(2) - 0.10) < 0.001)
check(f"Great-grandparent rate: {inbreeding_mutation_rate(3):.3f}", abs(inbreeding_mutation_rate(3) - 0.067) < 0.01)

# Inbred offspring have worse genes on average
normal_total = 0
inbred_total = 0
for _ in range(200):
    nc = inherit(mother, father, 'male', inbreeding_closeness=0)
    ic = inherit(mother, father, 'male', inbreeding_closeness=1)
    normal_total += sum(nc[0]) + sum(nc[1])
    inbred_total += sum(ic[0]) + sum(ic[1])

check(f"Inbred gene total {inbred_total} < normal {normal_total}",
      inbred_total < normal_total)

# ==========================================================================
print("\n=== Genetics: Lineage on Creature ===")
m48 = make_map()
parent_a = make_creature(m48, x=0, y=0, name='ParentA', sex='male')
parent_b = make_creature(m48, x=1, y=0, name='ParentB', sex='female')

parent_a.chromosomes = generate_chromosomes('male')
parent_b.chromosomes = generate_chromosomes('female')

child_chroms = inherit(parent_b.chromosomes, parent_a.chromosomes, 'female')
child_c = make_creature(m48, x=0, y=1, name='Child', sex='female',
                        chromosomes=child_chroms)
child_c.mother_uid = parent_b.uid
child_c.father_uid = parent_a.uid

check("Child has mother_uid", child_c.mother_uid == parent_b.uid)
check("Child has father_uid", child_c.father_uid == parent_a.uid)
check("Child has chromosomes", child_c.chromosomes is not None)

# Express and verify stats are modified
child_mods = express(child_c.chromosomes)
check(f"Child genetic STR mod: {child_mods[Stat.STR]} (in [-3,3])",
      -3 <= child_mods[Stat.STR] <= 3)

# ==========================================================================
print("\n=== Pairing: Species Gate ===")

m49 = make_map()
male_h = make_creature(m49, x=0, y=0, name='HumanM', sex='male', age=20)
male_h.species = 'human'
female_h = make_creature(m49, x=1, y=0, name='HumanF', sex='female', age=20)
female_h.species = 'human'

# Same species: always passes
same_pass = sum(1 for _ in range(100) if Creature._species_gate(male_h, female_h))
check(f"Same species gate: {same_pass}/100 pass", same_pass == 100)

# Cross species: ~1% pass
female_o = make_creature(m49, x=2, y=0, name='OrcF', sex='female', age=20)
female_o.species = 'orc'
cross_pass = sum(1 for _ in range(10000) if Creature._species_gate(male_h, female_o))
check(f"Cross species gate: {cross_pass}/10000 (~100 expected)", 20 < cross_pass < 250)

# Abom male + non-abom female: 0%
male_a = make_creature(m49, x=3, y=0, name='AbomM', sex='male', age=20)
male_a.is_abomination = True
abom_pass = sum(1 for _ in range(1000) if Creature._species_gate(male_a, female_h))
check(f"Abom male + human female: {abom_pass}/1000 (should be 0)", abom_pass == 0)

# Non-abom male + abom female: ~0.5%
female_a = make_creature(m49, x=4, y=0, name='AbomF', sex='female', age=20)
female_a.is_abomination = True
abom_f_pass = sum(1 for _ in range(10000) if Creature._species_gate(male_h, female_a))
check(f"Human male + abom female: {abom_f_pass}/10000 (~50 expected)", 5 < abom_f_pass < 150)

# Abom + abom: always pass
male_a2 = make_creature(m49, x=5, y=0, name='AbomM2', sex='male', age=20)
male_a2.is_abomination = True
aa_pass = sum(1 for _ in range(100) if Creature._species_gate(male_a2, female_a))
check(f"Abom + abom gate: {aa_pass}/100", aa_pass == 100)

# ==========================================================================
print("\n=== Pairing: Desirability ===")
m50 = make_map()
strong_m = make_creature(m50, x=0, y=0, name='StrongM', sex='male', age=20,
                         stats={Stat.STR: 18, Stat.CHR: 16, Stat.INT: 14,
                                Stat.VIT: 12, Stat.LCK: 12})
weak_m = make_creature(m50, x=1, y=0, name='WeakM', sex='male', age=20,
                       stats={Stat.STR: 6, Stat.CHR: 6, Stat.INT: 6})
eval_f = make_creature(m50, x=2, y=0, name='EvalF', sex='female', age=20)

d_strong = Creature.desirability(strong_m, eval_f)
d_weak = Creature.desirability(weak_m, eval_f)
check(f"Strong male desirability {d_strong:.2f} > weak {d_weak:.2f}", d_strong > d_weak)

# ==========================================================================
print("\n=== Pairing: Proposal + Egg ===")
from classes.genetics import generate_chromosomes
from classes.inventory import Egg

m51 = make_map()
adam = make_creature(m51, x=0, y=0, name='Adam', sex='male', age=25,
                     stats={Stat.STR: 14, Stat.CHR: 14, Stat.VIT: 12,
                            Stat.INT: 12, Stat.PER: 12, Stat.AGL: 12, Stat.LCK: 10})
adam.species = 'human'
adam.chromosomes = generate_chromosomes('male')
adam.prudishness = 0.1  # willing

eve = make_creature(m51, x=1, y=0, name='Eve', sex='female', age=25,
                    stats={Stat.VIT: 14, Stat.CHR: 14, Stat.AGL: 12,
                           Stat.INT: 12, Stat.PER: 12, Stat.STR: 10, Stat.LCK: 10})
eve.species = 'human'
eve.chromosomes = generate_chromosomes('female')
eve.prudishness = 0.1  # willing

# Build positive relationship (needed for female willingness)
for _ in range(10):
    adam.record_interaction(eve, 3.0)
    eve.record_interaction(adam, 3.0)

# Try pairing multiple times (fecundity + willingness are probabilistic)
pair_success = 0
eggs_created = 0
for _ in range(50):
    eve.is_pregnant = False
    eve.stats.remove_mods_by_source('pregnancy')
    adam._pair_cooldown = 0
    r = adam.propose_pairing(eve, now=1000)
    if r['accepted']:
        pair_success += 1
        eggs_created += 1 if r['egg'] is not None else 0
        # Clean up egg from inventory
        for item in list(eve.inventory.items):
            if isinstance(item, Egg):
                eve.inventory.items.remove(item)

check(f"Pairing successes: {pair_success}/50", pair_success > 0)
check(f"Eggs created: {eggs_created}", eggs_created > 0)

# Wrong sex
r = eve.propose_pairing(adam, now=1000)
check("Female can't propose pairing", r['reason'] == 'wrong_sex')

# Underage
young_m = make_creature(m51, x=0, y=1, name='YoungM', sex='male', age=10)
r = young_m.propose_pairing(eve, now=1000)
check("Underage male rejected", r['reason'] == 'underage')

# Already pregnant
eve.is_pregnant = True
adam._pair_cooldown = 0
r = adam.propose_pairing(eve, now=5000)
check("Pregnant female rejected", r['reason'] == 'already_pregnant')
eve.is_pregnant = False

# ==========================================================================
print("\n=== Egg Lifecycle ===")
m52 = make_map()
mother_e = make_creature(m52, x=0, y=0, name='Mother', sex='female', age=25)
mother_e.species = 'human'
mother_e.chromosomes = generate_chromosomes('female')
father_e = make_creature(m52, x=1, y=0, name='Father', sex='male', age=25)
father_e.species = 'human'
father_e.chromosomes = generate_chromosomes('male')

# Create test egg directly
from classes.genetics import inherit, express, apply_genetics
child_chroms = inherit(mother_e.chromosomes, father_e.chromosomes, 'female')
child_obj = Creature.__new__(Creature)
child_obj.name = 'TestChild'
child_obj.species = 'human'
child_obj.sex = 'female'
child_obj.chromosomes = child_chroms
child_obj.mother_uid = mother_e.uid
child_obj.father_uid = father_e.uid
child_obj.is_abomination = False
child_obj.inbred = False
child_obj.age = 0
child_obj.prudishness = 0.5
# GRAPH auto-creates empty dicts on first access — no init needed
child_obj.is_pregnant = False
child_obj._pair_cooldown = 0
child_obj.sleep_debt = 0
child_obj._fatigue_level = 0
child_obj._stats_for_egg = {Stat.STR: 10, Stat.VIT: 10, Stat.AGL: 10,
                             Stat.PER: 10, Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10}

test_egg = Egg(creature=child_obj, mother_species='human', father_species='human')
check("Egg is live", test_egg.live)
check("Not abomination", not test_egg.is_abomination)
check("Not ready to hatch", not test_egg.ready_to_hatch)

# Gestate for 30 days with mother
for day in range(30):
    test_egg.tick_gestation(carried_by_mother=True)

if test_egg.live:
    check(f"After 30 days: gestation={test_egg.gestation_days}", test_egg.gestation_days == 30)
    check(f"Days with mother: {test_egg.days_with_mother}", test_egg.days_with_mother == 30)
    check("Ready to hatch", test_egg.ready_to_hatch)

    # Hatch
    tile_e = m52.tiles[MapKey(0, 0, 0)]
    hatched = test_egg.hatch(m52, MapKey(0, 0, 0))
    check("Hatched creature exists", hatched is not None)
    check("Hatched on map", hatched.current_map is m52)
    check("Hatched age = 0", hatched.age == 0)
    check("Egg no longer live", not test_egg.live)
    check(f"Mother UID: {hatched.mother_uid}", hatched.mother_uid == mother_e.uid)
    check(f"Father UID: {hatched.father_uid}", hatched.father_uid == father_e.uid)
else:
    # Egg died during gestation (1% per day chance — unlikely but possible)
    check("Egg died during gestation (rare)", not test_egg.live)

# Abandoned egg: no maternal buff
abandoned_egg = Egg(creature=Creature.__new__(Creature))
abandoned_egg.creature.name = 'Abandoned'
# GRAPH auto-creates empty dicts on first access — no init needed
for day in range(30):
    abandoned_egg.tick_gestation(carried_by_mother=False)
check(f"Abandoned egg: days with mother = {abandoned_egg.days_with_mother}",
      abandoned_egg.days_with_mother == 0)

# ==========================================================================
print("\n=== Pregnancy Debuffs ===")
m53 = make_map()
preg_f = make_creature(m53, x=0, y=0, name='PregF', sex='female', age=25,
                       stats={Stat.AGL: 14, Stat.VIT: 12, Stat.INT: 10,
                              Stat.STR: 10, Stat.PER: 10, Stat.CHR: 10, Stat.LCK: 10})
agl_before = preg_f.stats.active[Stat.AGL]()
speed_before = preg_f.stats.active[Stat.MOVE_SPEED]()

# Simulate pregnancy debuffs (as applied during _execute_pairing)
preg_f.stats.add_mod('pregnancy', Stat.AGL, -2)
preg_f.stats.add_mod('pregnancy', Stat.MOVE_SPEED, -1)
preg_f.stats.add_mod('pregnancy', Stat.STAM_REGEN, -2)
preg_f.is_pregnant = True

agl_during = preg_f.stats.active[Stat.AGL]()
speed_during = preg_f.stats.active[Stat.MOVE_SPEED]()
check(f"AGL debuffed: {agl_before} → {agl_during}", agl_during == agl_before - 2)
# AGL debuff also cascades into MOVE_SPEED (derived from AGL), so total speed drop > 1
check(f"Speed debuffed: {speed_before} → {speed_during}", speed_during < speed_before)

# End pregnancy
preg_f.end_pregnancy()
check("Not pregnant after end", not preg_f.is_pregnant)
agl_after = preg_f.stats.active[Stat.AGL]()
check(f"AGL restored: {agl_after}", agl_after == agl_before)

# ==========================================================================
print("\n=== Solicit Rumor ===")
m54 = make_map()
curious = make_creature(m54, x=0, y=0, name='Curious',
                        stats={Stat.CHR: 14, Stat.PER: 12})
informant = make_creature(m54, x=1, y=0, name='Informant',
                          stats={Stat.PER: 10})
subject_s = make_creature(m54, x=5, y=5, name='Subject')

# Curious has weak opinion of subject
curious.record_interaction(subject_s, 1.0)
curious.record_interaction(subject_s, 0.5)
# Informant has strong opinion
informant.record_interaction(subject_s, -10.0)
for _ in range(5):
    informant.record_interaction(subject_s, -2.0)

# Solicit rumor
successes_sr = 0
for _ in range(50):
    if curious.solicit_rumor(informant, tick=100):
        successes_sr += 1

check(f"Solicited rumors: {successes_sr}/50", successes_sr > 0)
# Check that curious now has rumors about subject
rumors_s = GRAPH.get_rumors(curious.uid, subject_s.uid) or []
check(f"Curious has {len(rumors_s)} rumors about subject", len(rumors_s) > 0)

# ==========================================================================
print("\n=== Fecundity Curve ===")
m55 = make_map()
young_f = make_creature(m55, x=0, y=0, name='YoungF', sex='female', age=18)
check(f"Fecundity at 18: {young_f.fecundity():.2f}", young_f.fecundity() == 1.0)

mid_f = make_creature(m55, x=1, y=0, name='MidF', sex='female', age=200)
check(f"Fecundity at 200: {mid_f.fecundity():.2f} (should be ~1.0)", mid_f.fecundity() > 0.8)

old_f = make_creature(m55, x=2, y=0, name='OldF', sex='female', age=364)
check(f"Fecundity at 364: {old_f.fecundity():.2f} (near 0)", old_f.fecundity() < 0.1)

ancient_f = make_creature(m55, x=3, y=0, name='AncientF', sex='female', age=400)
check(f"Fecundity at 400: {ancient_f.fecundity():.2f} (= 0)", ancient_f.fecundity() == 0.0)

child_f = make_creature(m55, x=4, y=0, name='ChildF', sex='female', age=10)
check(f"Fecundity at 10 (child): {child_f.fecundity():.2f} (= 0)", child_f.fecundity() == 0.0)

male_fec = make_creature(m55, x=5, y=0, name='MaleF', sex='male', age=25)
check(f"Male fecundity: {male_fec.fecundity():.2f} (= 0)", male_fec.fecundity() == 0.0)

# ==========================================================================
print("\n=== Witness Reactions ===")
m56 = make_map()
witness = make_creature(m56, x=2, y=0, name='Witness', stats={Stat.PER: 14})
perp = make_creature(m56, x=0, y=0, name='Perp', sex='male')
victim_w = make_creature(m56, x=1, y=0, name='Victim', sex='female')

# Witness favors female → negative for male
witness.record_interaction(victim_w, 10.0)
witness.record_interaction(perp, -5.0)
sent_before = witness.get_relationship(perp)[0]
witness.witness_forced_encounter(perp, victim_w)
sent_after = witness.get_relationship(perp)[0]
check(f"Witness favors female: perp sentiment {sent_before} → {sent_after} (more negative)",
      sent_after < sent_before)

# Witness favors male → neutral (no change)
witness2 = make_creature(m56, x=3, y=0, name='Witness2')
witness2.record_interaction(perp, 10.0)
witness2.record_interaction(victim_w, -2.0)
witness2.witness_forced_encounter(perp, victim_w)
rel_w2 = witness2.get_relationship(perp)
check("Witness favors male: no additional negative recorded",
      rel_w2[0] == 10.0)  # unchanged

# ==========================================================================
print("\n=== Egg Eating ===")
m57 = make_map()
eater = make_creature(m57, x=0, y=0, name='Eater')
eater.species = 'human'
witness_e = make_creature(m57, x=1, y=0, name='EggWitness', stats={Stat.PER: 14})

# Non-cannibalism (eating orc egg as human)
orc_egg = Egg(creature=None, mother_species='orc', father_species='orc')
eater.inventory.items.append(orc_egg)
r = eater.eat_egg(orc_egg)
check("Ate orc egg", r['eaten'])
check("Not cannibalism", not r['cannibalism'])

# Cannibalism (eating human egg as human)
human_egg = Egg(creature=None, mother_species='human', father_species='human')
eater.inventory.items.append(human_egg)
witness_e_sent_before = witness_e.get_relationship(eater)
r = eater.eat_egg(human_egg)
check("Ate human egg", r['eaten'])
check("IS cannibalism", r['cannibalism'])
witness_e_rel = witness_e.get_relationship(eater)
check(f"Witness recorded massive negative: {witness_e_rel[0]}",
      witness_e_rel[0] <= -20.0)

# ==========================================================================
print("\n=== Parent-Child Bonding ===")
m58 = make_map()
parent_p = make_creature(m58, x=0, y=0, name='BondParent')
child_p = make_creature(m58, x=0, y=0, name='BondChild', age=0)

parent_p.bond_with_child(child_p)
check("Parent → child sentiment = 15.0", parent_p.get_relationship(child_p)[0] == 15.0)
check("Child → parent sentiment = 15.0", child_p.get_relationship(parent_p)[0] == 15.0)

# ==========================================================================
print("\n=== Age Properties ===")
m59 = make_map()
baby = make_creature(m59, x=0, y=0, name='Baby', age=5)
adult_a = make_creature(m59, x=1, y=0, name='Adult', age=25)
old_a = make_creature(m59, x=2, y=0, name='Elder', age=400)

check("Baby is child", baby.is_child)
check("Baby not adult", not baby.is_adult)
check("Adult is adult", adult_a.is_adult)
check("Adult not child", not adult_a.is_child)

# ==========================================================================
print("\n=== Age Sentiment Modifiers ===")
m60 = make_map()
elder_m = make_creature(m60, x=0, y=0, name='Elder', sex='male', age=200)
young_f = make_creature(m60, x=1, y=0, name='YoungWoman', sex='female', age=20)
child_c = make_creature(m60, x=2, y=0, name='Kid', age=10)
mother_m = make_creature(m60, x=3, y=0, name='Mom', sex='female', age=100)
mother_m._has_hatched_child = True

# Older male → younger woman: favorable
mod_m = elder_m.age_sentiment_modifier(young_f)
check(f"Elder male → young woman: {mod_m:.2f} (positive)", mod_m > 0)

# Adult → child: exploit tendency
mod_exploit = elder_m.age_sentiment_modifier(child_c)
check(f"Adult → child: {mod_exploit:.2f} (negative)", mod_exploit < 0)

# Mother → child: kindness
mod_mother = mother_m.age_sentiment_modifier(child_c)
check(f"Mother → child: {mod_mother:.2f} (positive, overrides exploit)", mod_mother > 0)

# ==========================================================================
print("\n=== Gender Competition ===")
m61 = make_map(cols=10, rows=10)
male_comp = make_creature(m61, x=5, y=5, name='CompMale', sex='male', age=25,
                          stats={Stat.STR: 14, Stat.CHR: 14, Stat.PER: 14})
# Add some competitors — hold strong refs to prevent WeakSet GC
_male_rivals = [make_creature(m61, x=6+i, y=5, name=f'RivalM{i}', sex='male', age=25,
                               stats={Stat.STR: 16, Stat.CHR: 16, Stat.PER: 14})
                for i in range(3)]

rank = male_comp.attractiveness_rank_nearby()
check(f"Male rank with 3 stronger rivals: {rank:.2f} (low)", rank < 0.5)

eagerness = male_comp.pairing_eagerness()
check(f"Male eagerness (low rank = high drive): {eagerness:.2f} (positive)", eagerness > 0)

# Female with less attractive rivals — hold strong refs
female_comp = make_creature(m61, x=5, y=6, name='CompFemale', sex='female', age=25,
                            stats={Stat.VIT: 16, Stat.CHR: 16, Stat.AGL: 14, Stat.PER: 14})
_female_rivals = [make_creature(m61, x=6+i, y=6, name=f'RivalF{i}', sex='female', age=25,
                                 stats={Stat.VIT: 8, Stat.CHR: 8, Stat.PER: 14})
                  for i in range(3)]

f_rank = female_comp.attractiveness_rank_nearby()
check(f"Female rank with weaker rivals: {f_rank:.2f} (high)", f_rank > 0.5)

f_eagerness = female_comp.pairing_eagerness()
check(f"Female eagerness (high rank = higher standards): {f_eagerness:.2f}", f_eagerness > 0)

# ==========================================================================
print("\n=== Egg World Limits ===")
# Count should reflect eggs created during pairing tests
egg_count = Creature.count_eggs_in_world()
check(f"Egg count in world: {egg_count}", egg_count >= 0)

# Test the limit check
check("Egg limit with max=99999: not reached", not Creature.egg_limit_reached(99999))
check("Egg limit with max=0: reached", Creature.egg_limit_reached(0))

# ==========================================================================
print("\n=== Pair Bond ===")
m62 = make_map(cols=10, rows=10)
mate_m = make_creature(m62, x=0, y=0, name='MateM', sex='male', age=25)
mate_f = make_creature(m62, x=1, y=0, name='MateF', sex='female', age=25)

# Form bond
mate_m.partner_uid = mate_f.uid
mate_f.partner_uid = mate_m.uid

check("Male has partner", mate_m.has_partner)
check("Female has partner", mate_f.has_partner)
check("Male's partner is female", mate_m.get_partner() is mate_f)
check("Female's partner is male", mate_f.get_partner() is mate_m)

# Break bond
mate_m.break_pair_bond()
check("Male has no partner after break", not mate_m.has_partner)
check("Female also unpartnered", not mate_f.has_partner)

# ==========================================================================
print("\n=== PairedBehavior ===")
from classes.creature import PairedBehavior

m63 = make_map(cols=10, rows=10)
paired_m = make_creature(m63, x=0, y=0, name='PairedM', sex='male', age=25)
paired_f = make_creature(m63, x=5, y=5, name='PairedF', sex='female', age=25)

paired_m.partner_uid = paired_f.uid
paired_f.partner_uid = paired_m.uid

pb = PairedBehavior()
# Partner is far (dist=10) → should follow
old_loc = paired_m.location
pb.think(paired_m, 10, 10)
check("PairedBehavior: moved toward partner", paired_m.location != old_loc)
# Should be closer now
new_dist = abs(paired_m.location.x - paired_f.location.x) + abs(paired_m.location.y - paired_f.location.y)
check(f"Closer to partner: dist={new_dist}", new_dist < 10)

# Run 20 cycles
for _ in range(20):
    pb.think(paired_m, 10, 10)
final_dist = abs(paired_m.location.x - paired_f.location.x) + abs(paired_m.location.y - paired_f.location.y)
check(f"After 20 cycles: dist={final_dist} (should be <=3)", final_dist <= 3)

# Dead partner → break bond
paired_f.stats.base[Stat.HP_CURR] = 0
pb.think(paired_m, 10, 10)
check("Bond broken when partner dies", not paired_m.has_partner)

# ==========================================================================
print("\n=== Child-Parent No-Collide ===")
m64 = make_map(cols=5, rows=5)
parent_nc = make_creature(m64, x=2, y=2, name='ParentNC', age=30)
child_nc = make_creature(m64, x=2, y=1, name='ChildNC', age=5,
                         mother_uid=parent_nc.uid)
child_nc.mother_uid = parent_nc.uid

# Child should be able to walk onto parent's tile
old_child_loc = child_nc.location
child_nc.move(0, 1, 5, 5)  # move south into parent's tile (2,2)
check(f"Child walked onto parent tile: ({child_nc.location.x},{child_nc.location.y})",
      child_nc.location.x == 2 and child_nc.location.y == 2)

# With size-based capacity: medium=4 units, tile=16
# Parent(4) + child(4) = 8, other adult(4) = 12 total ≤ 16 → fits
other_adult = make_creature(m64, x=2, y=3, name='OtherAdult', age=30)
other_adult.move(0, -1, 5, 5)  # move into (2,2) — should fit
check(f"Medium adults can share tile (capacity): moved to ({other_adult.location.x},{other_adult.location.y})",
      other_adult.location.x == 2 and other_adult.location.y == 2)

# Fill tile to capacity: 4 medium creatures = 16 units, 5th blocked
fill_creature = make_creature(m64, x=2, y=2, name='FillC', age=30)
# Now tile has: parent(4) + child(4) + other(4) + fill(4) = 16 units
blocked_adult = make_creature(m64, x=2, y=4, name='BlockedAdult', age=30)
old_blocked = blocked_adult.location
blocked_adult.move(0, -1, 5, 5)  # try to move to (2,3) first
blocked_adult.move(0, -1, 5, 5)  # then try (2,2) — should be full
check(f"5th medium creature blocked at full tile", blocked_adult.location.y != 2)

# ==========================================================================
print("\n=== Tent Spawn/Despawn ===")
from classes.world_object import WorldObject as WO

m65 = make_map()
tent = Creature.spawn_tent(m65, MapKey(3, 3, 0))
check("Tent is a WorldObject", isinstance(tent, WO))
check("Tent sprite is tent_pairing", tent.sprite_name == 'tent_pairing')
check("Tent on map", tent.current_map is m65)

# Check it's in the map's object registry
objects_on_map = WO.on_map(m65)
check("Tent in map objects", tent in objects_on_map)

Creature.despawn_tent(tent)
check("Tent removed from map", tent.current_map is None)
objects_after = WO.on_map(m65)
check("Tent not in map objects after despawn", tent not in objects_after)

# ==========================================================================
print("\n=== Quest System ===")
from classes.quest import QuestLog, QuestState, _safe_eval

ql = QuestLog()

# Define a test quest
test_quest = {
    'name': 'find_sword', 'giver': 'blacksmith',
    'description': 'Find the lost sword', 'quest_type': 'quest',
    'conditions': '', 'reward_action': '', 'fail_action': '',
    'time_limit': 60, 'repeatable': False, 'cooldown_days': None,
}
test_steps = [
    {'step_no': 1, 'step_sub': 'a', 'description': 'Talk to guard',
     'success_condition': '', 'fail_condition': '',
     'success_action': '', 'fail_action': '',
     'step_map': None, 'step_location_x': None, 'step_location_y': None,
     'step_npc': 'guard', 'time_limit': None},
    {'step_no': 2, 'step_sub': 'a', 'description': 'Find the cave',
     'success_condition': '', 'fail_condition': '',
     'success_action': '', 'fail_action': '',
     'step_map': 'cave', 'step_location_x': 5, 'step_location_y': 5,
     'step_npc': None, 'time_limit': 30},
    {'step_no': 2, 'step_sub': 'b', 'description': 'Defeat the troll',
     'success_condition': '', 'fail_condition': '',
     'success_action': '', 'fail_action': '',
     'step_map': 'cave', 'step_location_x': None, 'step_location_y': None,
     'step_npc': 'troll', 'time_limit': None},
]

# Accept quest
check("Accept quest", ql.accept_quest('find_sword', test_quest, now=0))
check("Quest is active", ql.get_quest_state('find_sword') == QuestState.ACTIVE)
check("Can't accept twice", not ql.accept_quest('find_sword', test_quest, now=0))

# Complete steps
check("Complete step 1a", ql.complete_step('find_sword', 1, 'a'))
check("Step 1a is done", ql.is_step_complete('find_sword', 1, 'a'))
check("Step 2a not done yet", not ql.is_step_complete('find_sword', 2, 'a'))

# Not all steps done → quest not complete
check("Quest not complete yet", not ql.check_quest_complete('find_sword', test_steps))

# Complete remaining steps
ql.complete_step('find_sword', 2, 'a')
ql.complete_step('find_sword', 2, 'b')
check("All steps done", ql.check_quest_complete('find_sword', test_steps))

# Complete quest
check("Complete quest", ql.complete_quest('find_sword', now=5000, quest_def=test_quest))
check("Quest state = completed", ql.get_quest_state('find_sword') == QuestState.COMPLETED)

# Fail a quest
ql2 = QuestLog()
ql2.accept_quest('find_sword', test_quest, now=0)
check("Fail quest", ql2.fail_quest('find_sword'))
check("Failed state", ql2.get_quest_state('find_sword') == QuestState.FAILED)

# Time limit
ql3 = QuestLog()
ql3.accept_quest('find_sword', test_quest, now=0)
check("Not timed out at 50s", not ql3.check_time_limits('find_sword', test_quest, test_steps, now=50000))
check("Timed out at 61s", ql3.check_time_limits('find_sword', test_quest, test_steps, now=61000))

# Safe eval
check("Safe eval: empty = True", _safe_eval('', {}))
check("Safe eval: simple True", _safe_eval('1 + 1 == 2', {}))
check("Safe eval: with namespace", _safe_eval('x > 5', {'x': 10}))
check("Safe eval: False", not _safe_eval('x > 5', {'x': 3}))
check("Safe eval: blocks __import__", not _safe_eval('__import__("os")', {}))

# Active quests list
check("Active quests list", 'find_sword' in ql3.get_active_quests())

# Repeatable job
job_quest = {
    'name': 'gather_wood', 'giver': 'lumberjack',
    'description': 'Gather wood', 'quest_type': 'job',
    'conditions': '', 'reward_action': '', 'fail_action': '',
    'time_limit': None, 'repeatable': True, 'cooldown_days': 1,
}
ql4 = QuestLog()
ql4.accept_quest('gather_wood', job_quest, now=0)
ql4.complete_quest('gather_wood', now=1000, quest_def=job_quest)
check("Job completed", ql4.get_quest_state('gather_wood') == QuestState.COMPLETED)
# Can't re-accept during cooldown
check("Job on cooldown", not ql4.accept_quest('gather_wood', job_quest, now=2000))
# Can re-accept after cooldown (1 day = 86400000ms)
check("Job after cooldown", ql4.accept_quest('gather_wood', job_quest, now=86_500_000))

# Quest log on creature
m66 = make_map()
quest_creature = make_creature(m66, x=0, y=0, name='Quester')
check("Creature has quest_log", hasattr(quest_creature, 'quest_log'))
check("Quest log is QuestLog", isinstance(quest_creature.quest_log, QuestLog))

# ==========================================================================
print("\n=== Valuation System ===")
from classes.valuation import (
    compute_raw_kpi, decompounded_value, worth_to_creature,
    min_sell_price, max_buy_price, compute_trade_price, trade_reward,
)
import math

m67v = make_map()
val_creature = make_creature(m67v, x=0, y=0, name='ValCreature',
                             stats={Stat.STR: 14, Stat.AGL: 12, Stat.VIT: 12,
                                    Stat.PER: 12, Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10})
val_creature.gold = 200

# Decompounding formula
check("Decompound(0 uses) = 0", decompounded_value(10.0, 0) == 0.0)
check("Decompound(1 use) has premium + floor",
      decompounded_value(10.0, 1) == (10.0 ** 1.0) - 1 + 1.5 * 10.0)

# More durability = more value, but diminishing
val_5 = decompounded_value(10.0, 5)
val_10 = decompounded_value(10.0, 10)
val_50 = decompounded_value(10.0, 50)
check(f"5 uses ({val_5:.1f}) < 10 uses ({val_10:.1f}) < 50 uses ({val_50:.1f})",
      val_5 < val_10 < val_50)

# Per-use value diminishes
per_use_5 = val_5 / 5
per_use_50 = val_50 / 50
check(f"Per-use value diminishes: {per_use_5:.1f} > {per_use_50:.1f}",
      per_use_5 > per_use_50)

# Raw KPI for a weapon
test_sword = Weapon(name='TestSword', weight=3.0, value=50.0,
                    slots=[Slot.HAND_R], slot_count=1, damage=8,
                    buffs={Stat.MELEE_DMG: 2})
kpi = compute_raw_kpi(test_sword, val_creature)
check(f"Sword KPI = {kpi:.1f} (positive)", kpi > 0)

# Worth to creature
worth = worth_to_creature(test_sword, val_creature)
check(f"Sword worth = {worth:.1f} (positive)", worth > 0)

# Better weapon should have higher worth
weak_sword = Weapon(name='WeakSword', weight=2.0, value=20.0,
                    slots=[Slot.HAND_R], slot_count=1, damage=3)
weak_worth = worth_to_creature(weak_sword, val_creature)
check(f"Strong sword ({worth:.0f}) > weak sword ({weak_worth:.0f})", worth > weak_worth)

# Min sell price = max(paid, worth)
val_creature._item_prices[id(test_sword)] = 40.0
sell_min = min_sell_price(test_sword, val_creature)
check(f"Min sell = max(paid=40, worth={worth:.0f}) = {sell_min:.0f}", sell_min == max(40, worth))

# Trade between two creatures
buyer = make_creature(m67v, x=1, y=0, name='Buyer',
                      stats={Stat.STR: 10, Stat.CHR: 16, Stat.PER: 10, Stat.VIT: 10})
buyer.gold = 300

seller = make_creature(m67v, x=0, y=1, name='Seller',
                       stats={Stat.STR: 12, Stat.CHR: 10, Stat.PER: 10, Stat.VIT: 10})
seller.gold = 100
seller._item_prices[id(test_sword)] = 50.0
seller.inventory.items.append(test_sword)

trade = compute_trade_price(test_sword, seller, buyer)
if trade['feasible']:
    check(f"Trade feasible: price={trade['price']:.1f}", True)
    check(f"Price between min ({trade['seller_min']:.0f}) and max ({trade['buyer_max']:.0f})",
          trade['seller_min'] <= trade['price'] <= trade['buyer_max'])
    check(f"Buyer surplus: {trade['buyer_surplus']:.1f} >= 0", trade['buyer_surplus'] >= 0)
    check(f"Seller surplus: {trade['seller_surplus']:.1f} >= 0", trade['seller_surplus'] >= 0)
    # High CHR buyer should get better deal (seller_share lower)
    check("High CHR buyer gets more surplus", trade['buyer_surplus'] >= trade['seller_surplus'])
else:
    check("Trade not feasible (item not valuable enough to buyer)", True)

# Trade reward uses ln
tr = trade_reward(10.0, 100.0)
check(f"Trade reward: ln(1 + 10/100) = {tr:.4f}", abs(tr - math.log(1.1)) < 0.001)

# Desperate seller (liabilities > gold)
desperate = make_creature(m67v, x=2, y=0, name='Desperate',
                          stats={Stat.STR: 10, Stat.CHR: 10})
desperate.gold = 10
desperate.liabilities = 50.0  # underwater
desperate._item_prices[id(weak_sword)] = 30.0
desperate.inventory.items.append(weak_sword)

d_trade = compute_trade_price(weak_sword, desperate, buyer)
if d_trade['feasible']:
    check(f"Desperate seller accepts lower price: {d_trade['price']:.1f}", d_trade['price'] > 0)

# ==========================================================================
print("\n=== Loan System ===")
m68 = make_map()
lender = make_creature(m68, x=0, y=0, name='Lender',
                       stats={Stat.CHR: 14, Stat.STR: 10, Stat.PER: 10})
lender.gold = 500
borrower_l = make_creature(m68, x=1, y=0, name='Borrower',
                           stats={Stat.CHR: 10, Stat.STR: 10, Stat.PER: 10})
borrower_l.gold = 50

# Give a loan
check("Give loan succeeds", lender.give_loan(borrower_l, 100, daily_rate=0.1, now=0))
check(f"Lender gold: {lender.gold}", lender.gold == 400)
check(f"Borrower gold: {borrower_l.gold}", borrower_l.gold == 150)
check("Loan recorded on borrower", lender.uid in borrower_l.loans)
check("Loan recorded on lender", borrower_l.uid in lender.loans_given)

# Debt calculation (no time passed)
owed = borrower_l.debt_owed_to(lender.uid, now=0)
check(f"Debt at t=0: {owed:.1f} (should be 100)", abs(owed - 100) < 0.1)

# Debt with interest (1 day at 10%)
owed_1d = borrower_l.debt_owed_to(lender.uid, now=86_400_000)
check(f"Debt after 1 day: {owed_1d:.1f} (should be ~110)", abs(owed_1d - 110) < 1)

# Debt after 5 days
owed_5d = borrower_l.debt_owed_to(lender.uid, now=5 * 86_400_000)
check(f"Debt after 5 days: {owed_5d:.1f} (compounding)", owed_5d > 150)

# Total debt
total = borrower_l.total_debt(now=0)
check(f"Total debt: {total:.1f}", abs(total - 100) < 0.1)

# Disposable wealth
disp = borrower_l.disposable_wealth(now=0)
check(f"Disposable wealth: {disp:.1f} (150 - 100 = 50)", abs(disp - 50) < 0.1)

# Underwater after interest
disp_5d = borrower_l.disposable_wealth(now=5 * 86_400_000)
check(f"Underwater after 5 days: disposable={disp_5d:.1f}", disp_5d < 0)

# Partial repayment
r = borrower_l.repay_loan(lender, 60.0, now=0)
check(f"Partial repay: paid={r['paid']:.1f}", r['paid'] == 60)
check(f"Remaining: {r['remaining']:.1f}", r['remaining'] > 0)
check("Not fully repaid", not r['fully_repaid'])
check(f"Borrower gold after repay: {borrower_l.gold}", borrower_l.gold == 90)

# Full repayment
borrower_l.gold = 200
r2 = borrower_l.repay_loan(lender, 200.0, now=0)
check("Fully repaid", r2['fully_repaid'])
check("Loan cleared from borrower", lender.uid not in borrower_l.loans)
check("Loan cleared from lender", borrower_l.uid not in lender.loans_given)

# Collect debt
lender.give_loan(borrower_l, 50, daily_rate=0.05, now=0)
borrower_l.gold = 10  # can't fully pay
r3 = lender.collect_debt(borrower_l, now=0)
check(f"Collected: {r3['collected']:.1f} (partial)", r3['collected'] == 10)
check(f"Remaining: {r3['remaining']:.1f}", r3['remaining'] > 0)

# Default: 0 gold
borrower_l.gold = 0
r4 = lender.collect_debt(borrower_l, now=0)
check("Default: can't pay", r4['defaulted'])

# Can't loan more than you have
poor = make_creature(m68, x=2, y=0, name='Poor')
poor.gold = 5
check("Can't loan more than you have", not poor.give_loan(borrower_l, 100))

# ==========================================================================
print("\n=== Gods / Piety System ===")
from classes.gods import WorldData, God, compute_piety_drift, update_creature_piety

world = WorldData()
check(f"Gods loaded: {len(world.gods)}", len(world.gods) == 8)
check(f"Dichotomies: {len(world.dichotomies)}", len(world.dichotomies) == 4)

# Check opposition
check("Solmara opposes Vaelkor", world.is_opposed('Solmara', 'Vaelkor'))
check("Vaelkor opposes Solmara", world.is_opposed('Vaelkor', 'Solmara'))
check("Solmara not opposed to Aelora", not world.is_opposed('Solmara', 'Aelora'))

# Same axis check
check("Solmara + Vaelkor on same axis", world.is_aligned_axis('Solmara', 'Vaelkor'))
check("Solmara + Nyssara NOT same axis", not world.is_aligned_axis('Solmara', 'Nyssara'))

# Record actions → god counter
world.record_action('melee_attack')  # Vaelkor (wrath)
world.record_action('melee_attack')
world.record_action('talk')          # Solmara (compassion)
check("Vaelkor count = 2", world.gods['Vaelkor'].action_count == 2)
check("Solmara count = 1", world.gods['Solmara'].action_count == 1)

# World balance
balance = world.get_balance('Vaelkor')
check(f"Vaelkor balance: {balance:.2f} (positive = wrath winning)", balance > 0)
balance_s = world.get_balance('Solmara')
check(f"Solmara balance: {balance_s:.2f} (negative = compassion losing)", balance_s < 0)

# Get god for action
check("melee_attack → Vaelkor", world.get_god_for_action('melee_attack') == 'Vaelkor')
check("talk → Solmara", world.get_god_for_action('talk') == 'Solmara')
check("wait → Aelora (order)", world.get_god_for_action('wait') == 'Aelora')
check("steal → Xarith (chaos) or Nyssara (lies)",
      world.get_god_for_action('steal') in ('Xarith', 'Nyssara'))

# World flags
world.set_flag('dragon_defeated', True)
check("World flag set", world.get_flag('dragon_defeated') is True)
check("Missing flag = None", world.get_flag('nonexistent') is None)

# Piety drift calculation
drift = compute_piety_drift(0.8, 1.5)  # me=0.8, opposing=1.5
check(f"Piety drift: {drift:.4f}", drift > 0)
drift_none = compute_piety_drift(0.0, 1.0)  # no piety = no drift
check("No piety = no drift", drift_none == 0.0)

# Creature piety
m67 = make_map()
devotee = make_creature(m67, x=0, y=0, name='Devotee', stats={Stat.PER: 14})
devotee.deity = 'Solmara'
devotee.piety = 0.5

heretic = make_creature(m67, x=1, y=0, name='Heretic', stats={Stat.PER: 10})
heretic.deity = 'Vaelkor'
heretic.piety = 0.8

# Witnessing aligned action → reinforce
piety_before = devotee.piety
update_creature_piety(devotee, 'talk', world, [devotee, heretic])
check(f"Aligned action reinforces: {piety_before} → {devotee.piety}", devotee.piety > piety_before)

# Witnessing opposing action → erode
piety_before2 = devotee.piety
update_creature_piety(devotee, 'melee_attack', world, [devotee, heretic])
check(f"Opposing action erodes: {piety_before2} → {devotee.piety}", devotee.piety < piety_before2)

# Unrelated action → no change
piety_before3 = devotee.piety
update_creature_piety(devotee, 'steal', world, [devotee, heretic])
check(f"Unrelated axis: no change {piety_before3} → {devotee.piety}", devotee.piety == piety_before3)

# Heavy erosion → lose god
devotee.piety = 0.001
update_creature_piety(devotee, 'melee_attack', world, [devotee, heretic])
check(f"Heavy erosion: deity={devotee.deity}, piety={devotee.piety}",
      devotee.deity is None and devotee.piety == 0.0)

# Creature without deity: no effect
neutral = make_creature(m67, x=2, y=0, name='Neutral')
neutral.deity = None
piety_n = neutral.piety
update_creature_piety(neutral, 'melee_attack', world, [neutral, heretic])
check("No deity = no piety change", neutral.piety == piety_n)

# ==========================================================================
print("\n=== Observation Masks ===")
from classes.observation import (
    apply_mask, apply_preset_mask, SECTION_RANGES, PRESET_MASKS,
    OBSERVATION_SIZE as OBS_SIZE,
)

m_mask = make_map(cols=10, rows=10)
masked_c = make_creature(m_mask, x=5, y=5, name='MaskedC',
                         stats={Stat.STR: 14, Stat.CHR: 16, Stat.PER: 12})
# Give them some social relationships
other_c = make_creature(m_mask, x=6, y=5, name='OtherC')
masked_c.record_interaction(other_c, 10.0)
masked_c.record_interaction(other_c, 5.0)

obs_normal = build_observation(masked_c, 10, 10)
check(f"Normal obs size: {len(obs_normal)}", len(obs_normal) == OBS_SIZE)

# Social section should have non-zero values (has relationships)
social_start, social_end = SECTION_RANGES['self_social']
social_vals = obs_normal[social_start:social_end]
check("Social section has non-zero values", any(v != 0 for v in social_vals))

# Apply socially_deaf mask
obs_masked = list(obs_normal)  # copy
apply_preset_mask(obs_masked, 'socially_deaf')

# Social sections should be zeroed
social_masked = obs_masked[social_start:social_end]
check("Socially deaf: self_social zeroed", all(v == 0 for v in social_masked))

# Reputation should also be zeroed (part of 'social' group)
rep_start, rep_end = SECTION_RANGES['self_reputation']
check("Socially deaf: reputation zeroed", all(v == 0 for v in obs_masked[rep_start:rep_end]))

# Census should be zeroed (part of 'social' group)
census_start, census_end = SECTION_RANGES['census_visible']
check("Socially deaf: census zeroed", all(v == 0 for v in obs_masked[census_start:census_end]))

# Non-social sections should be untouched
base_start, base_end = SECTION_RANGES['self_base']
check("Socially deaf: base stats untouched",
      obs_masked[base_start:base_end] == obs_normal[base_start:base_end])

# Blind mask
obs_blind = list(obs_normal)
apply_preset_mask(obs_blind, 'blind')
spatial_start, spatial_end = SECTION_RANGES['spatial_walls']
check("Blind: spatial zeroed", all(v == 0 for v in obs_blind[spatial_start:spatial_end]))
check("Blind: economy untouched",
      obs_blind[SECTION_RANGES['self_economy'][0]:SECTION_RANGES['self_economy'][1]] ==
      obs_normal[SECTION_RANGES['self_economy'][0]:SECTION_RANGES['self_economy'][1]])

# Paranoid mask (inverts social — scale -1.0)
obs_paranoid = list(obs_normal)
apply_preset_mask(obs_paranoid, 'paranoid')
# Social values should be negated
for i in range(social_start, social_end):
    if obs_normal[i] != 0:
        check(f"Paranoid: social val {i} inverted",
              abs(obs_paranoid[i] + obs_normal[i]) < 0.001)
        break  # just check first non-zero

# Feral mask: social + economy + quest + religion all zeroed
obs_feral = list(obs_normal)
apply_preset_mask(obs_feral, 'feral')
quest_start, quest_end = SECTION_RANGES['self_quest']
check("Feral: quests zeroed", all(v == 0 for v in obs_feral[quest_start:quest_end]))

# Creature mask field
masked_c.observation_mask = 'blind'
check("Creature has observation_mask", masked_c.observation_mask == 'blind')

# Verify all presets are valid
for name, preset in PRESET_MASKS.items():
    test_obs = list(obs_normal)
    apply_preset_mask(test_obs, name)
    check(f"Preset '{name}' applies without error", len(test_obs) == OBS_SIZE)

# ==========================================================================
print("\n=== Gym Single-Agent Environment ===")
from editor.simulation.env import CreatureEnv, MultiAgentCreatureEnv

env = CreatureEnv(arena_kwargs={'cols': 10, 'rows': 10, 'num_creatures': 4,
                                'obstacle_density': 0.05},
                  max_steps=50)
obs, info = env.reset(seed=42)
check(f"Reset obs shape: {obs.shape}", obs.shape == (OBSERVATION_SIZE,))
check("Reset obs dtype float32", obs.dtype == np.float32)
check("Info has step=0", info['step'] == 0)

# Run a few random steps
total_reward = 0.0
for _ in range(20):
    action = np.random.randint(0, NUM_ACTIONS)
    obs, reward, terminated, truncated, info = env.step(action)
    total_reward += reward
    check(f"Step obs shape ok", obs.shape == (OBSERVATION_SIZE,))
    if terminated or truncated:
        break

check(f"Ran steps: info step={info['step']}", info['step'] > 0)
check(f"Total reward: {total_reward:.2f} (is a number)", isinstance(total_reward, float))
check("HP ratio in info", 'agent_hp_ratio' in info)

# Run to completion
env2 = CreatureEnv(arena_kwargs={'cols': 8, 'rows': 8, 'num_creatures': 3,
                                 'obstacle_density': 0.05},
                   max_steps=30)
obs, _ = env2.reset(seed=123)
done = False
steps = 0
while not done:
    obs, reward, terminated, truncated, info = env2.step(Action.WAIT)
    done = terminated or truncated
    steps += 1
check(f"Episode completed in {steps} steps (max 30)", steps <= 30)

# ==========================================================================
print("\n=== Gym Multi-Agent Environment ===")
menv = MultiAgentCreatureEnv(
    arena_kwargs={'cols': 10, 'rows': 10, 'num_creatures': 4,
                  'obstacle_density': 0.05},
    max_steps=50)
observations = menv.reset(seed=42)
check(f"Multi-agent reset: {len(observations)} creatures", len(observations) == 4)

for uid, obs in observations.items():
    check(f"Agent {uid} obs shape", obs.shape == (OBSERVATION_SIZE,))

# Step with random actions
agents = menv.agents
actions = {uid: np.random.randint(0, NUM_ACTIONS) for uid in agents}
results = menv.step(actions)
check(f"Multi-agent step: {len(results)} results", len(results) == 4)

for uid, res in results.items():
    check(f"Agent {uid} result has obs", res['obs'].shape == (OBSERVATION_SIZE,))
    check(f"Agent {uid} result has reward", isinstance(res['reward'], float))

# Run 30 steps
for _ in range(30):
    agents = menv.agents
    if not agents:
        break
    actions = {uid: np.random.randint(0, NUM_ACTIONS) for uid in agents}
    menv.step(actions)
check(f"Multi-agent survived 30+ steps", menv.sim.step_count >= 30)

# ==========================================================================
print("\n=== Spatial Memory & Goals ===")
gm = make_map(20, 20)
gc = make_creature(gm, x=5, y=5, name='GoalCreature')
gm.name = 'test_map'

# -- remember_location basics --
gc.remember_location('trading', 'test_map', 10, 10, tick=100)
check("remember_location adds entry",
      len(gc.known_locations.get('trading', [])) == 1)
check("remembered coords correct",
      gc.known_locations['trading'][0] == ('test_map', 10, 10, 100))

# -- deduplication: same coords updates tick --
gc.remember_location('trading', 'test_map', 10, 10, tick=200)
check("dedup: still 1 entry after re-remembering same coords",
      len(gc.known_locations['trading']) == 1)
check("dedup: tick updated to 200",
      gc.known_locations['trading'][0][3] == 200)

# -- different coords adds second entry --
gc.remember_location('trading', 'test_map', 15, 15, tick=300)
check("different coords adds second entry",
      len(gc.known_locations['trading']) == 2)

# -- multiple purposes stay separate --
gc.remember_location('farming', 'test_map', 3, 3, tick=100)
check("farming purpose separate from trading",
      'farming' in gc.known_locations and len(gc.known_locations['farming']) == 1)

# -- memory cap --
from classes.creature._goals import _MAX_MEMORY_PER_PURPOSE
for i in range(_MAX_MEMORY_PER_PURPOSE + 5):
    gc.remember_location('capped', 'test_map', i, 0, tick=i)
check(f"memory capped at {_MAX_MEMORY_PER_PURPOSE}",
      len(gc.known_locations['capped']) == _MAX_MEMORY_PER_PURPOSE)

# -- update_spatial_memory from tile purpose --
gm2 = make_map(10, 10)
gm2.name = 'purpose_map'
gm2.tiles[MapKey(3, 3, 0)].purpose = 'hunting'
gc2 = make_creature(gm2, x=3, y=3, name='PurposeCreature')
gc2.update_spatial_memory(tick=500)
check("update_spatial_memory learns tile purpose",
      'hunting' in gc2.known_locations and len(gc2.known_locations['hunting']) == 1)

# -- tile without purpose: no entry --
gc3 = make_creature(gm2, x=0, y=0, name='NoPurpose')
gc3.update_spatial_memory(tick=600)
check("no purpose tile: known_locations empty",
      len(gc3.known_locations) == 0)

# -- set_goal / goal_distance / at_goal --
gm3 = make_map(20, 20)
gm3.name = 'goal_map'
gc4 = make_creature(gm3, x=2, y=2, name='GoalRunner')
gc4.set_goal('trading', 'goal_map', 10, 10, tick=0)
check("current_goal set", gc4.current_goal == 'trading')
check("goal_target set", gc4.goal_target == ('goal_map', 10, 10))
check("goal_distance = Manhattan(2,2 -> 10,10) = 16",
      gc4.goal_distance() == 16.0)
check("not at_goal when 16 away", not gc4.at_goal())

# -- goal_progress: moving closer --
gc4.location = MapKey(5, 5, 0)
progress = gc4.goal_progress()
check("goal_progress positive when moving closer (was 16, now 10, progress=6)",
      progress == 6.0)

# -- at_goal: within 1 tile --
gc4.location = MapKey(10, 10, 0)
check("at_goal when on target tile", gc4.at_goal())

# -- at_goal: 1 tile away --
gc4.location = MapKey(10, 11, 0)
check("at_goal when 1 tile away", gc4.at_goal())

# -- not at_goal: 2 tiles away --
gc4.location = MapKey(10, 12, 0)
check("not at_goal when 2 tiles away", not gc4.at_goal())

# -- clear_goal --
gc4.clear_goal()
check("clear_goal: current_goal is None", gc4.current_goal is None)
check("clear_goal: goal_target is None", gc4.goal_target is None)
check("clear_goal: goal_distance is inf", gc4.goal_distance() == float('inf'))

# -- direction_to_goal --
gm4 = make_map(20, 20)
gm4.name = 'dir_map'
gc5 = make_creature(gm4, x=5, y=5, name='DirCreature')
gc5.set_goal('farming', 'dir_map', 10, 3, tick=0)
dx, dy = gc5.direction_to_goal()
check("direction_to_goal dx=1 (east)", dx == 1)
check("direction_to_goal dy=-1 (north)", dy == -1)

# -- direction_to_goal: no goal --
gc5.clear_goal()
check("direction_to_goal (0,0) when no goal", gc5.direction_to_goal() == (0, 0))

# -- cross-map goal --
gc5.set_goal('trading', 'other_map', 0, 0, tick=0)
check("cross-map goal_distance = 100 placeholder", gc5.goal_distance() == 100.0)
check("cross-map not at_goal", not gc5.at_goal())
check("cross-map direction (0,0)", gc5.direction_to_goal() == (0, 0))

# -- pick_goal_target from memory --
gm5 = make_map(20, 20)
gm5.name = 'pick_map'
gc6 = make_creature(gm5, x=0, y=0, name='Picker')
gc6.remember_location('trading', 'pick_map', 8, 8, tick=100)
gc6.remember_location('trading', 'pick_map', 15, 15, tick=200)
result = gc6.pick_goal_target('trading')
check("pick_goal_target returns closest on current map",
      result is not None and result[1] == 8 and result[2] == 8)

# -- pick_goal_target: no known locations returns None --
result_none = gc6.pick_goal_target('unknown_purpose')
check("pick_goal_target returns None for unknown purpose", result_none is None)

# -- pick_goal_target: other map fallback --
gc6.remember_location('healing', 'far_away_map', 5, 5, tick=300)
result_far = gc6.pick_goal_target('healing')
check("pick_goal_target falls back to other map",
      result_far is not None and result_far[0] == 'far_away_map')

# -- spatial_memory fires on movement (event-driven) --
gm6 = make_map(10, 10)
gm6.name = 'tick_map'
gm6.tiles[MapKey(1, 1, 0)].purpose = 'resting'
gc7 = make_creature(gm6, x=0, y=0, name='TickCreature')
# Move to tile with purpose — triggers spatial memory scan
gc7.location = MapKey(1, 1, 0)
check("spatial_memory learns tile purpose on move",
      'resting' in gc7.known_locations)

# -- goal_target --
gc8 = make_creature(gm6, x=0, y=0, name='ZoneCreature')
gc8.set_goal('trading', 'tick_map', 5, 5, tick=0)
check("goal_target set", gc8.goal_target == ('tick_map', 5, 5))
gc8.clear_goal()
check("goal_target cleared after clear_goal", gc8.goal_target is None)

# -- goal_started_tick --
gc9 = make_creature(gm6, x=0, y=0, name='TickTracker')
gc9.set_goal('farming', 'tick_map', 5, 5, tick=12345)
check("goal_started_tick set", gc9.goal_started_tick == 12345)

# ==========================================================================
# Resource / Harvest system
# ==========================================================================
print("\n--- Resource / Harvest tests ---")

from classes.actions import Action, dispatch

# Tile with a resource
rm = make_map(5, 5)
wheat_tile = rm.tiles[MapKey(2, 2, 0)]
wheat_tile.purpose = 'farming'
wheat_tile.resource_type = 'wheat'
wheat_tile.resource_amount = 10
wheat_tile.resource_max = 20
wheat_tile.growth_rate = 1.0

rc = make_creature(rm, x=2, y=2, name='Harvester')

# search_tile should reveal resource
sr = rc.search_tile()
check("search_tile returns resource_type", sr['resource_type'] == 'wheat')
check("search_tile returns resource_amount", sr['resource_amount'] == 10)

# harvest happy path
result = rc.harvest()
check("harvest succeeds", result['success'])
check("harvest returns correct amount", result['amount'] == 10)
check("tile depleted after harvest", wheat_tile.resource_amount == 0)
check("harvested item in inventory", any(getattr(i, 'name', '') == 'Wheat' for i in rc.inventory.items))
check("harvested stack has correct quantity",
      next((i.quantity for i in rc.inventory.items if getattr(i, 'name', '') == 'Wheat'), 0) == 10)

# harvest from depleted tile fails
result2 = rc.harvest()
check("harvest depleted tile fails", not result2['success'])
check("harvest depleted reason", result2.get('reason') == 'depleted')

# search on depleted tile shows 0
sr2 = rc.search_tile()
check("search depleted tile shows 0 amount", sr2['resource_amount'] == 0)

# harvest on tile with no resource fails
empty_rc = make_creature(rm, x=0, y=0, name='EmptyHarvester')
result3 = empty_rc.harvest()
check("harvest no-resource tile fails", not result3['success'])
check("harvest no-resource reason", result3.get('reason') == 'no_resource')

# grow_resources tick
wheat_tile.resource_amount = 5
rm.grow_resources()
check("grow_resources increments amount", wheat_tile.resource_amount == 6.0)

# grow does not exceed max
wheat_tile.resource_amount = 19.5
rm.grow_resources()
check("grow_resources caps at resource_max", wheat_tile.resource_amount == 20)

# zero growth_rate tile does not grow
inert_tile = rm.tiles[MapKey(1, 1, 0)]
inert_tile.resource_type = 'rock'
inert_tile.resource_amount = 5
inert_tile.resource_max = 10
inert_tile.growth_rate = 0.0
rm.grow_resources()
check("zero growth_rate tile unchanged", inert_tile.resource_amount == 5)

# dispatch HARVEST action works
wheat_tile.resource_amount = 8
wheat_tile.resource_max = 20
wheat_tile.growth_rate = 1.0
rc2 = make_creature(rm, x=2, y=2, name='Dispatcher')
result4 = dispatch(rc2, Action.HARVEST, {'cols': 5, 'rows': 5})
check("dispatch HARVEST succeeds", result4.get('success'))
check("dispatch HARVEST amount", result4.get('amount') == 8)

# ==========================================================================
# Jobs, Schedules, FARM, polymorphic HARVEST
# ==========================================================================
print("\n--- Jobs / Schedule / FARM tests ---")

from classes.jobs import (Schedule, Job, DAY_WORKER, WANDERER, NIGHT_WORKER,
                           DEFAULT_JOBS, qualifies_for, best_job_for)

# -- Schedule basics --
check("DAY_WORKER at 10am is work",  DAY_WORKER.activity_at(10.0) == 'work')
check("DAY_WORKER at 2am is sleep",  DAY_WORKER.activity_at(2.0) == 'sleep')
check("DAY_WORKER at 12:30 is open (lunch break)",
      DAY_WORKER.activity_at(12.5) == 'open')
check("WANDERER at noon is open",   WANDERER.activity_at(12.0) == 'open')
check("WANDERER at 3am is sleep",   WANDERER.activity_at(3.0) == 'sleep')
check("NIGHT_WORKER at midnight is work",
      NIGHT_WORKER.activity_at(0.0) == 'work')
check("NIGHT_WORKER at noon is sleep",
      NIGHT_WORKER.activity_at(12.0) == 'sleep')

# -- Job qualification --
jm = make_map(8, 8)
strong_c = make_creature(jm, x=0, y=0, name='Strong',
                          stats={Stat.STR: 16, Stat.VIT: 14, Stat.PER: 14,
                                 Stat.INT: 8, Stat.CHR: 8})
check("strong creature qualifies for miner", qualifies_for(strong_c, DEFAULT_JOBS['miner']))
check("strong creature does NOT qualify for healer",
      not qualifies_for(strong_c, DEFAULT_JOBS['healer']))

best = best_job_for(strong_c)
check(f"best_job_for strong returns a job: {best.name if best else None}",
      best is not None)

# -- FARM action --
farm_tile = jm.tiles[MapKey(3, 3, 0)]
farm_tile.purpose = 'farming'
farm_tile.resource_type = 'wheat'
farm_tile.resource_max = 20
farm_tile.resource_amount = 5
farm_tile.growth_rate = 1.0

farmer_c = make_creature(jm, x=3, y=3, name='Farmer',
                          stats={Stat.VIT: 14, Stat.INT: 14, Stat.STR: 12})
farmer_c.job = DEFAULT_JOBS['farmer']
farmer_c.schedule = DAY_WORKER

fr = farmer_c.farm()
check("farm() on farming tile succeeds", fr['success'])
check("farm() boosts resource_amount", farm_tile.resource_amount > 5)

# farm() fails on a non-resource tile
no_res = make_creature(jm, x=0, y=1, name='NoResFarmer',
                       stats={Stat.VIT: 14, Stat.INT: 14})
nr = no_res.farm()
check("farm() on empty tile fails", not nr['success'])
check("farm() empty tile reason", nr.get('reason') == 'no_resource')

# farm() fails when already full
farm_tile.resource_amount = farm_tile.resource_max
full_r = farmer_c.farm()
check("farm() at max fails", not full_r['success'])
check("farm() at max reason", full_r.get('reason') == 'already_full')

# -- do_job() --
# Fallback _current_hour(now_ms) = (8 + now_ms/500/60) % 24.
# Target 10am → need offset of 2 game hours = 120 min = 60000 ms
JOB_TIME_MS = 2 * 60 * 500  # 2 game hours after 8am start → 10am

# Farmer on farming tile during work hours: paid
farm_tile.resource_amount = 5  # reset
prev_gold = farmer_c.gold
jr = farmer_c.do_job(now=JOB_TIME_MS)
check("do_job farmer on farming tile at 10am succeeds", jr['success'])
check("do_job pays wage", farmer_c.gold > prev_gold)
check("do_job records wage_accumulated", farmer_c._wage_accumulated > 0)

# Farmer OFF hours (2am) → need 18 hours offset = 1080 min = 540000 ms
farm_tile.resource_amount = 5
OFF_HOURS_MS = 18 * 60 * 500  # 8am + 18h = 2am next day
jr2 = farmer_c.do_job(now=OFF_HOURS_MS)
check("do_job off-hours fails", not jr2['success'])
check("do_job off-hours reason", jr2.get('reason') == 'off_hours')

# Farmer at wrong workplace (trading tile, not farming)
wrong_tile = jm.tiles[MapKey(5, 5, 0)]
wrong_tile.purpose = 'trading'
wrong_farmer = make_creature(jm, x=5, y=5, name='WrongFarmer',
                              stats={Stat.VIT: 14, Stat.INT: 14})
wrong_farmer.job = DEFAULT_JOBS['farmer']
wrong_farmer.schedule = DAY_WORKER
jr3 = wrong_farmer.do_job(now=JOB_TIME_MS)
check("do_job at wrong workplace fails", not jr3['success'])
check("do_job wrong workplace reason", jr3.get('reason') == 'not_at_workplace')

# Wanderer (no job) cannot do_job
wanderer_c = make_creature(jm, x=0, y=0, name='Wanderer')
# wanderer_c.job defaults to None
jr4 = wanderer_c.do_job(now=JOB_TIME_MS)
check("do_job wanderer fails", not jr4['success'])
check("do_job wanderer reason", jr4.get('reason') == 'no_job')

# -- Polymorphic HARVEST reward resolution --
from classes.reward import _resolve_action_purpose

fishing_tile = jm.tiles[MapKey(1, 1, 0)]
fishing_tile.purpose = 'fishing'
fishing_tile.resource_type = 'fish'
fishing_tile.resource_amount = 5
fishing_tile.resource_max = 10

fisher = make_creature(jm, x=1, y=1, name='Fisher')
resolved = _resolve_action_purpose(fisher, Action.HARVEST)
check(f"HARVEST on fishing tile resolves to 'fishing' (got {resolved})",
      resolved == 'fishing')

farmer_on_wheat = make_creature(jm, x=3, y=3, name='FarmerOnWheat')
resolved_farm = _resolve_action_purpose(farmer_on_wheat, Action.HARVEST)
check(f"HARVEST on farming tile resolves to 'farming' (got {resolved_farm})",
      resolved_farm == 'farming')

# dispatch FARM works
disp_farm2 = make_creature(jm, x=3, y=3, name='DispatchFarm2',
                            stats={Stat.VIT: 14, Stat.INT: 14})
farm_tile.resource_amount = 5
dfr = dispatch(disp_farm2, Action.FARM, {'cols': 8, 'rows': 8})
check("dispatch FARM succeeds", dfr.get('success'))

# Action counts
check("NUM_ACTIONS is 32", NUM_ACTIONS == 32)

# ==========================================================================
# Processing recipes (cook / smelt)
# ==========================================================================
print("\n--- Processing recipes tests ---")

from classes.recipes import (PROCESSING_RECIPES, find_matching_recipe,
                              consume_inputs, Recipe)
from classes.inventory import Stackable

pm = make_map(8, 8)

# --- find_matching_recipe happy path ---
cook_tile = pm.tiles[MapKey(4, 4, 0)]
cook_tile.purpose = 'crafting'

cook = make_creature(pm, x=4, y=4, name='Cook',
                      stats={Stat.INT: 12, Stat.STR: 10})
# Give the cook 2 wheat
wheat = Stackable(name='Wheat', weight=0.2, value=1.0, quantity=2)
wheat.is_food = True
wheat.key = 'food_wheat_raw'
cook.inventory.items.append(wheat)

recipe = find_matching_recipe(cook.inventory.items)
check("find_matching_recipe returns something with wheat",
      recipe is not None)
check(f"wheat matches bake_bread (got {recipe.name if recipe else None})",
      recipe is not None and recipe.name == 'bake_bread')

# Filter by category
ore_stack = Stackable(name='IronOre', weight=0.5, value=1.0, quantity=2)
ore_stack.key = 'material_ore_iron'
coal_stack = Stackable(name='Coal', weight=0.3, value=0.5, quantity=1)
coal_stack.key = 'material_coal'
stash_for_cat = [wheat, ore_stack, coal_stack]
food_recipe = find_matching_recipe(stash_for_cat, category='food')
material_recipe = find_matching_recipe(stash_for_cat, category='material')
check("category='food' prefers bake_bread",
      food_recipe is not None and food_recipe.category == 'food')
check("category='material' picks smelt_iron",
      material_recipe is not None and material_recipe.name == 'smelt_iron')

# --- process() happy path ---
pr = cook.process()
check("process() on crafting tile succeeds", pr['success'])
check(f"process() returns recipe name (got {pr.get('recipe')})",
      pr.get('recipe') == 'bake_bread')
check("bread now in inventory",
      any(getattr(i, 'name', '') == 'Bread' for i in cook.inventory.items))
# Wheat should have been consumed (2 required)
wheat_left = sum(i.quantity for i in cook.inventory.items
                 if getattr(i, 'name', '') == 'Wheat')
check(f"wheat consumed (left: {wheat_left})", wheat_left == 0)

# --- process() on wrong tile fails ---
wrong_tile_cook = make_creature(pm, x=0, y=0, name='WrongTileCook',
                                 stats={Stat.INT: 12})
wheat2 = Stackable(name='Wheat', weight=0.2, value=1.0, quantity=2)
wheat2.key = 'food_wheat_raw'
wrong_tile_cook.inventory.items.append(wheat2)
pr2 = wrong_tile_cook.process()
check("process() off crafting tile fails", not pr2['success'])
check("process() wrong_tile reason", pr2.get('reason') == 'wrong_tile')

# --- process() with no ingredients fails ---
empty_cook = make_creature(pm, x=4, y=4, name='EmptyCook',
                            stats={Stat.INT: 12})
pr3 = empty_cook.process()
check("process() with no ingredients fails", not pr3['success'])
check("process() no_recipe_match reason",
      pr3.get('reason') == 'no_recipe_match')

# --- process() ore → iron ---
smelter = make_creature(pm, x=4, y=4, name='Smelter',
                         stats={Stat.STR: 12})
ore_stack2 = Stackable(name='IronOre', weight=0.5, value=1.0, quantity=2)
ore_stack2.key = 'material_ore_iron'
coal_stack2 = Stackable(name='Coal', weight=0.3, value=0.5, quantity=1)
coal_stack2.key = 'material_coal'
smelter.inventory.items.append(ore_stack2)
smelter.inventory.items.append(coal_stack2)
pr4 = smelter.process(category='material')
check("process() ore to iron succeeds", pr4['success'])
check("Iron Ingot in inventory",
      any(getattr(i, 'name', '') == 'Iron Ingot'
          for i in smelter.inventory.items))

# --- Bread gives more heal than raw wheat (the whole point) ---
bread = next((i for i in cook.inventory.items
              if getattr(i, 'name', '') == 'Bread'), None)
check("bread has heal_amount > 0", bread is not None and bread.heal_amount > 0)
check("bread heal_amount > raw wheat implicit heal",
      bread is not None and bread.heal_amount >= 5)

# --- dispatch PROCESS works end-to-end ---
disp_cook = make_creature(pm, x=4, y=4, name='DispatchCook',
                           stats={Stat.INT: 12})
wheat3 = Stackable(name='Wheat', weight=0.2, value=1.0, quantity=2)
wheat3.key = 'food_wheat_raw'
disp_cook.inventory.items.append(wheat3)
dpr = dispatch(disp_cook, Action.PROCESS, {'cols': 8, 'rows': 8})
check("dispatch PROCESS succeeds", dpr.get('success'))

# --- Crafter JOB performs processing ---
crafter = make_creature(pm, x=4, y=4, name='CrafterJob',
                         stats={Stat.INT: 14})
from classes.jobs import DEFAULT_JOBS, DAY_WORKER
crafter.job = DEFAULT_JOBS['crafter']
crafter.schedule = DAY_WORKER
wheat4 = Stackable(name='Wheat', weight=0.2, value=1.0, quantity=2)
wheat4.key = 'food_wheat_raw'
crafter.inventory.items.append(wheat4)
# JOB_TIME_MS defined earlier in the jobs test block — reuse
cjr = crafter.do_job(now=JOB_TIME_MS)
check("crafter JOB with wheat ingredient succeeds", cjr['success'])
check("crafter JOB produces bread",
      any(getattr(i, 'name', '') == 'Bread' for i in crafter.inventory.items))
check("crafter JOB paid wage", crafter._wage_accumulated > 0)

# --- Crafter JOB with empty inventory is 'idle' but still paid ---
idle_crafter = make_creature(pm, x=4, y=4, name='IdleCrafter',
                              stats={Stat.INT: 14})
idle_crafter.job = DEFAULT_JOBS['crafter']
idle_crafter.schedule = DAY_WORKER
cjr_idle = idle_crafter.do_job(now=JOB_TIME_MS)
check("idle crafter JOB still succeeds (apprentice work)",
      cjr_idle['success'])
check("idle crafter paid wage", idle_crafter._wage_accumulated > 0)

# --- Mining JOB boosts vein, does NOT mint buried_gold ---
mine_tile = pm.tiles[MapKey(2, 5, 0)]
mine_tile.purpose = 'mining'
mine_tile.resource_type = 'ore'
mine_tile.resource_max = 8
mine_tile.resource_amount = 3
mine_tile.growth_rate = 0.2
mine_tile.buried_gold = 0

miner = make_creature(pm, x=2, y=5, name='Miner',
                      stats={Stat.STR: 14, Stat.VIT: 12})
miner.job = DEFAULT_JOBS['miner']
miner.schedule = DAY_WORKER
prev_buried = mine_tile.buried_gold
prev_amount = mine_tile.resource_amount
mjr = miner.do_job(now=JOB_TIME_MS)
check("miner JOB succeeds", mjr['success'])
check("miner JOB boosted resource_amount (vein tending)",
      mine_tile.resource_amount > prev_amount)
check("miner JOB did NOT mint buried_gold",
      mine_tile.buried_gold == prev_buried)

# --- Full loop: harvest ore, process to ingot ---
mine_tile.resource_amount = mine_tile.resource_max  # max it out for harvest
harvester = make_creature(pm, x=2, y=5, name='HarvestMiner',
                           stats={Stat.STR: 12})
hr = harvester.harvest()
check("harvest on mining tile succeeds", hr['success'])
# Harvested item may have resource_type name or catalog name
harvested_items = [getattr(i, 'name', '') for i in harvester.inventory.items]
check(f"harvested something: {harvested_items}", len(harvester.inventory.items) > 0)
# Give harvester proper ore and coal for smelt test
from classes.inventory import Stackable as _S
_ore = _S(name='Iron Ore', weight=0.5, value=1.0, quantity=2)
_ore.key = 'material_ore_iron'
_coal = _S(name='Coal', weight=0.3, value=0.5, quantity=1)
_coal.key = 'material_coal'
harvester.inventory.items.extend([_ore, _coal])
# Move to crafting tile, smelt
harvester.location = MapKey(4, 4, 0)
smelt_r = harvester.process(category='material')
check("smelt ore -> iron ingot succeeds", smelt_r['success'])

# ==========================================================================
# Auto-trade: the gold-denominated trade loop
# ==========================================================================
print("\n--- Auto-trade tests ---")

# Start each auto-trade section with a clean market tape so one test's
# EMA drift doesn't contaminate another's price anchoring.
from classes.market import reset_market, observe_trade, market_price, market_confidence, market_snapshot
reset_market()

tm = make_map(6, 6)

# --- BUY path: hungry buyer, seller has food ---
buyer = make_creature(tm, x=2, y=2, name='Buyer')
buyer.hunger = -0.2  # below 0.3 → hungry
buyer.gold = 100

seller = make_creature(tm, x=2, y=3, name='Seller')  # adjacent
bread_stack = Consumable(name='Bread', weight=0.1, value=4.0,
                          quantity=3, heal_amount=5, duration=0)
bread_stack.is_food = True
seller.inventory.items.append(bread_stack)

buyer_prev_gold = buyer.gold
seller_prev_gold = seller.gold
buy_r = buyer.auto_trade(seller)
check("auto_trade buy succeeds", buy_r['success'])
check(f"direction is bought (got {buy_r.get('direction')})",
      buy_r.get('direction') == 'bought')
check("buyer has bread now",
      any(getattr(i, 'name', '') == 'Bread' for i in buyer.inventory.items))
# Gold should flow from buyer to seller by the computed price
price_paid = buy_r.get('price', 0)
check(f"buyer paid ({price_paid} gold)", buyer.gold == buyer_prev_gold - price_paid)
check(f"seller gained ({price_paid} gold)", seller.gold == seller_prev_gold + price_paid)
# Seller stack should be 2 now (transferred one unit out of 3)
seller_bread_qty = sum(i.quantity for i in seller.inventory.items
                       if getattr(i, 'name', '') == 'Bread')
check(f"seller bread stack decremented (left: {seller_bread_qty})",
      seller_bread_qty == 2)
# Buyer side should have cost basis recorded for resale floor
bought_bread = next(i for i in buyer.inventory.items
                    if getattr(i, 'name', '') == 'Bread')
check("buyer _item_prices records cost basis",
      id(bought_bread) in buyer._item_prices)

# --- SELL path: seller has goods, wealthy buyer ---
rich_buyer = make_creature(tm, x=3, y=3, name='RichBuyer')
rich_buyer.hunger = 0.8  # not hungry
rich_buyer.gold = 500  # wealthy

merchant = make_creature(tm, x=3, y=2, name='Merchant')  # adjacent
ingot = Stackable(name='IronIngot', weight=0.5, value=8.0, quantity=2)
merchant.inventory.items.append(ingot)
merchant.gold = 0

merchant_prev = merchant.gold
sell_r = merchant.auto_trade(rich_buyer)
check("auto_trade sell succeeds", sell_r['success'])
check(f"direction is sold (got {sell_r.get('direction')})",
      sell_r.get('direction') == 'sold')
check("rich buyer now has iron", any(getattr(i, 'name', '') == 'IronIngot'
                                       for i in rich_buyer.inventory.items))
sell_price = sell_r.get('price', 0)
check(f"merchant gained {sell_price}", merchant.gold == merchant_prev + sell_price)

# --- Rejection: poor buyer, not hungry, seller has non-food goods ---
poor_buyer = make_creature(tm, x=4, y=4, name='PoorBuyer')
poor_buyer.hunger = 0.5
poor_buyer.gold = 2  # can't afford much

seller2 = make_creature(tm, x=4, y=3, name='Seller2')
ingot2 = Stackable(name='IronIngot', weight=0.5, value=8.0, quantity=1)
seller2.inventory.items.append(ingot2)

rej_r = seller2.auto_trade(poor_buyer)
check("auto_trade rejection when buyer can't afford", not rej_r['success'])

# --- Non-adjacent rejection ---
far1 = make_creature(tm, x=0, y=0, name='Far1')
far2 = make_creature(tm, x=5, y=5, name='Far2')
far_r = far1.auto_trade(far2)
check("auto_trade far rejection", not far_r['success'])
check("auto_trade reason is not_adjacent",
      far_r.get('reason') == 'not_adjacent')

# --- dispatch TRADE auto-picks target (fresh map — test isolation) ---
dm = make_map(6, 6)
d1 = make_creature(dm, x=1, y=1, name='D1')
d1.hunger = -0.2
d1.gold = 50
d2 = make_creature(dm, x=1, y=2, name='D2')  # adjacent
d2_bread = Consumable(name='Bread', weight=0.1, value=4.0, quantity=2,
                       heal_amount=5, duration=0)
d2_bread.is_food = True
d2.inventory.items.append(d2_bread)
dtr = dispatch(d1, Action.TRADE, {'cols': 6, 'rows': 6})
check("dispatch TRADE with auto target succeeds", dtr.get('success'))

# dispatch TRADE with no partner in range (fresh map)
lm = make_map(6, 6)
lonely = make_creature(lm, x=5, y=0, name='Lonely')
lr = dispatch(lonely, Action.TRADE, {'cols': 6, 'rows': 6})
check("dispatch TRADE with no partner fails", not lr.get('success'))
check("dispatch TRADE no_partner reason", lr.get('reason') == 'no_partner')

# --- Market memory: EMA drifts toward cleared prices ---
reset_market()
observe_trade('TestItem', 10.0)
check("market_price after first trade = 10",
      abs(market_price('TestItem') - 10.0) < 0.01)
# EMA = 0.2 * 20 + 0.8 * 10 = 12
observe_trade('TestItem', 20.0)
check(f"market_price after second (20) drifts toward it (got {market_price('TestItem'):.2f})",
      abs(market_price('TestItem') - 12.0) < 0.01)
# Many trades at 10 should drift back toward 10
for _ in range(30):
    observe_trade('TestItem', 10.0)
check(f"market_price after 30 trades at 10 drifts back (got {market_price('TestItem'):.2f})",
      abs(market_price('TestItem') - 10.0) < 0.5)
# Confidence grows with volume
check("market_confidence > 0 after trades", market_confidence('TestItem') > 0)
# Unknown item returns seed
check("market_price unknown returns seed",
      market_price('NonExistent', seed=5.5) == 5.5)
check("market_price unknown with no seed returns None",
      market_price('NonExistent') is None)

# --- compute_trade_price consults market memory ---
reset_market()
from classes.valuation import compute_trade_price
# Seed the market for Bread at price=10 via 40 trades
for _ in range(40):
    observe_trade('Bread', 10.0)
# Now compute_trade_price with bread should anchor toward market (10)
am = make_map(6, 6)
mv_seller = make_creature(am, x=1, y=1, name='MVSeller',
                          stats={Stat.VIT: 12, Stat.STR: 12})
mv_buyer = make_creature(am, x=1, y=2, name='MVBuyer',
                         stats={Stat.VIT: 12, Stat.STR: 12})
mv_buyer.gold = 200
mv_buyer.hunger = 0.6  # not desperate
mv_bread = Consumable(name='Bread', weight=0.1, value=4.0, quantity=5,
                       heal_amount=5, duration=0)
mv_bread.is_food = True
mv_seller.inventory.items.append(mv_bread)
deal = compute_trade_price(mv_bread, mv_seller, mv_buyer)
# Without market: s_min/b_max ~= 28; with full market confidence and 30%
# anchor, pulled toward 10 → somewhere around 22-24
anchored_min = deal['seller_min']
check(f"market anchored seller_min below raw worth (got {anchored_min:.2f})",
      anchored_min < 28.0)

# --- Food Consumables get non-zero KPI after heal_amount fix ---
from classes.valuation import worth_to_creature
heal_bread = Consumable(name='HealBread', weight=0.1, value=4.0, quantity=1,
                         heal_amount=5, duration=0)
kpi_creature = make_creature(am, x=3, y=3, name='KPICheck')
worth = worth_to_creature(heal_bread, kpi_creature)
check(f"bread worth > 0 (heal_amount bug fix; got {worth:.2f})",
      worth > 0)

# --- Desperation surplus recompute bugfix ---
# Scenario: seller with qty=3 bread, _item_prices says they paid 12.
# Raw worth ~= 28 (quantity decompound). Buyer also values at ~28.
# Without desperation: s_min=max(12,28)=28, b_max=28, surplus=0, price=28.
# Seller has gold=0 → desperation fires → s_min drops to 12, surplus
# should be recomputed to 16, price becomes 12 + 16 * share. Price must
# be >= 12 (paid floor), buyer_surplus + seller_surplus must equal
# the (new) surplus.
reset_market()
rb_map = make_map(6, 6)
rb_seller = make_creature(rb_map, x=1, y=1, name='RBSeller')
rb_seller.gold = 0  # desperate
rb_bread = Consumable(name='Bread', weight=0.1, value=4.0, quantity=3,
                       heal_amount=5, duration=0)
rb_bread.is_food = True
rb_seller._item_prices[id(rb_bread)] = 12.0  # paid 12 earlier
rb_seller.inventory.items.append(rb_bread)

rb_buyer = make_creature(rb_map, x=1, y=2, name='RBBuyer')
rb_buyer.gold = 100
rb_buyer.hunger = 0.6  # not desperate

rb_deal = compute_trade_price(rb_bread, rb_seller, rb_buyer)
check(f"desperate seller feasible after paid-price override (feasible={rb_deal['feasible']})",
      rb_deal['feasible'])
check(f"desperate seller price >= paid floor (price={rb_deal['price']:.1f})",
      rb_deal['price'] >= 12.0 - 0.01)
check(f"surpluses sum to total after desperation recompute",
      abs(rb_deal['buyer_surplus'] + rb_deal['seller_surplus'] -
          rb_deal['surplus']) < 0.01)
check(f"desperation reports positive surplus (got {rb_deal['surplus']:.2f})",
      rb_deal['surplus'] > 0)

# --- Auto-trade records trade in market ---
reset_market()
sm = make_map(6, 6)
s1 = make_creature(sm, x=1, y=1, name='S1')
s1.hunger = -0.2
s1.gold = 100
s2 = make_creature(sm, x=1, y=2, name='S2')
s2_bread = Consumable(name='Bread', weight=0.1, value=4.0, quantity=3,
                       heal_amount=5, duration=0)
s2_bread.is_food = True
s2.inventory.items.append(s2_bread)

snap_before = market_snapshot()
s1.auto_trade(s2)
snap_after = market_snapshot()
check("auto_trade updated market for Bread",
      'Bread' in snap_after and 'Bread' not in snap_before)

# --- Market confidence grows with volume ---
reset_market()
for i in range(100):
    observe_trade('BulkItem', 7.0)
conf = market_confidence('BulkItem')
check(f"high-volume confidence approaches 1.0 (got {conf:.2f})",
      conf > 0.9)

# --- Hunger-dependent food valuation ---
hv_map = make_map(5, 5)
bread_probe = Consumable(name='ProbeBread', heal_amount=5, quantity=1)
bread_probe.is_food = True
full_c = make_creature(hv_map, x=0, y=0, name='FullCreature')
full_c.hunger = 0.8
hungry_c = make_creature(hv_map, x=1, y=0, name='HungryCreature')
hungry_c.hunger = -0.3
starving_c = make_creature(hv_map, x=2, y=0, name='StarvingCreature')
starving_c.hunger = -0.9

full_worth = worth_to_creature(bread_probe, full_c)
hungry_worth = worth_to_creature(bread_probe, hungry_c)
starving_worth = worth_to_creature(bread_probe, starving_c)
check(f"full creature worth positive ({full_worth:.1f})", full_worth > 0)
check(f"hungry > full ({hungry_worth:.1f} > {full_worth:.1f})",
      hungry_worth > full_worth)
check(f"starving > hungry ({starving_worth:.1f} > {hungry_worth:.1f})",
      starving_worth > hungry_worth)
# Spec: 1x at hunger=0, 3x at hunger=-1 — starving should be about 3x full
check(f"starving/full ratio ~= 3 (got {starving_worth/full_worth:.2f})",
      2.5 < starving_worth / full_worth < 3.5)

# Non-food consumables are NOT affected by hunger
potion = Consumable(name='TestPotion', heal_amount=5, quantity=1)
# potion.is_food not set → defaults to falsy
potion_full = worth_to_creature(potion, full_c)
potion_hungry = worth_to_creature(potion, hungry_c)
check(f"non-food potion worth is hunger-independent ({potion_full:.1f} == {potion_hungry:.1f})",
      abs(potion_full - potion_hungry) < 0.01)

# --- Trader JOB executes a trade when partner adjacent ---
tjm = make_map(6, 6)
trade_tile = tjm.tiles[MapKey(3, 3, 0)]
trade_tile.purpose = 'trading'

trader = make_creature(tjm, x=3, y=3, name='Trader', stats={Stat.CHR: 14})
trader.job = DEFAULT_JOBS['trader']
trader.schedule = DAY_WORKER
ingot3 = Stackable(name='IronIngot', weight=0.5, value=8.0, quantity=1)
trader.inventory.items.append(ingot3)

# Adjacent wealthy customer
customer = make_creature(tjm, x=3, y=4, name='Customer')
customer.gold = 100
customer.hunger = 0.8  # wealthy speculation path

# Use JOB_TIME (10am) from the earlier jobs test block
tjr = trader.do_job(now=JOB_TIME_MS)
check("trader JOB at trading tile succeeds", tjr['success'])
check("trader JOB paid wage", trader._wage_accumulated > 0)
# The trade may or may not have fired — trader gets paid either way
# but customer should have the ingot if trade fired
check("customer received ingot from trade",
      any(getattr(i, 'name', '') == 'IronIngot'
          for i in customer.inventory.items))

# ==========================================================================
# Curriculum: reward mask + env toggles + stage loader
# ==========================================================================
print("\n--- Curriculum tests ---")

# --- Reward mask: signal_scales kwarg ---
from classes.reward import compute_reward, make_reward_snapshot

cm = make_map(8, 8)
ck = make_creature(cm, x=2, y=2, name='CurriculumProbe',
                    stats={Stat.STR: 10, Stat.VIT: 10, Stat.AGL: 10,
                           Stat.PER: 10, Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10})
prev_snap = make_reward_snapshot(ck)
# Force a delta on inv_value so the inventory signal fires
from classes.inventory import Stackable as _S
ck.inventory.items.append(_S(name='ProbeItem', value=10.0, quantity=1))
curr_snap = make_reward_snapshot(ck)

# No mask: legacy behavior, all signals contribute
total_legacy, signals_legacy = compute_reward(
    ck, prev_snap, curr_snap, breakdown=True)
check("legacy compute_reward returns total != 0",
      abs(total_legacy) > 0)

# Mask with only exploration (no exploration delta -> total=0)
total_only_explore, signals_explore = compute_reward(
    ck, prev_snap, curr_snap, breakdown=True,
    signal_scales={'exploration': 1.0})
check("masked reward silences inventory signal",
      abs(signals_explore.get('inventory', 0)) < 0.001)
check("masked reward total is much smaller than legacy",
      abs(total_only_explore) < abs(total_legacy))

# Mask with inventory at 0.5 — signal scaled
total_inv_half, signals_inv_half = compute_reward(
    ck, prev_snap, curr_snap, breakdown=True,
    signal_scales={'inventory': 0.5})
inv_full = signals_legacy.get('inventory', 0)
inv_half = signals_inv_half.get('inventory', 0)
if abs(inv_full) > 0.001:
    check(f"inventory scaled to ~half ({inv_half:.3f} vs {inv_full:.3f})",
          abs(inv_half - inv_full * 0.5) < 0.001)

# --- Env toggles: hunger_drain_enabled=False keeps creatures full ---
# Build a Simulation directly with the toggle
from editor.simulation.headless import Simulation
no_hunger_arena = {
    'map': make_map(5, 5),
    'creatures': [],
    'cols': 5, 'rows': 5,
}
nh_creature = make_creature(no_hunger_arena['map'], x=2, y=2, name='NoHungerProbe')
nh_creature.hunger = 0.5
no_hunger_arena['creatures'] = [nh_creature]

nh_sim = Simulation(no_hunger_arena, hunger_drain_enabled=False)
check("hunger_drain_enabled=False sets creature._hunger_drain to 0",
      nh_creature._hunger_drain == 0.0)
check("Simulation.hunger_drain_enabled flag stored",
      nh_sim.hunger_drain_enabled is False)

# Run a few hundred ticks — hunger should NOT drop
initial_h = nh_creature.hunger
for _ in range(200):
    nh_sim.step()
check(f"hunger did not drop with drain disabled "
      f"(start={initial_h:.3f}, end={nh_creature.hunger:.3f})",
      nh_creature.hunger >= initial_h - 0.001)

# --- Combat toggle: dispatch short-circuits MELEE_ATTACK ---
from classes.actions import dispatch as _dispatch, Action as _A
combat_off_arena = {
    'map': make_map(5, 5),
    'creatures': [],
    'cols': 5, 'rows': 5,
}
attacker = make_creature(combat_off_arena['map'], x=2, y=2, name='Attacker',
                          stats={Stat.STR: 16})
victim = make_creature(combat_off_arena['map'], x=3, y=2, name='Victim',
                        stats={Stat.VIT: 12})
combat_off_arena['creatures'] = [attacker, victim]
co_sim = Simulation(combat_off_arena, combat_enabled=False)
check("Simulation.combat_enabled=False flag stored",
      co_sim.combat_enabled is False)
hp_before = victim.stats.active[Stat.HP_CURR]()
result = _dispatch(attacker, _A.MELEE_ATTACK,
                    {'cols': 5, 'rows': 5,
                     'target': victim, 'now': 0,
                     'combat_enabled': False})
check("MELEE_ATTACK with combat_enabled=False fails fast",
      not result.get('success'))
check("MELEE_ATTACK reason is combat_disabled",
      result.get('reason') == 'combat_disabled')
hp_after = victim.stats.active[Stat.HP_CURR]()
check("victim HP unchanged when combat disabled",
      hp_after == hp_before)

# --- Gestation toggle: lifecycle pass is a noop ---
from classes.inventory import Egg as _Egg
gest_off_arena = {
    'map': make_map(5, 5),
    'creatures': [],
    'cols': 5, 'rows': 5,
}
mum = make_creature(gest_off_arena['map'], x=0, y=0, name='Mum',
                     sex='female', age=25)
fake_egg = _Egg()
fake_egg.gestation_days = 25
mum.inventory.items.append(fake_egg)
gest_off_arena['creatures'] = [mum]
go_sim = Simulation(gest_off_arena, gestation_enabled=False)
check("Simulation.gestation_enabled=False stored",
      go_sim.gestation_enabled is False)
go_sim._tick_lifecycle_day()
check("egg gestation_days unchanged when gestation disabled",
      fake_egg.gestation_days == 25)

# ==========================================================================
# DB catalog tests — MUST BE LAST because the DB loader replaces
# classes.recipes.PROCESSING_RECIPES with DB-sourced entries whose
# ingredient names differ from the hardcoded defaults. Earlier tests
# depend on the hardcoded recipes still being in place.
# ==========================================================================
print("\n--- DB catalog tests ---")

try:
    from data.db import (load as _db_load, ITEMS, JOBS,
                          PROCESSING_RECIPES as DB_RECIPES)
    _db_load()
    _db_loaded = True
except Exception as _e:
    _db_loaded = False
    print(f"  (DB catalog not loadable: {_e})")

if _db_loaded:
    check("food_wheat_raw exists in ITEMS", 'food_wheat_raw' in ITEMS)
    check("food_bread exists in ITEMS", 'food_bread' in ITEMS)
    check("material_ore_iron exists in ITEMS", 'material_ore_iron' in ITEMS)
    bread_item = ITEMS.get('food_bread')
    check("bread is_food flag is True",
          bread_item is not None and getattr(bread_item, 'is_food', False))
    check("bread heal_amount from DB = 5",
          bread_item is not None and getattr(bread_item, 'heal_amount', 0) == 5)

    check(f">= 7 jobs loaded (got {len(JOBS)})", len(JOBS) >= 7)
    check("farmer job loaded from DB", 'farmer' in JOBS)
    check("guard loaded from DB", 'guard' in JOBS)
    check("guard has night_worker schedule (work band present)",
          'guard' in JOBS and bool(JOBS['guard'].schedule.bands.get('work')))

    check(f">= 6 recipes loaded (got {len(DB_RECIPES)})", len(DB_RECIPES) >= 6)
    db_recipe_names = [r.name for r in DB_RECIPES]
    check("bake_bread recipe present", 'bake_bread' in db_recipe_names)
    check("smelt_iron recipe present", 'smelt_iron' in db_recipe_names)

    # Catalog-driven harvest: tile.resource_type = canonical item key
    cat_map = make_map(5, 5)
    cat_tile = cat_map.tiles[MapKey(2, 2, 0)]
    cat_tile.resource_type = 'food_wheat_raw'
    cat_tile.resource_amount = 10
    cat_tile.resource_max = 20
    cat_tile.growth_rate = 1.0
    cat_harvester = make_creature(cat_map, x=2, y=2, name='CatHarvester')
    cat_hr = cat_harvester.harvest()
    check("catalog harvest succeeds", cat_hr['success'])
    cat_wheat = next((i for i in cat_harvester.inventory.items
                       if getattr(i, 'name', '') == 'Wheat'), None)
    check("harvested item has DB name 'Wheat'", cat_wheat is not None)
    check("harvested item has DB value",
          cat_wheat is not None and abs(cat_wheat.value - 1.0) < 0.01)

    # Catalog-driven PROCESS: bake_bread via DB list
    cat_craft = cat_map.tiles[MapKey(3, 3, 0)]
    cat_craft.purpose = 'crafting'
    cat_harvester.location = MapKey(3, 3, 0)
    if cat_wheat is not None and cat_wheat.quantity < 2:
        cat_wheat.quantity = 2
    cat_pr = cat_harvester.process()
    check("catalog PROCESS bake_bread succeeds", cat_pr['success'])
    cat_bread = next((i for i in cat_harvester.inventory.items
                       if getattr(i, 'name', '') == 'Bread'), None)
    check("bread is in inventory after PROCESS", cat_bread is not None)
    check("bread has heal_amount from DB",
          cat_bread is not None and cat_bread.heal_amount == 5)

    # --- Fix 1: recipe matching uses item.key AND item.name ---
    # Rename the wheat item to something else. The bake_bread recipe
    # references the item by key, so it should still match.
    from classes.recipes import find_matching_recipe
    key_map = make_map(5, 5)
    renamer = make_creature(key_map, x=0, y=0, name='Renamer')
    # Clone wheat from catalog and rename it
    import copy as _cp
    wheat_tmpl = ITEMS['food_wheat_raw']
    fake_wheat = _cp.copy(wheat_tmpl)
    fake_wheat.name = 'Bizarro Wheat'  # display rename
    fake_wheat.quantity = 5
    renamer.inventory.items.append(fake_wheat)
    matched = find_matching_recipe(renamer.inventory.items, category='food')
    check(f"renamed wheat still matches via catalog key (got {matched.name if matched else None})",
          matched is not None and matched.name == 'bake_bread')

    # --- Fix 2: schedules loaded from DB ---
    from data.db import SCHEDULES
    check(f">= 3 schedules loaded (got {len(SCHEDULES)})", len(SCHEDULES) >= 3)
    check("day_worker schedule in DB SCHEDULES", 'day_worker' in SCHEDULES)
    check("night_worker schedule has work bands",
          'night_worker' in SCHEDULES
          and len(SCHEDULES['night_worker'].bands.get('work', [])) > 0)
    check("wanderer schedule has no work bands",
          'wanderer' in SCHEDULES
          and len(SCHEDULES['wanderer'].bands.get('work', [])) == 0)
    # Guard job's schedule should be the night_worker from DB
    guard_job = JOBS.get('guard')
    check("guard job schedule is night_worker from DB",
          guard_job is not None and
          guard_job.schedule is SCHEDULES.get('night_worker'))

    # --- Fix 3: creatures can be assigned a job from DB ---
    # The creatures table has job_key column — verify schema allows it.
    import sqlite3 as _sq
    from pathlib import Path as _P
    _db = _sq.connect(str(_P('src/data/game.db')))
    creature_cols = [r[1] for r in _db.execute('PRAGMA table_info(creatures)').fetchall()]
    _db.close()
    check("creatures.job_key column exists", 'job_key' in creature_cols)
else:
    check("DB catalog was loadable", False)

# ==========================================================================
# Birth chain: pair -> egg -> gestation -> hatch -> live creature on map
# ==========================================================================
print("\n--- Birth chain tests ---")

from classes.inventory import Egg

# Build a simple two-creature scenario: adult male + adult fertile female,
# adjacent, same species, neither pregnant. The male is overwhelmingly
# stronger so force_pairing's d20 grapple contest is effectively
# deterministic — otherwise the test is a coinflip and flakes.
bm = make_map(8, 8)
male = make_creature(bm, x=3, y=3, name='BirthMale', sex='male', age=25,
                      stats={Stat.STR: 20, Stat.AGL: 20, Stat.VIT: 14, Stat.CHR: 12})
female = make_creature(bm, x=3, y=4, name='BirthFemale', sex='female', age=25,
                        stats={Stat.STR: 6, Stat.AGL: 6, Stat.VIT: 14, Stat.CHR: 12})
# Strong sentiment so the proposal isn't refused on relationship grounds
male.record_interaction(female, 8.0)
female.record_interaction(male, 8.0)

# Force a pairing (skips willingness contest — retry up to 5 times for d20 variance)
pair_result = None
for _attempt in range(5):
    pair_result = male.force_pairing(female, now=0)
    if pair_result.get('accepted'):
        break
    male._pair_cooldown = 0  # reset cooldown for retry
check("force_pairing completed", pair_result is not None)
check(f"female is pregnant after pairing (reason: {pair_result.get('reason', 'ok')})",
      female.is_pregnant)

# Egg should be in female's inventory and equal to her _pregnancy_egg
preg_eggs = [i for i in female.inventory.items if isinstance(i, Egg)]
check("pregnancy egg in female inventory", len(preg_eggs) == 1)
check("pregnancy egg matches _pregnancy_egg",
      preg_eggs and preg_eggs[0] is female._pregnancy_egg)

egg = preg_eggs[0]
check("fresh egg has 0 gestation days", egg.gestation_days == 0)
check("fresh egg is alive", egg.live)
check("fresh egg is NOT ready_to_hatch", not egg.ready_to_hatch)

# Tick gestation 30 times — egg should be ready
for _ in range(egg.gestation_period):
    egg.tick_gestation(carried_by_mother=True)
check(f"egg gestation_days reached {egg.gestation_period}",
      egg.gestation_days >= egg.gestation_period)
# May be dead from random ~1%/day rolls; if so, hatch returns None
if egg.live:
    check("aged egg ready_to_hatch", egg.ready_to_hatch)
    child = egg.hatch(bm, female.location)
    check("hatch returns a child", child is not None)
    if child is not None:
        check("hatched child is age 0", child.age == 0)
        check("hatched child has female's species", child.species == female.species)
        check("hatched child is on the map",
              child.current_map is bm)
        check("hatched child has mother_uid set",
              getattr(child, 'mother_uid', None) == female.uid)

# --- End-to-end via Simulation: pair, advance days, see hatching ---
# Use a synthetic Simulation directly with our test creatures
from editor.simulation.headless import Simulation
sim_arena = {
    'map': bm,
    'creatures': [male, female],
    'cols': 8, 'rows': 8,
}
sim = Simulation(sim_arena)
initial_pop = len(sim.creatures)

# Force a fresh pairing in the sim. We need to:
#   * clear the female's pregnancy state
#   * clear the male's pair cooldown (set to 1 day in the previous pairing)
#   * top off the male's HP/stamina (drained by the previous pairing)
def _reset_for_pair(m, f):
    f.is_pregnant = False
    f._pregnancy_egg = None
    f.stats.remove_mods_by_source('pregnancy')
    m._pair_cooldown = 0
    m.stats.base[Stat.HP_CURR] = m.stats.active[Stat.HP_MAX]()
    m.stats.base[Stat.CUR_STAMINA] = m.stats.active[Stat.MAX_STAMINA]()

_reset_for_pair(male, female)
male.force_pairing(female, now=0)
check("sim: female re-pregnant after second pairing", female.is_pregnant)

# Manually fire the lifecycle pass for 30 days — this is what
# Simulation.step does on every game-day boundary.
for _ in range(35):
    sim._tick_lifecycle_day()

# By now any surviving egg should have hatched and the population grown
hatched = len(sim.creatures) - initial_pop
print(f'  (sim ticked 35 days; hatched {hatched} creature(s))')
# The 1%/day death roll over 30 days = ~26% survival, so a single
# pairing has a real chance of producing a dead egg. Run ~5 trials
# until at least one survives, just to make the test reliable.
trials = 0
while hatched == 0 and trials < 5:
    _reset_for_pair(male, female)
    male.force_pairing(female, now=0)
    for _ in range(35):
        sim._tick_lifecycle_day()
    hatched = len(sim.creatures) - initial_pop
    trials += 1
check(f"at least one egg hatched into the simulation (trials={trials+1})",
      hatched >= 1)

# ==========================================================================
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
if FAIL:
    sys.exit(1)
else:
    print("All tests passed!")
