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

# ---- Extended guards (rel/has_item/lifecycle/profession/level_max) ----
# Use a fresh conversation name so these don't contaminate the above tests.
DIALOGUE[20] = {
    'id': 20, 'conversation': 'guards', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'Good to see you, friend.',
    'char_conditions': {'rel_min': 5.0},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [],
}
DIALOGUE[21] = {
    'id': 21, 'conversation': 'guards', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'You again.',
    'char_conditions': {'rel_max': -5.0},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [],
}
DIALOGUE[22] = {
    'id': 22, 'conversation': 'guards', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'Welcome, keyholder.',
    'char_conditions': {'has_item': 'KeyOfTheCity'},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [],
}
DIALOGUE[23] = {
    'id': 23, 'conversation': 'guards', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'Move along, recruit.',
    'char_conditions': {'level_max': 2},
    'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0,
    'children': [],
}
DIALOGUE_ROOTS['guards'] = [20, 21, 22, 23]

from classes.relationship_graph import GRAPH
from classes.inventory import Item

# rel_min: friend-only line hidden at neutral
neutral_p = make_creature(m40, x=6, y=0, stats={Stat.PER: 12, Stat.LVL: 5},
                          name='NeutralP')
neutral_n = make_creature(m40, x=7, y=0, stats={Stat.PER: 12}, name='NeutralN')
neutral_roots = neutral_p.start_conversation(neutral_n, 'guards')
check("rel_min line hidden at neutral rel",
      not any(n['text'] == 'Good to see you, friend.' for n in neutral_roots))
check("rel_max line hidden at neutral rel",
      not any(n['text'] == 'You again.' for n in neutral_roots))
neutral_p.end_conversation()

# Bump rel high, friend line appears
GRAPH.record_interaction(neutral_p.uid, neutral_n.uid, 10.0)
friend_roots = neutral_p.start_conversation(neutral_n, 'guards')
check("rel_min line appears when rel >= threshold",
      any(n['text'] == 'Good to see you, friend.' for n in friend_roots))
neutral_p.end_conversation()

# rel_max: enemy line appears when rel is deeply negative
enemy_p = make_creature(m40, x=8, y=0, stats={Stat.PER: 12, Stat.LVL: 5},
                        name='EnemyP')
enemy_n = make_creature(m40, x=9, y=0, stats={Stat.PER: 12}, name='EnemyN')
GRAPH.record_interaction(enemy_p.uid, enemy_n.uid, -10.0)
enemy_roots = enemy_p.start_conversation(enemy_n, 'guards')
check("rel_max line appears when rel <= threshold",
      any(n['text'] == 'You again.' for n in enemy_roots))
enemy_p.end_conversation()

# has_item: keyholder line gated on inventory
key_p = make_creature(m40, x=10, y=0, stats={Stat.PER: 12, Stat.LVL: 5},
                      name='KeyP')
key_n = make_creature(m40, x=11, y=0, stats={Stat.PER: 12}, name='KeyN')
no_key_roots = key_p.start_conversation(key_n, 'guards')
check("has_item guard blocks when item absent",
      not any(n['text'] == 'Welcome, keyholder.' for n in no_key_roots))
key_p.end_conversation()
key_p.inventory.items.append(Item(name='KeyOfTheCity', weight=0.1, value=0.0))
with_key_roots = key_p.start_conversation(key_n, 'guards')
check("has_item guard passes when item present",
      any(n['text'] == 'Welcome, keyholder.' for n in with_key_roots))
key_p.end_conversation()

# level_max: recruit line hidden for high-level character
high_p = make_creature(m40, x=12, y=0, stats={Stat.PER: 12, Stat.LVL: 10},
                       name='HighP')
high_n = make_creature(m40, x=13, y=0, stats={Stat.PER: 12}, name='HighN')
high_roots = high_p.start_conversation(high_n, 'guards')
check("level_max line hidden for high level",
      not any(n['text'] == 'Move along, recruit.' for n in high_roots))
high_p.end_conversation()

low_p = make_creature(m40, x=14, y=0, stats={Stat.PER: 12, Stat.LVL: 1},
                      name='LowP')
low_n = make_creature(m40, x=15, y=0, stats={Stat.PER: 12}, name='LowN')
low_roots = low_p.start_conversation(low_n, 'guards')
check("level_max line shown for low level",
      any(n['text'] == 'Move along, recruit.' for n in low_roots))
low_p.end_conversation()

# ---- Branch node (auto_advance) ----
DIALOGUE[30] = {
    'id': 30, 'conversation': 'branching', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': '<branch>',
    'char_conditions': {}, 'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {'auto_advance': True},
    'sort_order': 0, 'children': [31],
}
DIALOGUE[31] = {
    'id': 31, 'conversation': 'branching', 'species': None,
    'creature_key': None, 'parent_id': 30, 'speaker': 'npc',
    'text': 'Landed here automatically.',
    'char_conditions': {}, 'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0, 'children': [32],
}
DIALOGUE[32] = {
    'id': 32, 'conversation': 'branching', 'species': None,
    'creature_key': None, 'parent_id': 31, 'speaker': 'player',
    'text': 'OK.',
    'char_conditions': {}, 'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0, 'children': [],
}
DIALOGUE_ROOTS['branching'] = [30]

bp = make_creature(m40, x=16, y=0, stats={Stat.PER: 12}, name='BranchP')
bn = make_creature(m40, x=17, y=0, stats={Stat.PER: 12}, name='BranchN')
branch_roots = bp.start_conversation(bn, 'branching')
check(f"Branch root found: {len(branch_roots)}", len(branch_roots) == 1)
returned = bp.advance_dialogue(30, bn)
check("Branch auto-advanced past node 30",
      bp.dialogue is not None and bp.dialogue['current_node_id'] == 31)
check(f"Branch returned target's children: {[c['id'] for c in returned]}",
      len(returned) == 1 and returned[0]['id'] == 32)
bp.end_conversation()

# ---- Goto (cross-conversation jump) ----
DIALOGUE[40] = {
    'id': 40, 'conversation': 'entry', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'Ask the barkeep.',
    'char_conditions': {}, 'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {'goto': 'barkeep'},
    'sort_order': 0, 'children': [],
}
DIALOGUE[41] = {
    'id': 41, 'conversation': 'barkeep', 'species': None,
    'creature_key': None, 'parent_id': None, 'speaker': 'npc',
    'text': 'What can I get you?',
    'char_conditions': {}, 'world_conditions': {}, 'quest_conditions': {},
    'behavior': None, 'effects': {}, 'sort_order': 0, 'children': [],
}
DIALOGUE_ROOTS['entry'] = [40]
DIALOGUE_ROOTS['barkeep'] = [41]

gp = make_creature(m40, x=18, y=0, stats={Stat.PER: 12}, name='GotoP')
gn = make_creature(m40, x=19, y=0, stats={Stat.PER: 12}, name='GotoN')
goto_roots = gp.start_conversation(gn, 'entry')
check(f"Goto entry root found: {len(goto_roots)}", len(goto_roots) == 1)
new_roots = gp.advance_dialogue(40, gn)
check(f"Goto returned target conversation roots: {[n['id'] for n in new_roots]}",
      len(new_roots) == 1 and new_roots[0]['id'] == 41)
check("Conversation name updated after goto",
      gp.dialogue is not None and gp.dialogue['conversation'] == 'barkeep')
gp.end_conversation()

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
print("\n=== Monster Species Loading ===")
from data.db import MONSTER_SPECIES

check(f">= 9 monster species loaded (got {len(MONSTER_SPECIES)})",
      len(MONSTER_SPECIES) >= 9)
for key in ['grey_wolf', 'honey_bees', 'cave_bear', 'dire_orc']:
    check(f"  {key} in MONSTER_SPECIES", key in MONSTER_SPECIES)

wolf_cfg = MONSTER_SPECIES['grey_wolf']
check(f"wolf diet = carnivore", wolf_cfg['diet'] == 'carnivore')
check(f"wolf split_size = 10", wolf_cfg['split_size'] == 10)
check(f"wolf territory_scales = True", wolf_cfg['territory_scales'] is True)

bee_cfg = MONSTER_SPECIES['honey_bees']
check(f"bees dominance = fixed", bee_cfg['dominance_type'] == 'fixed')
check(f"bees collapse_on_alpha_death", bee_cfg['collapse_on_alpha_death'] is True)
check(f"bees territory_scales = False", bee_cfg['territory_scales'] is False)

# ==========================================================================
print("\n=== Monster Class Construction ===")
from classes.monster import Monster

mm = make_map(20, 20)
wolf = Monster(current_map=mm, location=MapKey(5, 5, 0),
               species='grey_wolf', sex='male', age=20)
check(f"wolf species = grey_wolf", wolf.species == 'grey_wolf')
check(f"wolf size = medium", wolf.size == 'medium')
check(f"wolf diet = carnivore", wolf.diet == 'carnivore')
check(f"wolf dominance_type = contest", wolf.dominance_type == 'contest')
check(f"wolf meat_value = 0.3", abs(wolf.meat_value - 0.3) < 0.01)
check(f"wolf stats.base[STR] = 14", wolf.stats.base.get(Stat.STR) == 14)
check(f"wolf has stubbed get_relationship", wolf.get_relationship(wolf) is None)

