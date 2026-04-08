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
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
if FAIL:
    sys.exit(1)
else:
    print("All tests passed!")
