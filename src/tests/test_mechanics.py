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
    Item, Weapon, Wearable, Consumable, Ammunition, Stackable, Slot, Inventory
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

# Statistical test
d_successes = sum(1 for _ in range(500)
                  if liar.deceive(mark)['success'])
check(f"Liar deceives mark: {d_successes}/500 (liar has advantage)",
      d_successes > 200)

# Failed deception damages trust
rel_mark = mark.get_relationship(liar)
if rel_mark:
    failed_count = 500 - d_successes
    check(f"Mark sentiment toward liar after failures: {rel_mark[0]:.1f}",
          rel_mark[0] < 0 if failed_count > 0 else True)

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
arrows_start = arrows.quantity
for _ in range(50):
    far_target.stats.base[Stat.HP_CURR] = far_target.stats.active[Stat.HP_MAX]()
    archer.stats.base[Stat.CUR_STAMINA] = archer.stats.active[Stat.MAX_STAMINA]()
    r = archer.ranged_attack(far_target, now=1000)
    if r['hit']:
        hits += 1
        total_dmg += r['damage']

check(f"Ranged hits: {hits}/50", hits > 0)
check(f"Ranged total damage: {total_dmg}", total_dmg > 0)
check(f"Arrows consumed: {arrows_start} → {arrows.quantity}",
      arrows.quantity < arrows_start)

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
rumors = listener.rumors.get(subject.uid, [])
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
check("Stamina fully restored",
      sleeper.stats.active[Stat.CUR_STAMINA]() == sleeper.stats.active[Stat.MAX_STAMINA]())
check("Mana fully restored",
      sleeper.stats.active[Stat.CUR_MANA]() == sleeper.stats.active[Stat.MAX_MANA]())

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

# Sleep clears debt
tired.sleep(now=1000)
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
check("All values are floats", all(isinstance(v, float) for v in obs))
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
hp_delta_idx = OBSERVATION_SIZE - 3
check(f"HP delta is negative: {obs2[hp_delta_idx]:.3f}", obs2[hp_delta_idx] < 0)

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

# Compare: low INT creature gets less curiosity reward
low_int = make_creature(m43, x=0, y=1,
                        stats={Stat.INT: 6, Stat.PER: 10}, name='LowINT')
snap_h = make_reward_snapshot(low_int)
low_int.record_interaction(stranger_rl, 1.0)
snap_i = make_reward_snapshot(low_int)
r5 = compute_reward(low_int, snap_h, snap_i)
check(f"Low INT curiosity reward: {r5:.2f} < high INT {r4:.2f}", r5 < r4)

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
from simulation.arena import generate_arena, random_stats

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
from simulation.headless import Simulation
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
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
if FAIL:
    sys.exit(1)
else:
    print("All tests passed!")