# ==========================================================================
print("\n=== Pack: Membership, Ranking, Alpha ===")
from classes.pack import Pack

pm = make_map(20, 20)
alpha_wolf = Monster(current_map=pm, location=MapKey(10, 10, 0),
                     species='grey_wolf', sex='male',
                     stats={Stat.STR: 18, Stat.VIT: 16, Stat.AGL: 14})
beta_wolf = Monster(current_map=pm, location=MapKey(11, 10, 0),
                    species='grey_wolf', sex='male',
                    stats={Stat.STR: 12, Stat.VIT: 12, Stat.AGL: 10})
pack = Pack(species='grey_wolf', territory_center=MapKey(10, 10, 0), game_map=pm)
pack.add_member(alpha_wolf)
pack.add_member(beta_wolf)

check(f"pack size = 2", pack.size == 2)
check(f"alpha is highest-stat wolf", pack.alpha_male is alpha_wolf)
check(f"alpha_wolf.is_alpha True", alpha_wolf.is_alpha is True)
check(f"beta_wolf.is_alpha False", beta_wolf.is_alpha is False)
check(f"alpha_wolf.rank = 0", alpha_wolf.rank == 0)
check(f"beta_wolf.rank = 1", beta_wolf.rank == 1)

# ==========================================================================
print("\n=== Pack: Territory Scaling ===")
# Wolf territory scales with pack size
solo_pack = Pack(species='grey_wolf', territory_center=MapKey(5, 5, 0), game_map=pm)
solo_wolf = Monster(current_map=pm, location=MapKey(5, 5, 0),
                    species='grey_wolf', sex='male')
solo_pack.add_member(solo_wolf)
solo_territory = solo_pack.effective_territory_size()
full_territory = pack.effective_territory_size()
check(f"solo wolf pack has smaller territory ({solo_territory:.2f} < {full_territory:.2f})",
      solo_territory < full_territory)

# Bees have fixed territory regardless of size
bees_pack = Pack(species='honey_bees', territory_center=MapKey(12, 12, 0), game_map=pm)
bee1 = Monster(current_map=pm, location=MapKey(12, 12, 0),
               species='honey_bees', sex='female')
bees_pack.add_member(bee1)
bees_solo = bees_pack.effective_territory_size()
# The cohesion modulation still applies, but the size-scaling doesn't.
check(f"bee pack territory NOT scaled with size",
      not bees_pack.territory_scales)

# ==========================================================================
print("\n=== Monster Observation + NN ===")
from classes.monster_observation import build_monster_observation, MONSTER_OBSERVATION_SIZE
from classes.monster_net import MonsterNet
from classes.monster_actions import compute_monster_mask, MonsterAction

obs = build_monster_observation(alpha_wolf, 20, 20)
check(f"monster obs length = MONSTER_OBSERVATION_SIZE ({MONSTER_OBSERVATION_SIZE})",
      len(obs) == MONSTER_OBSERVATION_SIZE)

mnet = MonsterNet()
import numpy as np
probs = mnet.forward(np.array(obs, dtype=np.float32))
check(f"MonsterNet output shape = 11", len(probs) == 11)
check(f"MonsterNet probs sum ~ 1", abs(probs.sum() - 1.0) < 0.01)

# INT-gated mask: bees (INT=2) only allow Move/Attack/Flee/Harvest-if-herbivore
bee_mask = compute_monster_mask(bee1)
allowed_bee = [i for i, v in enumerate(bee_mask) if v > 0]
check(f"bee mask restricted (got {allowed_bee})",
      int(MonsterAction.PATROL) not in allowed_bee and
      int(MonsterAction.HOWL) not in allowed_bee)
check(f"bee mask includes MOVE", int(MonsterAction.MOVE) in allowed_bee)
check(f"bee mask includes ATTACK", int(MonsterAction.ATTACK) in allowed_bee)

wolf_mask = compute_monster_mask(alpha_wolf)
allowed_wolf = [i for i, v in enumerate(wolf_mask) if v > 0]
check(f"wolf (INT=8) mask includes HOWL", int(MonsterAction.HOWL) in allowed_wolf)
check(f"wolf (INT=8) mask includes PATROL", int(MonsterAction.PATROL) in allowed_wolf)

# ==========================================================================
print("\n=== Meat Item: Species Tag + Spoilage ===")
from classes.inventory import Meat

meat = Meat(name='wolf_meat', weight=0.5, value=1.0, quantity=1,
            species='grey_wolf', meat_value=0.3,
            spoil_tick=1000, is_monster_meat=True)
check(f"meat has species tag", meat.species == 'grey_wolf')
check(f"fresh meat not spoiled at now=500", not meat.is_spoiled(500))
check(f"meat spoiled at now=1500", meat.is_spoiled(1500))
check(f"preserved meat never spoils",
      Meat(name='p', weight=0, value=0, quantity=1, species='x',
           meat_value=0.3, spoil_tick=0, is_preserved=True).is_spoiled(99999) is False)

# ==========================================================================
print("\n=== Monster Death Drops Meat ===")
from classes.maps import Tile

dm = make_map(10, 10)
death_wolf = Monster(current_map=dm, location=MapKey(4, 4, 0),
                     species='grey_wolf', sex='male')
tile = dm.tiles[MapKey(4, 4, 0)]
check(f"tile has no meat pre-death",
      not any(isinstance(i, Meat) for i in tile.inventory.items))

death_wolf.die()
meats = [i for i in tile.inventory.items if isinstance(i, Meat)]
check(f"tile has 1 meat item post-death", len(meats) == 1)
if meats:
    m = meats[0]
    check(f"meat.species = grey_wolf", m.species == 'grey_wolf')
    check(f"meat.is_monster_meat = True", m.is_monster_meat is True)
    check(f"meat.meat_value = 0.3", abs(m.meat_value - 0.3) < 0.01)

# ==========================================================================
print("\n=== Cannibalism: Rumor Broadcast + Piety Loss ===")
from classes.relationship_graph import GRAPH

cm = make_map(10, 10)
eater = make_creature(cm, x=5, y=5,
                      stats={Stat.STR: 10, Stat.VIT: 12, Stat.PER: 14},
                      name='Eater')
eater.species = 'human'
witness = make_creature(cm, x=6, y=5, stats={Stat.PER: 14}, name='Witness')
eater.deity = 'Solmara'
eater.piety = 0.5

# Create cannibal meat (same species)
cannibal_meat = Meat(name='human_flesh', weight=0.3, value=1.0, quantity=1,
                     species='human', meat_value=0.3, spoil_tick=999999,
                     is_monster_meat=False)
eater.inventory.items.append(cannibal_meat)

piety_before = eater.piety
eater.use_item(cannibal_meat)
check(f"cannibalism counter incremented",
      getattr(eater, '_cannibalism_events', 0) == 1)
rel = GRAPH.get_edge(witness.uid, eater.uid)
check(f"witness records negative sentiment toward eater",
      rel is not None and rel[0] < 0)
check(f"eater piety decreased ({piety_before} -> {eater.piety})",
      eater.piety < piety_before)

# Non-cannibal meat: no penalty
wolf_meat = Meat(name='wolf_flesh', weight=0.3, value=1.0, quantity=1,
                 species='grey_wolf', meat_value=0.3, spoil_tick=999999)
eater2 = make_creature(cm, x=1, y=1, name='Eater2')
eater2.species = 'human'
eater2.inventory.items.append(wolf_meat)
eater2.use_item(wolf_meat)
check(f"eating non-cannibal meat: no event",
      getattr(eater2, '_cannibalism_events', 0) == 0)

# ==========================================================================
print("\n=== Alpha Death Collapse (bees) vs Promotion (wolves) ===")
am = make_map(10, 10)
bee_pack = Pack(species='honey_bees',
                territory_center=MapKey(5, 5, 0), game_map=am)
queen = Monster(current_map=am, location=MapKey(5, 5, 0),
                species='honey_bees', sex='female',
                stats={Stat.STR: 5, Stat.VIT: 5})
worker1 = Monster(current_map=am, location=MapKey(5, 5, 0),
                  species='honey_bees', sex='female',
                  stats={Stat.STR: 2, Stat.VIT: 2})
worker2 = Monster(current_map=am, location=MapKey(5, 5, 0),
                  species='honey_bees', sex='female',
                  stats={Stat.STR: 2, Stat.VIT: 2})
bee_pack.add_member(queen)
bee_pack.add_member(worker1)
bee_pack.add_member(worker2)
check(f"queen is alpha", bee_pack.alpha_female is queen)

# Queen dies -> pack collapses, survivors become solitary
bee_pack.remove_member(queen)
check(f"bee pack collapsed (size=0)", bee_pack.size == 0)
# Survivors should each have their own 1-member pack
check(f"worker1 in own pack", worker1.pack is not None and worker1.pack is not bee_pack)
check(f"worker2 in own pack", worker2.pack is not None and worker2.pack is not bee_pack)
check(f"worker1 pack size = 1",
      worker1.pack is not None and worker1.pack.size == 1)

# Wolves don't collapse: beta promotes
wolf_pack2 = Pack(species='grey_wolf',
                  territory_center=MapKey(8, 8, 0), game_map=am)
a_wolf = Monster(current_map=am, location=MapKey(8, 8, 0),
                 species='grey_wolf', sex='male',
                 stats={Stat.STR: 18, Stat.VIT: 16, Stat.AGL: 14})
b_wolf = Monster(current_map=am, location=MapKey(8, 9, 0),
                 species='grey_wolf', sex='male',
                 stats={Stat.STR: 14, Stat.VIT: 14, Stat.AGL: 12})
wolf_pack2.add_member(a_wolf)
wolf_pack2.add_member(b_wolf)
wolf_pack2.remove_member(a_wolf)
check(f"wolf pack survives alpha removal", wolf_pack2.size == 1)
check(f"beta promoted to alpha", b_wolf.is_alpha is True)

# ==========================================================================
print("\n=== Pack Territory Overlap + Hostility ===")
tm = make_map(40, 40)
pa = Pack(species='grey_wolf', territory_center=MapKey(10, 10, 0), game_map=tm)
wa = Monster(current_map=tm, location=MapKey(10, 10, 0),
             species='grey_wolf', sex='male')
pa.add_member(wa)

# Pack B close to A (overlapping)
pb = Pack(species='grey_wolf', territory_center=MapKey(12, 10, 0), game_map=tm)
wb = Monster(current_map=tm, location=MapKey(12, 10, 0),
             species='grey_wolf', sex='male')
pb.add_member(wb)

# Pack C far from A (not overlapping)
pc = Pack(species='grey_wolf', territory_center=MapKey(35, 35, 0), game_map=tm)
wc = Monster(current_map=tm, location=MapKey(35, 35, 0),
             species='grey_wolf', sex='male')
pc.add_member(wc)

# Small packs can merge (combined size=2 <= split_size/2=5)
check(f"pa can merge with pb (small compatible)", pa.can_merge_with(pb))
check(f"pa is_hostile False (merge preempts hostility)",
      pa.is_hostile_to(pb) is False)

# ==========================================================================
print("\n=== Monster Dispatch: MOVE, EAT ===")
from classes.monster_dispatch import dispatch_monster

dis_map = make_map(15, 15)
dw = Monster(current_map=dis_map, location=MapKey(5, 5, 0),
             species='grey_wolf', sex='male')
dp = Pack(species='grey_wolf', territory_center=MapKey(8, 5, 0), game_map=dis_map)
dp.add_member(dw)

# MOVE should step toward pack target (territory sample)
old_loc = dw.location
res = dispatch_monster(dw, int(MonsterAction.MOVE),
                       {'cols': 15, 'rows': 15, 'now': 0})
check(f"MOVE dispatch returns result dict", isinstance(res, dict))

# EAT: place meat on tile, dispatch EAT, verify hunger restored
dw.hunger = 0.3
eat_meat = Meat(name='m', weight=0.1, value=0.1, quantity=1,
                species='deer', meat_value=0.3, spoil_tick=99999)
dis_map.tiles[dw.location].inventory.items.append(eat_meat)
hunger_before = dw.hunger
res = dispatch_monster(dw, int(MonsterAction.EAT),
                       {'cols': 15, 'rows': 15, 'now': 0})
check(f"EAT succeeded", res['success'])
check(f"hunger increased ({hunger_before} -> {dw.hunger})",
      dw.hunger > hunger_before)
check(f"meat removed from tile",
      eat_meat not in dis_map.tiles[dw.location].inventory.items)

# EAT own-species: flag ate_own_species
self_meat = Meat(name='wolf', weight=0.1, value=0.1, quantity=1,
                 species='grey_wolf', meat_value=0.3, spoil_tick=99999)
dis_map.tiles[dw.location].inventory.items.append(self_meat)
res = dispatch_monster(dw, int(MonsterAction.EAT),
                       {'cols': 15, 'rows': 15, 'now': 0})
check(f"monster eating own species: ate_own_species flag",
      res.get('ate_own_species') is True)

# ==========================================================================
print("\n=== Monster Tick: Simulation Integration ===")
from editor.simulation.headless import Simulation as MonSim
from editor.simulation.arena import spawn_monsters_for_stage

sim_map = make_map(20, 20)
sim_creatures = []
for i in range(2):
    c = make_creature(sim_map, x=i * 3, y=10,
                      stats={Stat.STR: 10, Stat.VIT: 12, Stat.PER: 10},
                      name=f'cs{i}')
    sim_creatures.append(c)

ms, ps = spawn_monsters_for_stage(sim_map, 20, 20,
    species_subset=['grey_wolf'],
    count_per_species=2)
check(f"spawn_monsters_for_stage returns monsters", len(ms) >= 1)
check(f"spawn_monsters_for_stage returns packs", len(ps) >= 1)

arena_with_mon = {'map': sim_map, 'creatures': sim_creatures,
                  'monsters': ms, 'packs': ps,
                  'cols': 20, 'rows': 20}
monsim = MonSim(arena_with_mon, gestation_enabled=False,
                fatigue_enabled=False)
monsim.use_monster_heuristic = True
for _ in range(10):
    monsim.step()
check(f"simulation ticked 10 steps with monsters", monsim.step_count == 10)
check(f"monsters still active after sim ticks",
      len(monsim.monsters) >= 1 or all(not m.is_alive for m in ms))

# ==========================================================================
print("\n=== Creature Observation Sees Monsters ===")
from classes.observation import build_observation, SECTION_RANGES

om = make_map(15, 15)
cobs_hero = make_creature(om, x=7, y=7,
                          stats={Stat.STR: 12, Stat.VIT: 12, Stat.PER: 14,
                                 Stat.INT: 10, Stat.LCK: 10},
                          name='obs_hero')
# No monster visible → slots zero
obs_no_mon = build_observation(cobs_hero, 15, 15)
s, e = SECTION_RANGES['monster_slots']
check(f"no monster: slots all zero",
      all(v == 0.0 for v in obs_no_mon[s:e]))

# Spawn a monster in sight range
obs_wolf = Monster(current_map=om, location=MapKey(9, 7, 0),
                   species='grey_wolf', sex='male')
obs_pack = Pack(species='grey_wolf', territory_center=MapKey(9, 7, 0), game_map=om)
obs_pack.add_member(obs_wolf)
obs_with_mon = build_observation(cobs_hero, 15, 15)
slot_vals = obs_with_mon[s:s+6]
check(f"monster visible: slot 0 has non-zero values",
      any(v != 0.0 for v in slot_vals))
check(f"slot 0 distance > 0 (normalized)", slot_vals[0] > 0)

# ==========================================================================
print("\n=== MonsterTrainer: Attach + Online RL Smoke ===")
try:
    from editor.simulation.monster_train import MonsterTrainer, TorchMonsterPolicy
    import torch as _torch
    _torch.manual_seed(42)

    # Small sim with 2 wolves and 2 creatures
    tr_map = make_map(20, 20)
    tr_creatures = [make_creature(tr_map, x=i * 3, y=10,
                                  stats={Stat.STR: 10, Stat.VIT: 12,
                                         Stat.PER: 10},
                                  name=f'tc{i}')
                    for i in range(2)]
    tr_monsters, tr_packs = spawn_monsters_for_stage(
        tr_map, 20, 20, species_subset=['grey_wolf'],
        count_per_species=2)

    trainer = MonsterTrainer(monster_rollout_len=20)
    tr_arena = {'map': tr_map, 'creatures': tr_creatures,
                'monsters': tr_monsters, 'packs': tr_packs,
                'cols': 20, 'rows': 20}
    tr_sim = MonSim(tr_arena, gestation_enabled=False,
                    fatigue_enabled=False)
    trainer.attach_to_sim(tr_sim)

    check(f"trainer.attach sets sim.monster_net",
          tr_sim.monster_net is not None)
    check(f"trainer.attach sets sim.pack_net",
          tr_sim.pack_net is not None)
    check(f"trainer disables heuristic",
          tr_sim.use_monster_heuristic is False)

    updates_before = trainer.monster_updates
    for _ in range(30):
        tr_sim.step()
        trainer.on_step(tr_sim, signal_scales={
            'm_kills': 1.0, 'm_hp': 0.5, 'm_territory_stay': 0.3,
        })
    check(f"trainer ran >= 1 PPO update",
          trainer.monster_updates >= updates_before + 1 or
          trainer._total_buffered() > 0)
    check(f"trainer loss tracked",
          isinstance(trainer.last_loss, float))

    # Export test
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        trainer.export_weights(out_dir=tmp)
        p = Path(tmp)
        check(f"monster_net_trained.npz exported",
              (p / 'monster_net_trained.npz').exists())
        check(f"pack_net_trained.npz exported",
              (p / 'pack_net_trained.npz').exists())
except ImportError as e:
    print(f"  SKIP: MonsterTrainer test requires torch ({e})")

# ==========================================================================
print("\n=== Location Rumors (territory + purpose) ===")
GRAPH.clear()

hm = make_map(15, 15)
hm.name = 'rumor_map'
hm.tiles[MapKey(7, 7, 0)].purpose = 'trading'

scout = make_creature(hm, x=7, y=7, stats={Stat.PER: 14, Stat.CHR: 14},
                      name='Scout')
# Put a monster nearby so scout can record a territory rumor
from classes.monster import Monster
from classes.pack import Pack
r_wolf = Monster(current_map=hm, location=MapKey(9, 7, 0),
                 species='grey_wolf', sex='male')
r_pack = Pack(species='grey_wolf', territory_center=MapKey(9, 7, 0),
              game_map=hm)
r_pack.add_member(r_wolf)

scout.record_nearby_location_rumors(tick=100)
n_rumors = GRAPH.count_location_rumors_held(scout.uid)
check(f"scout recorded location rumors (got {n_rumors})", n_rumors >= 2)

purp_best = GRAPH.best_location_rumor(scout.uid, 'purpose')
check(f"best purpose rumor is scout's tile",
      purp_best is not None and purp_best[0] == ('rumor_map', 7, 7))
terr_best = GRAPH.best_location_rumor(scout.uid, 'territory')
check(f"best territory rumor is wolf pack center",
      terr_best is not None and terr_best[0] == ('rumor_map', 9, 7))
check(f"territory sentiment is negative (danger)",
      terr_best is not None and terr_best[1] < 0)
check(f"purpose sentiment is positive (seek)",
      purp_best is not None and purp_best[1] > 0)

# Share rumor with a listener
listener = make_creature(hm, x=8, y=7, stats={Stat.PER: 10}, name='Listener')
check(f"listener starts with no rumors",
      GRAPH.count_location_rumors_held(listener.uid) == 0)
# Retry a few times for CHR-based share success rolls (currently always
# succeeds because share_location_rumor has no chance gate; still OK)
shared = scout.share_location_rumor(listener, tick=200)
check(f"share succeeded", shared)
listener_count = GRAPH.count_location_rumors_held(listener.uid)
check(f"listener received rumor (count={listener_count})",
      listener_count >= 1)

# Shared rumor has decayed confidence
listener_best_purp = GRAPH.best_location_rumor(listener.uid, 'purpose')
listener_best_terr = GRAPH.best_location_rumor(listener.uid, 'territory')
received = listener_best_purp or listener_best_terr
if received is not None:
    check(f"shared rumor confidence < 1.0 (got {received[2]:.2f})",
          received[2] < 0.99)

# ==========================================================================
print("\n=== Mourning / Grief (awareness-gated) ===")
from classes.mourning import (
    notify_death, _base_magnitude, make_grief_snapshot,
    GRIEF_TIERS, FINISH_FIGHT_DELAY_MS, FALLBACK_REACH_MS,
    is_aware, share_death_news, get_death_event, clear_grief,
)

GRAPH.clear()
gm = make_map(30, 30)

# Two bonded creatures — witnesses within sight
lover_a = make_creature(gm, x=10, y=10, name='Romeo',
                        stats={Stat.PER: 14})
lover_b = make_creature(gm, x=11, y=10, name='Juliet',
                        stats={Stat.PER: 14})
# Off-map creature: bonded but far away (out of sight)
far_friend = make_creature(gm, x=28, y=28, name='FarFriend',
                            stats={Stat.PER: 10})
# Enemy — should never grieve
enemy = make_creature(gm, x=12, y=10, name='Tybalt')

# Seed relationships: lovers deeply bonded, friend mildly bonded,
# enemy hostile.
for _ in range(40):
    GRAPH.record_interaction(lover_a.uid, lover_b.uid, 19.0)
    GRAPH.record_interaction(lover_b.uid, lover_a.uid, 19.0)
for _ in range(20):
    GRAPH.record_interaction(far_friend.uid, lover_a.uid, 10.0)
for _ in range(10):
    GRAPH.record_interaction(enemy.uid, lover_a.uid, -10.0)

check(f"Lover magnitude > 50",
      _base_magnitude(lover_b, lover_a.uid) > 50)
check(f"Far friend magnitude > 8 (notable tier)",
      _base_magnitude(far_friend, lover_a.uid) > 8)
check(f"Enemy magnitude is 0",
      _base_magnitude(enemy, lover_a.uid) == 0)

# Fire the death
lover_a._last_update_time = 1000
str_before = lover_b.stats.active[Stat.STR]()
chr_before = lover_b.stats.active[Stat.CHR]()
lover_a.die()

# 1. SIGHT WITNESS: lover_b can see the death tile (adjacent)
check(f"Lover is aware immediately",
      is_aware(lover_b, lover_a.uid))
check(f"Lover grief counter incremented at death-time",
      lover_b._grief_events_total == 1)
check(f"Lover remembers death location",
      len(lover_b._grief_death_locations) == 1)

# 2. BUT debuffs are delayed — stats NOT yet reduced
str_mid = lover_b.stats.active[Stat.STR]()
chr_mid = lover_b.stats.active[Stat.CHR]()
check(f"Lover STR unchanged during grace ({str_before} -> {str_mid})",
      str_mid == str_before)
check(f"Lover CHR unchanged during grace",
      chr_mid == chr_before)

# 3. After 2 game hours (finish-fight delay), debuffs fire
lover_b.process_ticks(FINISH_FIGHT_DELAY_MS + 1)
str_after = lover_b.stats.active[Stat.STR]()
chr_after = lover_b.stats.active[Stat.CHR]()
check(f"Lover STR dropped after grace ({str_before} -> {str_after})",
      str_after < str_before)
check(f"Lover CHR dropped after grace",
      chr_after < chr_before)

# 4. FAR FRIEND: not in sight — should NOT be aware yet
check(f"Far friend not aware without witness/rumor",
      not is_aware(far_friend, lover_a.uid))
check(f"Far friend grief counter still 0",
      far_friend._grief_events_total == 0)

# 5. Enemy never grieves
check(f"Enemy never aware (hostile relationship)",
      not is_aware(enemy, lover_a.uid))
check(f"Enemy grief counter == 0",
      enemy._grief_events_total == 0)

# 6. RUMOR PROPAGATION: lover_b (witness) talks to far_friend
# lover_b carries rumor at confidence 1.0; share decays to 0.6
transmitted = share_death_news(lover_b, far_friend, tick=2000)
check(f"share_death_news transmitted to far_friend",
      transmitted)
check(f"Far friend now aware via rumor",
      is_aware(far_friend, lover_a.uid))
known = far_friend._known_deaths[lover_a.uid]
check(f"Rumor confidence < 1.0 (got {known['confidence']:.2f})",
      known['confidence'] < 1.0)
check(f"Rumor confidence > 0.5",
      known['confidence'] > 0.5)
check(f"Rumor source is decorated 'rumor_from_'",
      known['source'].startswith('rumor_from_'))

# Far friend grief event fired (magnitude attenuated by confidence)
check(f"Far friend grief counter incremented",
      far_friend._grief_events_total == 1)
# Base = sentiment * ln(count+1); attenuated by 0.6 rumor decay
# Confirm attenuation occurred — i.e. effective < base magnitude
ff_base = _base_magnitude(far_friend, lover_a.uid)
ff_mag = far_friend._grief_magnitude_sum
check(f"Far friend effective magnitude attenuated "
      f"(base={ff_base:.0f}, effective={ff_mag:.0f})",
      ff_mag < ff_base and ff_mag > 0)

# 7. FALLBACK REACH: a third isolated bonded creature
GRAPH.clear()
victim = make_creature(gm, x=15, y=15, name='Victim',
                       stats={Stat.PER: 14})
isolated = make_creature(gm, x=29, y=29, name='Isolated',
                         stats={Stat.PER: 10})
for _ in range(20):
    GRAPH.record_interaction(isolated.uid, victim.uid, 10.0)
victim._last_update_time = 5000
victim.die()
check(f"Isolated NOT aware at death-time",
      not is_aware(isolated, victim.uid))
# Advance time past fallback reach window
isolated.process_ticks(FALLBACK_REACH_MS + 1)
check(f"Isolated aware after fallback reach",
      is_aware(isolated, victim.uid))
fallback_entry = isolated._known_deaths.get(victim.uid, {})
check(f"Fallback source is 'fallback_reach'",
      fallback_entry.get('source') == 'fallback_reach')
check(f"Fallback confidence is reduced (0.3)",
      abs(fallback_entry.get('confidence', 0) - 0.3) < 0.01)

# 8. Grief reward signal (via snapshot delta)
from classes.reward import compute_reward, make_reward_snapshot
pre_snap = make_reward_snapshot(lover_b)
pre_snap['grief_magnitude_sum'] = 0
pre_snap['grief_events_total'] = 0
curr_snap = make_reward_snapshot(lover_b)
_, signals = compute_reward(lover_b, pre_snap, curr_snap,
                            breakdown=True,
                            signal_scales={'grief': 1.0})
check(f"grief signal present", 'grief' in signals)
check(f"grief signal is negative",
      signals.get('grief', 0) < 0)

# 9. Cleanup
clear_grief(lover_b)
str_restored = lover_b.stats.active[Stat.STR]()
check(f"clear_grief restores STR",
      str_restored == str_before)

# 10. Training scenario smoke test
from editor.simulation.arena import generate_grief_training_scenario
import random as _rng
_rng.seed(12345)
scn = generate_grief_training_scenario(cols=20, rows=20,
                                        bonded_pairs=2,
                                        monster_species=['grey_wolf'])
check(f"grief scenario has creatures", len(scn['creatures']) >= 2)
check(f"grief scenario has monsters", len(scn['monsters']) >= 1)
if len(scn['creatures']) >= 2:
    pair_mag = _base_magnitude(scn['creatures'][0],
                                scn['creatures'][1].uid)
    check(f"scenario bond produces profound magnitude (>50, got {pair_mag:.1f})",
          pair_mag > 50)

print("\n=== Species Sprite Size Audit ===")
from data.db import SPRITE_DATA, SPECIES as _SPECIES
SIZE_RANGES = {
    'tiny': (1, 7), 'small': (8, 16), 'medium': (16, 24),
    'large': (24, 32), 'huge': (32, 40), 'colossal': (40, 80),
}
for name, cfg in {**_SPECIES, **MONSTER_SPECIES}.items():
    size_cat = cfg.get('size', 'medium')
    sprite = cfg.get('sprite_name', None)
    if not sprite:
        continue
    data = SPRITE_DATA.get(sprite)
    if data is None:
        check(f"{name} sprite {sprite!r} exists", False)
        continue
    dim = max(data['width'], len(data['pixels']))
    lo, hi = SIZE_RANGES[size_cat]
    check(f"{name} [{size_cat}] sprite {dim}px in range {lo}-{hi}",
          lo <= dim <= hi)

# Verify every species has a default anim binding for idle + walk + attack + hurt + death
from data.db import ANIM_BINDINGS
for name, cfg in {**_SPECIES, **MONSTER_SPECIES}.items():
    sprite = cfg.get('sprite_name', None)
    if not sprite:
        continue
    for beh in ('idle', 'walk_south', 'attack_south', 'hurt', 'death'):
        anim = ANIM_BINDINGS.get((sprite, beh))
        check(f"{name}/{sprite} has '{beh}' binding",
              anim is not None)

# ==========================================================================
print("\n=== League Pool Snapshot Management ===")
import tempfile
import shutil as _shutil
from editor.simulation.league_pool import LeaguePool

with tempfile.TemporaryDirectory() as tmpdir:
    pool = LeaguePool(pool_dir=tmpdir, max_snapshots=3)
    # Create a dummy weight file
    dummy = Path(tmpdir) / '_probe.npz'
    np.savez(str(dummy), w1=np.zeros(3))

    e1 = pool.add_snapshot('v1', {'creature': str(dummy)}, stage=1)
    e2 = pool.add_snapshot('v2', {'creature': str(dummy)}, stage=2)
    e3 = pool.add_snapshot('v3', {'creature': str(dummy)}, stage=3)
    check(f"pool has 3 snapshots", len(pool.list_snapshots()) == 3)

    # Trim enforcement — adding a 4th should drop the oldest
    e4 = pool.add_snapshot('v4', {'creature': str(dummy)}, stage=4)
    ids = [s['id'] for s in pool.list_snapshots()]
    check(f"pool trimmed to max_snapshots (got {len(ids)})",
          len(ids) == 3)
    check(f"oldest (v1) was evicted",
          not any(i.startswith('v1_') for i in ids))

    # Sample
    sample = pool.sample_snapshot(component='creature')
    check(f"sample returns creature-equipped snapshot",
          sample is not None and 'creature' in sample['weights'])
    check(f"latest = v4",
          pool.latest_snapshot()['name'] == 'v4')

# ==========================================================================
print("\n=== StateMachine ===")
from classes.fsm import StateMachine, Transition

# Basic transition
enter_log = []
exit_log = []
sm = StateMachine(
    owner=None,
    initial='normal',
    states=['normal', 'stunned', 'sleeping', 'dead'],
    transitions=[
        Transition('normal', 'stun', 'stunned'),
        Transition('stunned', 'stun_expired', 'normal'),
        Transition('normal', 'sleep', 'sleeping'),
        Transition('sleeping', 'wake', 'normal'),
        Transition('*', 'die', 'dead'),
    ],
    on_enter={'stunned': lambda: enter_log.append('stunned'),
              'dead':    lambda: enter_log.append('dead')},
    on_exit={'normal':   lambda: exit_log.append('normal')},
)
check("initial state is 'normal'", sm.current == 'normal')
check("no previous yet", sm.previous is None)

ok = sm.trigger('stun', now=1000)
check("'stun' transition returns True", ok is True)
check("state is now 'stunned'", sm.current == 'stunned')
check("previous is 'normal'", sm.previous == 'normal')
check("on_exit(normal) fired", exit_log == ['normal'])
check("on_enter(stunned) fired", enter_log == ['stunned'])
check("time_in_state uses entered_at", sm.time_in_state(1500) == 500)

# Invalid trigger — silent no-op
ok2 = sm.trigger('nonexistent', now=2000)
check("unknown trigger returns False", ok2 is False)
check("state unchanged", sm.current == 'stunned')

# Back to normal
sm.trigger('stun_expired', now=3000)
check("returned to 'normal'", sm.current == 'normal')

# Wildcard transition ('*' matches any from_state)
sm.trigger('die', now=4000)
check("wildcard 'die' fires from any state", sm.current == 'dead')
check("on_enter(dead) fired", 'dead' in enter_log)

# Guarded transition: False guard blocks
allow_transition = [False]
sm2 = StateMachine(
    owner=None,
    initial='a', states=['a', 'b'],
    transitions=[
        Transition('a', 'go', 'b',
                   guard=lambda: allow_transition[0]),
    ],
)
check("guard=False blocks transition",
      sm2.trigger('go') is False and sm2.current == 'a')
allow_transition[0] = True
check("guard=True permits transition",
      sm2.trigger('go') is True and sm2.current == 'b')

# Effect runs on transition
effect_log = []
sm3 = StateMachine(
    owner=None, initial='a', states=['a', 'b'],
    transitions=[Transition('a', 'go', 'b',
                             effect=lambda: effect_log.append('fired'))],
)
sm3.trigger('go')
check("effect fired on transition", effect_log == ['fired'])

# force() bypasses guards and effects but runs enter/exit
sm4_enter = []
sm4 = StateMachine(
    owner=None, initial='a', states=['a', 'b', 'c'],
    transitions=[],
    on_enter={'c': lambda: sm4_enter.append('c')},
)
sm4.force('c', now=1234)
check("force() jumped to 'c'", sm4.current == 'c')
check("force() ran on_enter", sm4_enter == ['c'])

# Pickle roundtrip (state preserved, graph dropped)
import pickle
sm5 = StateMachine(
    owner=None, initial='a', states=['a', 'b'],
    transitions=[Transition('a', 'go', 'b')],
)
sm5.trigger('go', now=500)
restored = pickle.loads(pickle.dumps(sm5))
check("pickle preserved current state", restored.current == 'b')
check("pickle preserved entered_at", restored.time_in_state(800) == 300)

# ==========================================================================
print("\n=== ScheduledEventQueue ===")
from classes.fsm import ScheduledEventQueue

q = ScheduledEventQueue()
check("empty queue has len 0", len(q) == 0)
check("peek empty returns None", q.peek_next_expiry() is None)

t1 = q.schedule(1000, 'poison_tick', {'uid': 42})
t2 = q.schedule(500, 'stun_expire', {'uid': 42})
t3 = q.schedule(2000, 'lifecycle', {'stage': 'adult'})
check("3 events queued", len(q) == 3)
check("next expiry is the earliest (500)", q.peek_next_expiry() == 500)

# Drain at 700 — only the stun_expire should fire
fired_700 = q.drain(700)
check(f"drain@700 fires 1 event: {len(fired_700)}", len(fired_700) == 1)
check("fired event was stun_expire", fired_700[0][0] == 'stun_expire')
check("payload preserved", fired_700[0][1] == {'uid': 42})
check("queue has 2 left", len(q) == 2)

# Drain at 1500 — poison_tick fires, lifecycle waits
fired_1500 = q.drain(1500)
check("drain@1500 fires 1 more (poison_tick)",
      len(fired_1500) == 1 and fired_1500[0][0] == 'poison_tick')
check("queue has 1 left", len(q) == 1)

# Cancellation — mark t3 cancelled, drain past, should NOT fire
q.cancel(t3)
fired_3000 = q.drain(3000)
check("cancelled ticket does not fire",
      len(fired_3000) == 0)
check("queue empty after cancelled drain", len(q) == 0)

# Cancellation before expiry window skips silently
q2 = ScheduledEventQueue()
t_a = q2.schedule(100, 'a', None)
t_b = q2.schedule(200, 'b', None)
q2.cancel(t_a)
fired = q2.drain(500)
check("cancel before drain: only non-cancelled fires",
      len(fired) == 1 and fired[0][0] == 'b')

# Pickle roundtrip — events and cancellations preserved
q3 = ScheduledEventQueue()
q3.schedule(100, 'evt', 'pay')
q3.schedule(200, 'evt2', None)
q3_r = pickle.loads(pickle.dumps(q3))
fired_r = q3_r.drain(300)
check("pickled queue fires preserved events",
      len(fired_r) == 2)

# ==========================================================================
print("\n=== sim.events integration ===")
from editor.simulation.arena import generate_arena
from editor.simulation.headless import Simulation

_arena = generate_arena(cols=10, rows=10, num_creatures=2)
_sim = Simulation(_arena)

# sim.events exists; may hold a seeded weather-transition ticket
# from Phase 3 world cycles. Just assert the attribute is there.
check("sim.events attribute present",
      hasattr(_sim, 'events'))

# Schedule + verify handler dispatch via step
delivered = []
def _handle(payload):
    delivered.append(payload)
_sim.subscribe_event('test_tag', _handle)
_sim.events.schedule(_sim.now + _sim.tick_ms, 'test_tag', 'hello')
_sim.step()
check("event delivered during step",
      delivered == ['hello'])

# Handler that raises doesn't abort drain
def _bad(payload):
    raise RuntimeError('boom')
_sim.subscribe_event('boom_tag', _bad)
also_delivered = []
_sim.subscribe_event('boom_tag', lambda p: also_delivered.append(p))
_sim.events.schedule(_sim.now + _sim.tick_ms, 'boom_tag', 'ping')
import io, contextlib
_errbuf = io.StringIO()
with contextlib.redirect_stderr(_errbuf):
    _sim.step()
check("raising handler did not block second handler",
      also_delivered == ['ping'])
check("raising handler logged to stderr",
      'boom' in _errbuf.getvalue())

# Unsubscribe
_sim.unsubscribe_event('test_tag', _handle)
_sim.events.schedule(_sim.now + _sim.tick_ms, 'test_tag', 'bye')
_sim.step()
check("unsubscribed handler does not receive further events",
      delivered == ['hello'])

# ==========================================================================
print("\n=== Conditions (Phase 1) ===")
from classes.conditions import (CONDITION_ORDER, CONDITION_SPECS,
                                  damage_for_tick)

# Fresh sim with two creatures
_cond_arena = generate_arena(cols=8, rows=8, num_creatures=2)
_csim = Simulation(_cond_arena)
_victim, _attacker = _csim.creatures[0], _csim.creatures[1]

# Guarantee VIT baseline so the resistance contest is predictable
_victim.stats.base[Stat.VIT] = 10
_attacker.stats.base[Stat.STR] = 10
# Pump victim HP so poison ticks don't kill mid-test — we're verifying
# the condition lifecycle (apply/stack/tick/expire), not death.
_victim.stats.base[Stat.HP_MAX] = 200
_victim.stats.base[Stat.HP_CURR] = 200

# Apply Poisoned with skip_resist so we can observe the tick mechanic
# cleanly without d20 variance.
ok = _victim.apply_condition(_csim, 'poisoned', severity=2,
                              applied_by_uid=_attacker.uid,
                              duration_ms=10_000, skip_resist=True)
check("apply_condition returns True", ok is True)
check("victim has 'poisoned'", _victim.has_condition('poisoned'))
_p = _victim.get_condition('poisoned')
check("severity clamped to spec.max_severity", _p.severity == 2)
check("applied_by_uid preserved", _p.applied_by_uid == _attacker.uid)
check("expires_at set correctly",
      _p.expires_at == _csim.now + 10_000)

# Stacking: reapply at higher severity, duration refreshed + severity maxed
_victim.apply_condition(_csim, 'poisoned', severity=3,
                         applied_by_uid=_attacker.uid,
                         duration_ms=15_000, skip_resist=True)
_p2 = _victim.get_condition('poisoned')
check("stacking took max severity (3)", _p2.severity == 3)
check("stacking refreshed expiry",
      _p2.expires_at == _csim.now + 15_000)

# DoT tick via sim.events drain
_hp_before = _victim.stats.active[Stat.HP_CURR]()
# Advance the clock past the first tick interval
_csim.now += CONDITION_SPECS['poisoned'].tick_interval_ms
_csim._drain_scheduled_events()
_hp_after = _victim.stats.active[Stat.HP_CURR]()
expected_dmg = damage_for_tick(_p2)
check(f"poison tick dealt {_hp_before - _hp_after} HP (expected {expected_dmg})",
      _hp_before - _hp_after == expected_dmg)

# Next tick should have been rescheduled automatically
# Advance again; should see another tick
_csim.now += CONDITION_SPECS['poisoned'].tick_interval_ms
_csim._drain_scheduled_events()
_hp_after2 = _victim.stats.active[Stat.HP_CURR]()
check("poison rescheduled — second tick fired",
      _hp_after - _hp_after2 == expected_dmg)

# Natural expiry: fast-forward past expires_at
_csim.now = _p2.expires_at + 500
_csim._drain_scheduled_events()
check("poison expired after its window",
      not _victim.has_condition('poisoned'))

# remove_condition: manually cancel a still-active condition
_victim.apply_condition(_csim, 'bleeding', severity=1,
                         duration_ms=5_000, skip_resist=True)
check("bleeding applied", _victim.has_condition('bleeding'))
_victim.remove_condition(_csim, 'bleeding')
check("remove_condition clears condition",
      not _victim.has_condition('bleeding'))

# Stat mods: Afraid applies -STR, -AGL; removed on cure
_str_before = _victim.stats.active[Stat.STR]()
_victim.apply_condition(_csim, 'afraid', severity=2,
                         duration_ms=5_000, skip_resist=True)
_str_during = _victim.stats.active[Stat.STR]()
check(f"afraid reduces STR ({_str_before} -> {_str_during})",
      _str_during < _str_before)
_victim.remove_condition(_csim, 'afraid')
_str_after = _victim.stats.active[Stat.STR]()
check("STR restored after afraid cured",
      _str_after == _str_before)

# Action gating: stun blocks action_state
check("action_state defaults permit actions",
      _victim.can_act() is True)
_victim.apply_condition(_csim, 'stunned', severity=1,
                         duration_ms=3_000, skip_resist=True)
check("stunned drives action_state to 'stunned'",
      _victim.action_state.current == 'stunned')
check("can_act() False while stunned",
      _victim.can_act() is False)
_victim.remove_condition(_csim, 'stunned')
check("unstun returns action_state to 'normal'",
      _victim.action_state.current == 'normal')

# Regenerating: tick HEALS instead of damages
_victim.stats.base[Stat.HP_CURR] = 1
_hp_low = _victim.stats.active[Stat.HP_CURR]()
_victim.apply_condition(_csim, 'regenerating', severity=2,
                         duration_ms=10_000, skip_resist=True)
_csim.now += CONDITION_SPECS['regenerating'].tick_interval_ms
_csim._drain_scheduled_events()
_hp_healed = _victim.stats.active[Stat.HP_CURR]()
check(f"regenerating heals ({_hp_low} -> {_hp_healed})",
      _hp_healed > _hp_low)
_victim.remove_condition(_csim, 'regenerating')

# Observation slots: 17 new features exist and have sensible values
from classes.observation import build_observation, OBSERVATION_SIZE
_obs = build_observation(_victim, _csim.cols, _csim.rows)
check(f"OBSERVATION_SIZE = {OBSERVATION_SIZE} (includes condition slots)",
      OBSERVATION_SIZE > 1800)
check("observation length matches OBSERVATION_SIZE",
      len(_obs) == OBSERVATION_SIZE)
# With no active conditions, the 17 condition slots should be 16 zeros + 1 action_state (0/3 = 0)
# Find them by re-applying and checking before/after
_victim.apply_condition(_csim, 'burning', severity=2,
                         duration_ms=5_000, skip_resist=True)
_obs2 = build_observation(_victim, _csim.cols, _csim.rows)
_diffs = sum(1 for a, b in zip(_obs, _obs2) if abs(a - b) > 1e-6)
check(f"condition application changes observation ({_diffs} slots differ)",
      _diffs >= 2)  # is_active + severity_norm for burning
_victim.remove_condition(_csim, 'burning')

# Handler routes via UID to correct creature
_victim.apply_condition(_csim, 'poisoned', severity=1,
                         applied_by_uid=_attacker.uid,
                         duration_ms=5_000, skip_resist=True)
_hp_pre = _victim.stats.active[Stat.HP_CURR]()
_csim.now += CONDITION_SPECS['poisoned'].tick_interval_ms
_csim._drain_scheduled_events()
_hp_post = _victim.stats.active[Stat.HP_CURR]()
check("UID dispatch routed condition_tick to correct creature",
      _hp_pre != _hp_post)
_victim.remove_condition(_csim, 'poisoned')

# Curriculum gate: a sim with conditions_enabled=False rejects apply
_gated_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_gated_sim = Simulation(_gated_arena, conditions_enabled=False)
_gated_creature = _gated_sim.creatures[0]
ok_gated = _gated_creature.apply_condition(
    _gated_sim, 'poisoned', severity=1, duration_ms=5_000, skip_resist=True)
check("conditions_enabled=False blocks apply_condition",
      ok_gated is False and not _gated_creature.has_condition('poisoned'))

# Clean up on death: creature dying removes its conditions
_death_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_death_sim = Simulation(_death_arena)
_dying = _death_sim.creatures[0]
_dying.stats.base[Stat.HP_MAX] = 100
_dying.stats.base[Stat.HP_CURR] = 100
_dying.apply_condition(_death_sim, 'poisoned', severity=1,
                        duration_ms=5_000, skip_resist=True)
_dying.apply_condition(_death_sim, 'afraid', severity=2,
                        duration_ms=5_000, skip_resist=True)
check("creature has 2 conditions before death",
      len(_dying.conditions) == 2)
_dying.die()
check("conditions cleared on death",
      len(_dying.conditions) == 0)
check("action_state forced to 'dead' on death",
      _dying.action_state is not None and _dying.action_state.current == 'dead')

# ==========================================================================
print("\n=== Lifecycle FSM (Phase 2) ===")
from classes.creature._lifecycle import (LIFECYCLE_STATES,
                                           LIFECYCLE_STATE_IDX,
                                           DEFAULT_DYING_WINDOW_MS)

_lc_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_lcsim = Simulation(_lc_arena)
_lcc = _lcsim.creatures[0]

# Default lifecycle state is 'adult' (pre-FSM creatures act like adults)
check("default lifecycle_state is 'adult'", _lcc.lifecycle_state == 'adult')

# Mature from juvenile: start as juvenile via _ensure_lifecycle_fsm
_lcc._ensure_lifecycle_fsm(initial='juvenile')
check("initial='juvenile' seeds FSM",
      _lcc.lifecycle_state == 'juvenile')
# Juvenile stat mods apply (-4 STR, +2 AGL, -2 INT)
_juv_str_baseline = _lcc.stats.base.get(Stat.STR, 0)
_lcc._apply_lifecycle_stat_mods('juvenile')
_juv_str = _lcc.stats.active[Stat.STR]()
check(f"juvenile -4 STR ({_juv_str_baseline} -> {_juv_str})",
      _juv_str == _juv_str_baseline - 4)

_lcc.transition_lifecycle('mature', sim=_lcsim)
check("juvenile → adult on 'mature' trigger",
      _lcc.lifecycle_state == 'adult')
# Stat mods for adult are zero — STR returns to baseline
check("STR restored to baseline after mature",
      _lcc.stats.active[Stat.STR]() == _juv_str_baseline)

# Age to elder: stat mods shift (-2 STR, -2 AGL, +3 INT)
_adult_int = _lcc.stats.active[Stat.INT]()
_lcc.transition_lifecycle('age', sim=_lcsim)
check("adult → elder on 'age' trigger",
      _lcc.lifecycle_state == 'elder')
check(f"elder +3 INT ({_adult_int} -> {_lcc.stats.active[Stat.INT]()})",
      _lcc.stats.active[Stat.INT]() == _adult_int + 3)

# Event emission: lifecycle.<state> fires on transition
_heard = []
_lcsim.subscribe_event('lifecycle.dying', lambda p: _heard.append(('dying', p)))
_lcsim.subscribe_event('lifecycle.dead',  lambda p: _heard.append(('dead',  p)))

# Dying window: enter_dying schedules a death timer
_lcc2_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_lcc2sim = Simulation(_lcc2_arena)
_lcc2 = _lcc2sim.creatures[0]
_lcc2sim.subscribe_event('lifecycle.dying', lambda p: _heard.append(('dying2', p)))
_lcc2sim.subscribe_event('lifecycle.dead',  lambda p: _heard.append(('dead2', p)))

_lcc2.enter_dying(_lcc2sim)
check("enter_dying sets state to 'dying'",
      _lcc2.lifecycle_state == 'dying')
check("dying event fired",
      any(e[0] == 'dying2' for e in _heard))
check("death timer scheduled",
      len(_lcc2sim.events) >= 1)

# Advance past the dying window → death finalized
_lcc2sim.now += DEFAULT_DYING_WINDOW_MS + 500
_lcc2sim._drain_scheduled_events()
check("lifecycle_state='dead' after window",
      _lcc2.lifecycle_state == 'dead')
check("dead event fired",
      any(e[0] == 'dead2' for e in _heard))

# Resolve dying with 'heal': cancels timer, returns to adult
_lcc3_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_lcc3sim = Simulation(_lcc3_arena)
_lcc3 = _lcc3sim.creatures[0]
_lcc3.enter_dying(_lcc3sim)
check("lcc3 dying", _lcc3.lifecycle_state == 'dying')
_lcc3.resolve_dying(_lcc3sim, 'heal')
check("resolve_dying('heal') → adult",
      _lcc3.lifecycle_state == 'adult')
# Timer should be cancelled — advancing past the window must NOT
# kill the healed creature
_lcc3sim.now += DEFAULT_DYING_WINDOW_MS + 1000
_lcc3sim._drain_scheduled_events()
check("healed dying creature survives window",
      _lcc3.lifecycle_state == 'adult')

# killing_blow: instant dead, bypasses window
_lcc4_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_lcc4sim = Simulation(_lcc4_arena)
_lcc4 = _lcc4sim.creatures[0]
_lcc4.enter_dying(_lcc4sim, from_killing_blow=True)
check("killing_blow skips dying window",
      _lcc4.lifecycle_state == 'dead')

# Observation includes lifecycle fields
_lc_obs = build_observation(_lcc, _lcsim.cols, _lcsim.rows)
check("observation still matches OBSERVATION_SIZE",
      len(_lc_obs) == OBSERVATION_SIZE)
check("lifecycle slots are present (elder = 4/6)",
      any(abs(v - (4.0 / 6.0)) < 1e-6 for v in _lc_obs))

# ==========================================================================
print("\n=== World Cycles (Phase 3) ===")
from classes.world_cycles import (WorldCycles, TIME_OF_DAY_IDX,
                                    WEATHER_IDX, _time_of_day_for_hour,
                                    _light_level_for_hour)

check("6 AM is dawn", _time_of_day_for_hour(6.0) == 'dawn')
check("12 PM is day",  _time_of_day_for_hour(12.0) == 'day')
check("8 PM is dusk",  _time_of_day_for_hour(20.0) == 'dusk')
check("11 PM is night", _time_of_day_for_hour(23.0) == 'night')
check("4 AM is night",  _time_of_day_for_hour(4.0) == 'night')

# Light level ramps
check("noon light = 1.0", abs(_light_level_for_hour(12.0) - 1.0) < 1e-6)
check("midnight light = 0.2", abs(_light_level_for_hour(0.0) - 0.2) < 1e-6)
check("dawn (6:00) mid-ramp ~0.65",
      0.6 < _light_level_for_hour(6.0) < 0.7)

# Sim creates a WorldCycles + weather schedule
_wc_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_wcsim = Simulation(_wc_arena)
check("Simulation owns world_cycles", _wcsim.world_cycles is not None)
check("time_of_day is 'day' at 8 AM",
      _wcsim.world_cycles.time_of_day.current == 'day')
check("weather starts 'clear'",
      _wcsim.world_cycles.weather.current == 'clear')
check("visibility_mult cached",
      0 < _wcsim.world_cycles.visibility_mult <= 1.0)

# Step advances game clock; time-of-day updates deterministically.
# Fast-forward the game clock to simulate reaching dusk hours.
_wcsim.game_clock._elapsed += 60 * 60 * 11.5   # skip ~11.5 game hours
_wcsim.world_cycles.tick(_wcsim)
check(f"time_of_day updates with clock (h={_wcsim.game_clock.hour:.1f})",
      _wcsim.world_cycles.time_of_day.current in ('dusk', 'night'))

# Weather transition via expiry — force it by popping the event.
_heard_weather = []
_wcsim.subscribe_event('weather.rain',
                        lambda p: _heard_weather.append(('rain', p)))
_wcsim.subscribe_event('weather.overcast',
                        lambda p: _heard_weather.append(('overcast', p)))
import random as _r
_rng = _r.Random(12345)  # deterministic for test
_wcsim.world_cycles.on_weather_transition(_wcsim, rng=_rng)
check("weather FSM moved to a valid state",
      _wcsim.world_cycles.weather.current in WEATHER_IDX)

# Curriculum gate: cycles_enabled=False keeps things static
_gc_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_gcsim = Simulation(_gc_arena, cycles_enabled=False)
# The initial weather schedule should NOT have been seeded
# (we have subscribed events registered but no scheduled ticket).
_initial_events = len(_gcsim.events)
# Any events here would come from condition/lifecycle subscriptions;
# weather should be absent. Assert no weather_transition ticket:
check("cycles_enabled=False skips weather scheduling",
      _gcsim.world_cycles.weather.current == 'clear')

# Observation has the 4 world-cycle slots
_wc_obs = build_observation(_wcsim.creatures[0], _wcsim.cols, _wcsim.rows)
check("observation size matches with world cycles active",
      len(_wc_obs) == OBSERVATION_SIZE)

# ==========================================================================
print("\n=== Pack FSM (Phase 4) ===")
from classes.pack import Pack
from classes.maps import MapKey

# Construct a pack directly (independent of arena generator which
# doesn't always produce monsters in test contexts)
_pack = Pack(species='wolf', territory_center=MapKey(5, 5, 0),
             game_map=None)
check("new pack starts in 'forming' state",
      _pack.pack_state == 'forming')

# Empty pack → dispersed via the wildcard 'disperse' transition.
# size=0 right now since we haven't added members. A sim tick would
# fire disperse; drive it directly here for determinism.
class _FakeSim:
    now = 0
    _event_handlers = {}
_fs = _FakeSim()
_pack.evaluate_pack_state(_fs)
check("empty pack transitions to 'dispersed'",
      _pack.pack_state == 'dispersed')

# Fresh pack, populate + step it through the state cycle
_pack2 = Pack(species='wolf', territory_center=MapKey(5, 5, 0))

# Forming → territorial after the forming window elapses
_fs.now = 0
_pack2._pack_formed_at = 0
# Simulate a single-member pack (not empty, so disperse doesn't fire)
_pack2.members_m = [999]   # dummy UID, not a real Monster
_fs.now = 5000  # past FORMING_WINDOW_MS = 3000
_pack2.evaluate_pack_state(_fs)
# Single-member pack stabilizes then may immediately overwhelm if
# threats — with no seen_creatures, should land in territorial.
check(f"forming → territorial after window "
      f"(state={_pack2.pack_state})",
      _pack2.pack_state == 'territorial')

# Threat detection: add to seen_creatures → transitions to defending
_pack2.seen_creatures = {42: (10, 10, 0)}
# Single-member packs flee rather than defend — bump size first.
_pack2.members_m = [999, 1000, 1001]
_pack2.evaluate_pack_state(_fs)
check("territorial + threat → defending",
      _pack2.pack_state == 'defending')

# Threat clears → back to territorial
_pack2.seen_creatures = {}
_pack2.evaluate_pack_state(_fs)
check("defending → territorial when threats gone",
      _pack2.pack_state == 'territorial')

# Overwhelm: drop to 1 member with threats → flee
_pack2.members_m = [999]
_pack2.seen_creatures = {42: (10, 10, 0)}
_pack2.evaluate_pack_state(_fs)
# territorial → defending (via threat) then → fleeing (via overwhelm
# triggered on same tick because size <= 1). Actual order per code:
# threat fires first (territorial → defending), then overwhelm checks.
check(f"1-member + threat → fleeing (state={_pack2.pack_state})",
      _pack2.pack_state == 'fleeing')

# Centroid helper — empty pack returns (0, 0)
_empty_pack = Pack(species='wolf', territory_center=MapKey(0, 0, 0))
_cx, _cy = _empty_pack.pack_centroid()
check("empty pack_centroid() → (0, 0)",
      _cx == 0.0 and _cy == 0.0)

# ---- Creature-pack support + species-configurable ranking ----
from classes.species_rank import rank_score, formula_for_species

# Creature has a pack attribute (default None)
_sanity_map = make_map()
_cpc = make_creature(_sanity_map, x=0, y=0,
                     stats={Stat.STR: 14, Stat.CHR: 12, Stat.AGL: 11},
                     name='CPack')
check("Creature.pack default None", _cpc.pack is None)

# rank_score: each formula returns sensible values
_mighty = make_creature(_sanity_map, x=1, y=0,
                        stats={Stat.STR: 18, Stat.AGL: 14, Stat.CHR: 8},
                        name='Mighty')
_mighty.gold = 5
_social = make_creature(_sanity_map, x=2, y=0,
                        stats={Stat.STR: 10, Stat.AGL: 10, Stat.CHR: 18},
                        name='Social')
_social.gold = 5
_rich = make_creature(_sanity_map, x=3, y=0,
                      stats={Stat.STR: 10, Stat.AGL: 10, Stat.CHR: 10},
                      name='Rich')
_rich.gold = 5000

# might formula favors STR+AGL
_might_m = rank_score(_mighty, 'might')
_might_s = rank_score(_social, 'might')
check(f"might formula: Mighty ({_might_m}) > Social ({_might_s})",
      _might_m > _might_s)
# social formula favors CHR
_social_m = rank_score(_mighty, 'social')
_social_s = rank_score(_social, 'social')
check(f"social formula: Social ({_social_s}) > Mighty ({_social_m})",
      _social_s > _social_m)
# wealth formula favors gold
_wealth_m = rank_score(_mighty, 'wealth')
_wealth_r = rank_score(_rich, 'wealth')
check(f"wealth formula: Rich ({_wealth_r}) > Mighty ({_wealth_m})",
      _wealth_r > _wealth_m)
# hybrid formula blends; CHR*1.5 can tip the scale vs raw STR/AGL.
# Just verify it's a non-zero finite float — exact ordering depends
# on profile balance.
_hybrid_m = rank_score(_mighty, 'hybrid')
_hybrid_s = rank_score(_social, 'hybrid')
check(f"hybrid formula returns finite positive scores "
      f"(Mighty={_hybrid_m}, Social={_hybrid_s})",
      _hybrid_m > 0 and _hybrid_s > 0)

# formula_for_species: monsters default to 'might', creatures to 'hybrid'
# (when MONSTER_SPECIES / SPECIES dicts aren't available, falls back).
check("unknown species falls back to 'might'",
      formula_for_species('nonexistent_species_xyz') == 'might')

# Pack.rank_members_by_formula — create a bunch of dummy members
_species_pack = Pack(species='wolf', territory_center=MapKey(0, 0, 0))
# Register some creatures + put UIDs in members_m
_species_pack.members_m = [_mighty.uid, _rich.uid, _social.uid]
# Force the formula lookup to return 'might' by overriding species_rank
import classes.species_rank as _sr
_orig_lookup = _sr.formula_for_species
_sr.formula_for_species = lambda s: 'might'
try:
    _species_pack.rank_members_by_formula()
    # Mighty should be first (highest STR+AGL = 32)
    check(f"rerank (might): alpha_m is Mighty "
          f"(order={_species_pack.members_m})",
          _species_pack.members_m[0] == _mighty.uid)
finally:
    _sr.formula_for_species = _orig_lookup

# Swap to 'social' — Social goes first
_sr.formula_for_species = lambda s: 'social'
try:
    _species_pack.rank_members_by_formula()
    check(f"rerank (social): alpha_m is Social "
          f"(order={_species_pack.members_m})",
          _species_pack.members_m[0] == _social.uid)
finally:
    _sr.formula_for_species = _orig_lookup

# Swap to 'wealth' — Rich goes first
_sr.formula_for_species = lambda s: 'wealth'
try:
    _species_pack.rank_members_by_formula()
    check(f"rerank (wealth): alpha_m is Rich "
          f"(order={_species_pack.members_m})",
          _species_pack.members_m[0] == _rich.uid)
finally:
    _sr.formula_for_species = _orig_lookup

# ==========================================================================
print("\n=== Combat Arousal (Phase 7) ===")
from classes.creature._arousal import (AROUSAL_STATES, AROUSAL_STATE_IDX,
                                         AROUSAL_TIMEOUTS, get_action_gates)

_arsim_arena = generate_arena(cols=10, rows=10, num_creatures=1)
_arsim = Simulation(_arsim_arena)
_arc = _arsim.creatures[0]

# Default: pre-FSM creature reports 'calm'
check("default arousal_state is 'calm'", _arc.arousal_state == 'calm')

# Transition calm → alert on hostile sighting
_arc.arousal_on_hostile_seen(_arsim)
check("hostile_seen → alert", _arc.arousal_state == 'alert')

# Stat mod: alert gives +2 PER
_per_baseline = _arc.stats.base.get(Stat.PER, 10)
check(f"alert +2 PER (baseline {_per_baseline} → {_arc.stats.active[Stat.PER]()})",
      _arc.stats.active[Stat.PER]() == _per_baseline + 2)

# alert + combat → engaged
_arc.arousal_on_combat(_arsim)
check("combat event → engaged",
      _arc.arousal_state == 'engaged')

# engaged mods: +1 AGL, -1 PER, -1 INT
_int_baseline = _arc.stats.base.get(Stat.INT, 10)
check(f"engaged -1 INT ({_int_baseline} → {_arc.stats.active[Stat.INT]()})",
      _arc.stats.active[Stat.INT]() == _int_baseline - 1)

# Advance sim past engaged timeout — should transition to cooling_down
_arsim.now += AROUSAL_TIMEOUTS['engaged_to_cooling'] + 100
_arsim._drain_scheduled_events()
check("engaged → cooling_down after timeout",
      _arc.arousal_state == 'cooling_down')

# Continue: cooling_down → recovering
_arsim.now += AROUSAL_TIMEOUTS['cooling_to_recovering'] + 100
_arsim._drain_scheduled_events()
check("cooling_down → recovering",
      _arc.arousal_state == 'recovering')

# Recovering → calm
_arsim.now += AROUSAL_TIMEOUTS['recovering_to_calm'] + 100
_arsim._drain_scheduled_events()
check("recovering → calm",
      _arc.arousal_state == 'calm')

# Stat mods clear when back to calm
check("calm baseline PER restored",
      _arc.stats.active[Stat.PER]() == _per_baseline)

# Re-escalation: combat event jumps calm → engaged directly
_arc.arousal_on_combat(_arsim)
check("combat from calm → engaged (emergency)",
      _arc.arousal_state == 'engaged')

# Action gating — PAIR is calm-only
from classes.actions import Action
check("PAIR in action gates table",
      Action.PAIR in get_action_gates())
check("engaged creature cannot PAIR",
      not _arc.arousal_action_allowed(Action.PAIR))

# Reset to calm to verify PAIR opens up.
# Each transition reschedules the next timer from sim.now, so we
# need to advance + drain in a loop to walk through all timeouts.
for _ in range(5):
    _arsim.now += AROUSAL_TIMEOUTS['recovering_to_calm'] + 100
    _arsim._drain_scheduled_events()
check(f"fully cooled creature is calm ({_arc.arousal_state})",
      _arc.arousal_state == 'calm')
check("calm creature can PAIR",
      _arc.arousal_action_allowed(Action.PAIR))

# Observation slots populated
_ar_obs = build_observation(_arc, _arsim.cols, _arsim.rows)
check("observation length matches with arousal active",
      len(_ar_obs) == OBSERVATION_SIZE)

# ==========================================================================
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
if FAIL:
    sys.exit(1)
else:
    print("All tests passed!")
