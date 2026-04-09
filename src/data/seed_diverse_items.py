"""
Seed diverse items with varied stat/requirement mixes.
Run from project root: python src/data/seed_diverse_items.py
"""
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
DB_PATH = Path(__file__).parent / 'game.db'


def insert_sprite(con, name, palette, pixels):
    w = len(pixels[0])
    h = len(pixels)
    con.execute(
        'INSERT OR REPLACE INTO sprites (name, palette, pixels, width, height) VALUES (?,?,?,?,?)',
        (name, json.dumps(palette), json.dumps(pixels), w, h))


def item(con, cls, key, name, **kw):
    kw['class'] = cls; kw['key'] = key; kw['name'] = name
    cols = list(kw.keys())
    con.execute(f"INSERT OR REPLACE INTO items ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
                list(kw.values()))


def slots(con, key, slot_list):
    con.execute('DELETE FROM item_slots WHERE item_key=?', (key,))
    for s in slot_list:
        con.execute('INSERT INTO item_slots VALUES (?,?)', (key, s))


def seed():
    con = sqlite3.connect(DB_PATH)

    # ======================================================================
    # SPRITES for new items (8×8)
    # ======================================================================

    P = {  # palettes
        'gold':  {'G': [220,180,40], 'Y': [240,210,80], 'D': [180,140,20]},
        'blue':  {'B': [40,80,200], 'L': [70,120,230], 'D': [20,50,150]},
        'green': {'G': [40,180,40], 'L': [80,220,80], 'D': [20,120,20]},
        'red':   {'R': [200,40,40], 'L': [230,70,70], 'D': [150,20,20]},
        'purple':{'P': [140,40,180], 'L': [170,80,210], 'D': [100,20,140]},
        'iron':  {'S': [160,160,170], 'G': [130,130,140], 'D': [100,100,110], 'L': [190,190,200]},
        'leather':{'B': [130,80,40], 'b': [100,60,30], 'D': [70,40,20]},
        'wood':  {'W': [160,120,60], 'w': [140,100,45], 'D': [110,80,30]},
        'cloth': {'W': [240,235,220], 'G': [200,195,180], 'D': [170,165,150]},
        'magic': {'M': [100,200,255], 'G': [60,150,200], 'D': [40,100,160], 'S': [200,230,255]},
    }

    # Boots
    insert_sprite(con, 'i_boots_strength', P['leather'], [
        '........','..Bb.Bb.','BBbb.BBb','BDDb.BDD','BbDb.BbD','DDDD.DDD','........','........'])
    insert_sprite(con, 'i_boots_speed', P['blue'], [
        '........','..BL.BL.','BBLL.BBL','BDDL.BDD','BLDB.BLD','DDDD.DDD','........','........'])
    insert_sprite(con, 'i_boots_stealth', P['leather'], [
        '........','..bb.bb.','bbbD.bbb','bDDb.bDD','bbDb.bbD','DDDD.DDD','........','........'])

    # Rings
    insert_sprite(con, 'i_ring_poison_res', P['green'], [
        '........','..GGGG..', '.G....G.','.G.LL.G.','.G.LL.G.','.D....D.','..DDDD..','........'])
    insert_sprite(con, 'i_ring_magic_res', P['purple'], [
        '........','..PPPP..', '.P....P.','.P.LL.P.','.P.LL.P.','.D....D.','..DDDD..','........'])
    insert_sprite(con, 'i_ring_luck', P['gold'], [
        '........','..GGGG..', '.G....G.','.G.YY.G.','.G.YY.G.','.D....D.','..DDDD..','........'])
    insert_sprite(con, 'i_ring_strength', P['red'], [
        '........','..RRRR..', '.R....R.','.R.LL.R.','.R.LL.R.','.D....D.','..DDDD..','........'])

    # Amulets
    insert_sprite(con, 'i_amulet_wisdom', P['blue'], [
        '...BB...','..B..B..','.B.LL.B.','B..LL..B','B..LL..B','.B.LL.B.','..BBBB..','........'])
    insert_sprite(con, 'i_amulet_charm', P['gold'], [
        '...GG...','..G..G..','.G.YY.G.','G..YY..G','G..YY..G','.G.YY.G.','..GGGG..','........'])

    # Shields
    insert_sprite(con, 'i_shield_wood', P['wood'], [
        '.WWWWW..','.WwwwW..','.WwDwW..','.WwDwW..','.WwDwW..','.WwwwW..','..WWW...','........'])
    insert_sprite(con, 'i_shield_iron', P['iron'], [
        '.SSSSS..','.SLGLS..','.SGDGS..','.SGDGS..','.SGDGS..','.SLGLS..','..SSS...','........'])

    # Magic weapons
    insert_sprite(con, 'i_staff_magic', P['magic'], [
        '......S.','......M.','.....MG.','....MG..','...MG...','..MG....','..D.....','........'])
    insert_sprite(con, 'i_dagger_venom', P['green'], [
        '......L.','......G.','.....G..','....G...','...G....','..DD....','..D.....','........'])

    # Consumables
    insert_sprite(con, 'm_elixir_giant', P['red'], [
        '..DD....','..DD....','.DRRRD..','.DRLRD..','DRLLLRD.','DRRRRD..','DRRRRD..','.DDDD...'])
    insert_sprite(con, 'm_antidote', P['green'], [
        '..DD....','..DD....','.DGGD...','.DGLD..','DGLLLD..','DGGGD...','DGGGD...','.DDDD...'])
    insert_sprite(con, 'm_scroll_fire', P['red'], [
        '.RRRR...','.R..R...','.R..R...','.RLLR...','.RLLR...','.R..R...','.RRRR...','........'])

    # ======================================================================
    # WEARABLE ITEMS — varied stat mixes
    # ======================================================================

    # -- Boots --
    item(con, 'Wearable', 'boots_strength', 'Boots of Strength',
         description='Heavy iron-shod boots that make you hit harder',
         weight=3.0, value=30, sprite_name='i_boots_strength',
         slot_count=1, durability_max=80, durability_current=80,
         action_word='don', buffs='{"strength": 2, "agility": -1}',
         requirements='{"strength": 10}')
    slots(con, 'boots_strength', ['feet'])

    item(con, 'Wearable', 'boots_speed', 'Boots of Swiftness',
         description='Enchanted boots that quicken your step',
         weight=1.0, value=35, sprite_name='i_boots_speed',
         slot_count=1, durability_max=60, durability_current=60,
         action_word='don', buffs='{"move speed": 1, "agility": 2}')
    slots(con, 'boots_speed', ['feet'])

    item(con, 'Wearable', 'boots_stealth', 'Boots of Shadow',
         description='Soft-soled boots that muffle your footsteps',
         weight=0.8, value=25, sprite_name='i_boots_stealth',
         slot_count=1, durability_max=50, durability_current=50,
         action_word='don', buffs='{"stealth": 3, "detection": 1}')
    slots(con, 'boots_stealth', ['feet'])

    # -- Rings --
    item(con, 'Wearable', 'ring_poison_res', 'Ring of Poison Resistance',
         description='A jade ring that wards against venom',
         weight=0.1, value=45, sprite_name='i_ring_poison_res',
         slot_count=1, durability_max=200, durability_current=200,
         action_word='wear', buffs='{"poison resist": 5}')
    slots(con, 'ring_poison_res', ['ring_l', 'ring_r'])

    item(con, 'Wearable', 'ring_magic_res', 'Ring of Spell Ward',
         description='An amethyst ring that deflects magic',
         weight=0.1, value=50, sprite_name='i_ring_magic_res',
         slot_count=1, durability_max=200, durability_current=200,
         action_word='wear', buffs='{"magic resist": 4, "intelligence": 1}')
    slots(con, 'ring_magic_res', ['ring_l', 'ring_r'])

    item(con, 'Wearable', 'ring_luck', 'Lucky Coin Ring',
         description='A ring forged from a lucky coin — fate smiles on the wearer',
         weight=0.1, value=60, sprite_name='i_ring_luck',
         slot_count=1, durability_max=200, durability_current=200,
         action_word='wear', buffs='{"luck": 3, "loot gini": 0.1}')
    slots(con, 'ring_luck', ['ring_l', 'ring_r'])

    item(con, 'Wearable', 'ring_strength', 'Ring of the Bear',
         description='A blood-red ring that grants brute force',
         weight=0.1, value=40, sprite_name='i_ring_strength',
         slot_count=1, durability_max=200, durability_current=200,
         action_word='wear', buffs='{"strength": 3, "vitality": 1}',
         requirements='{"strength": 8}')
    slots(con, 'ring_strength', ['ring_l', 'ring_r'])

    # -- Amulets --
    item(con, 'Wearable', 'amulet_wisdom', 'Amulet of Wisdom',
         description='A sapphire pendant that sharpens the mind',
         weight=0.2, value=55, sprite_name='i_amulet_wisdom',
         slot_count=1, durability_max=150, durability_current=150,
         action_word='wear', buffs='{"intelligence": 3, "perception": 1, "max mana": 5}')
    slots(con, 'amulet_wisdom', ['neck'])

    item(con, 'Wearable', 'amulet_charm', 'Amulet of Allure',
         description='A golden pendant that makes you irresistibly charming',
         weight=0.2, value=45, sprite_name='i_amulet_charm',
         slot_count=1, durability_max=150, durability_current=150,
         action_word='wear', buffs='{"charisma": 4, "persuasion": 2, "intimidation": -1}')
    slots(con, 'amulet_charm', ['neck'])

    # -- Shields --
    item(con, 'Wearable', 'shield_wood', 'Wooden Shield',
         description='A simple wooden shield — better than nothing',
         weight=4.0, value=10, sprite_name='i_shield_wood',
         slot_count=1, durability_max=60, durability_current=60,
         action_word='raise', buffs='{"block": 2, "armor": 1}')
    slots(con, 'shield_wood', ['hand_l'])

    item(con, 'Wearable', 'shield_iron', 'Iron Shield',
         description='A heavy iron shield that can turn blades',
         weight=7.0, value=30, sprite_name='i_shield_iron',
         slot_count=1, durability_max=120, durability_current=120,
         action_word='raise', buffs='{"block": 4, "armor": 2, "agility": -1}',
         requirements='{"strength": 12}')
    slots(con, 'shield_iron', ['hand_l'])

    # ======================================================================
    # WEAPONS — varied mechanics
    # ======================================================================

    item(con, 'Weapon', 'staff_magic', 'Staff of Sparks',
         description='A crackling staff that channels magical energy',
         weight=2.5, value=40, sprite_name='i_staff_magic',
         slot_count=2, durability_max=80, durability_current=80,
         action_word='channel', damage=3, attack_time_ms=700, range=4,
         hit_dice=4, hit_dice_count=2, directions='["front"]',
         buffs='{"magic damage": 3, "intelligence": 1, "mana regen": 1}',
         requirements='{"intelligence": 12}')
    slots(con, 'staff_magic', ['hand_r', 'hand_l'])

    item(con, 'Weapon', 'dagger_venom', 'Venomous Dagger',
         description='A blade coated in lethal poison',
         weight=1.0, value=25, sprite_name='i_dagger_venom',
         slot_count=1, durability_max=50, durability_current=50,
         action_word='stab', damage=3, attack_time_ms=300, range=1,
         hit_dice=4, hit_dice_count=1, crit_chance_mod=5,
         directions='["front"]',
         status_effect='poison', status_dc=14,
         buffs='{"melee damage": 1}',
         requirements='{"agility": 10}')
    slots(con, 'dagger_venom', ['hand_r'])

    # ======================================================================
    # CONSUMABLES — varied effects
    # ======================================================================

    item(con, 'Consumable', 'elixir_giant', 'Elixir of the Giant',
         description='Temporarily grants enormous strength',
         weight=0.5, value=20, sprite_name='m_elixir_giant',
         max_stack_size=5, quantity=1, action_word='drink',
         duration=30.0, buffs='{"strength": 5, "vitality": 3, "agility": -2}')

    item(con, 'Consumable', 'antidote', 'Antidote',
         description='Cures poison and boosts resistance',
         weight=0.3, value=8, sprite_name='m_antidote',
         max_stack_size=10, quantity=1, action_word='drink',
         duration=60.0, heal_amount=5,
         buffs='{"poison resist": 8}')

    item(con, 'Consumable', 'scroll_fire', 'Scroll of Fireball',
         description='A single-use scroll that casts a devastating fireball',
         weight=0.1, value=30, sprite_name='m_scroll_fire',
         max_stack_size=3, quantity=1, action_word='read',
         duration=0, buffs='{}')

    # ======================================================================
    # CREATURE SPRITES (8×8 front-facing)
    # ======================================================================

    # Human male
    insert_sprite(con, 'c_human_m', {
        'S': [220,190,160], 'H': [80,50,30], 'E': [40,100,180],
        'C': [100,80,60], 'B': [60,60,150],
    }, [
        '..HHH...',
        '.HSSSH..',
        '.SESES..',
        '.SSSSS..',
        '..CSC...',
        '.CCBCC..',
        '..BBB...',
        '.BB.BB..',
    ])

    # Human female
    insert_sprite(con, 'c_human_f', {
        'S': [230,200,170], 'H': [120,60,20], 'E': [40,100,180],
        'C': [180,50,50], 'B': [60,60,150],
    }, [
        '.HHHHH..',
        'HHSSSHH.',
        '.SESES..',
        '.SSSSS..',
        '..CSC...',
        '.CCBCC..',
        '..BBB...',
        '.BB.BB..',
    ])

    # Orc male (green, tusks)
    insert_sprite(con, 'c_orc_m', {
        'S': [80,140,60], 'H': [40,60,30], 'E': [200,50,30],
        'T': [240,230,200], 'A': [60,100,40], 'B': [80,60,40],
    }, [
        '..HHH...',
        '.HSSSH..',
        '.SESES..',
        '.TSSSTSS',
        '..ASA...',
        '.AABAA..',
        '..BBB...',
        '.BB.BB..',
    ])

    # Orc female
    insert_sprite(con, 'c_orc_f', {
        'S': [90,150,70], 'H': [50,70,35], 'E': [200,50,30],
        'T': [240,230,200], 'A': [70,110,50], 'B': [80,60,40],
    }, [
        '.HHHHH..',
        'HHSSSHH.',
        '.SESES..',
        '.TSSST..',
        '..ASA...',
        '.AABAA..',
        '..BBB...',
        '.BB.BB..',
    ])

    # Bug (small, 6×6)
    insert_sprite(con, 'c_bug', {
        'B': [60,40,20], 'S': [100,70,30], 'E': [200,200,50],
        'L': [80,50,20], 'W': [150,120,80],
    }, [
        '..EE..','..SS..','WBSSBL','WBSSBL','..LL..','..L.L.',
    ])

    # Cricket (tiny)
    insert_sprite(con, 'c_cricket', {
        'G': [50,100,30], 'L': [80,140,50], 'E': [200,200,100],
        'W': [100,160,60],
    }, [
        '.EE.','GLLG','WLLW','.LL.','.L.L','.....',
    ])

    # Rat
    insert_sprite(con, 'c_rat', {
        'B': [100,80,60], 'E': [30,30,30], 'T': [180,140,100],
        'N': [200,150,120],
    }, [
        '........','..EBE...','..BBB...','.BBBBT..','BNBBBT..','..BB....','..B.B...','........',
    ])

    # Egg (generic)
    insert_sprite(con, 'e_generic', {
        'W': [240,235,220], 'S': [220,210,190], 'D': [200,190,170],
    }, [
        '..WW....','..WW....','.WWWW...','.WSSWW..','.WSSW...','.WWWW..','..WW....','........',
    ])

    # ======================================================================
    # SPECIES
    # ======================================================================

    # Orc
    con.execute('''INSERT OR REPLACE INTO species
        (name, playable, sprite_name, tile_scale, size, description,
         prudishness, base_move_speed, lifespan, maturity_age, young_max,
         fecundity_peak, fecundity_end, aggression, sociability, territoriality,
         curiosity_modifier, egg_sprite)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('orc', 1, 'c_orc_m', 1.2, 'medium',
         'Brutish green-skinned warriors with tusks',
         0.3, 3.5, 300, 15, 25, 80, 250, 0.7, 0.3, 0.6, -0.1, 'e_generic'))

    # Orc base stats
    for stat, val in [('strength',14),('vitality',13),('agility',8),
                      ('perception',9),('intelligence',7),('charisma',6),('luck',9),('hit dice',8)]:
        con.execute('INSERT OR REPLACE INTO species_stats VALUES (?,?,?)', ('orc', stat, val))

    # Bug (small creature species)
    con.execute('''INSERT OR REPLACE INTO species
        (name, playable, sprite_name, tile_scale, size, description,
         prudishness, base_move_speed, lifespan, maturity_age, young_max,
         fecundity_peak, fecundity_end, aggression, sociability, territoriality,
         curiosity_modifier)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('bug', 0, 'c_bug', 0.5, 'tiny',
         'Small crawling insects',
         0.0, 2.0, 60, 5, 10, 15, 40, 0.2, 0.0, 0.1, 0.3))

    for stat, val in [('strength',3),('vitality',4),('agility',12),
                      ('perception',8),('intelligence',2),('charisma',1),('luck',8),('hit dice',2)]:
        con.execute('INSERT OR REPLACE INTO species_stats VALUES (?,?,?)', ('bug', stat, val))

    # Update human with sprite + egg sprite
    con.execute("UPDATE species SET sprite_name='c_human_m', egg_sprite='e_generic' WHERE name='human'")

    # Human base stats
    for stat, val in [('strength',10),('vitality',10),('agility',10),
                      ('perception',10),('intelligence',10),('charisma',10),('luck',10),('hit dice',6)]:
        con.execute('INSERT OR REPLACE INTO species_stats VALUES (?,?,?)', ('human', stat, val))

    # ======================================================================
    # NPC CREATURES (variants of species)
    # ======================================================================

    # Human NPCs
    con.execute('''INSERT OR REPLACE INTO creatures
        (key, name, title, species, level, sex, age, prudishness,
         behavior, deity, gold, description, cumulative_limit, concurrent_limit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('blacksmith', 'Torvin', 'Blacksmith', 'human', 5, 'male', 45, 0.6,
         'StatWeightedBehavior', 'Verithan', 200,
         'A burly smith who values honest trade', 1, 1))

    for stat, val in [('strength',15),('vitality',13),('intelligence',11),('charisma',9)]:
        con.execute('INSERT OR REPLACE INTO creature_stats VALUES (?,?,?)', ('blacksmith', stat, val))

    con.execute('''INSERT OR REPLACE INTO creatures
        (key, name, title, species, level, sex, age, prudishness,
         behavior, deity, gold, description, cumulative_limit, concurrent_limit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('healer', 'Miriel', 'Healer', 'human', 4, 'female', 32, 0.7,
         'StatWeightedBehavior', 'Solmara', 80,
         'A gentle healer devoted to compassion', 1, 1))

    for stat, val in [('intelligence',15),('charisma',14),('perception',12),('vitality',11)]:
        con.execute('INSERT OR REPLACE INTO creature_stats VALUES (?,?,?)', ('healer', stat, val))

    con.execute('''INSERT OR REPLACE INTO creatures
        (key, name, title, species, level, sex, age, prudishness,
         behavior, deity, gold, description, cumulative_limit, concurrent_limit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('thief', 'Shade', 'Cutpurse', 'human', 3, 'male', 22, 0.2,
         'StatWeightedBehavior', 'Nyssara', 15,
         'A sneaky pickpocket with quick fingers', 1, 1))

    for stat, val in [('agility',16),('perception',14),('charisma',12),('strength',7)]:
        con.execute('INSERT OR REPLACE INTO creature_stats VALUES (?,?,?)', ('thief', stat, val))

    # Orc NPCs
    con.execute('''INSERT OR REPLACE INTO creatures
        (key, name, title, species, level, sex, age, prudishness,
         behavior, deity, gold, description, cumulative_limit, concurrent_limit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('orc_chief', 'Groknak', 'Warchief', 'orc', 7, 'male', 35, 0.2,
         'StatWeightedBehavior', 'Vaelkor', 150,
         'A massive orc who rules through violence', 1, 1))

    for stat, val in [('strength',18),('vitality',16),('charisma',11),('intelligence',8)]:
        con.execute('INSERT OR REPLACE INTO creature_stats VALUES (?,?,?)', ('orc_chief', stat, val))

    con.execute('''INSERT OR REPLACE INTO creatures
        (key, name, title, species, level, sex, age, prudishness,
         behavior, deity, gold, description, cumulative_limit, concurrent_limit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        ('orc_shaman', 'Zugga', 'Shaman', 'orc', 5, 'female', 40, 0.5,
         'StatWeightedBehavior', 'Mortheus', 60,
         'An orc wise-woman who communes with death', 1, 1))

    for stat, val in [('intelligence',13),('perception',12),('charisma',10),('vitality',14)]:
        con.execute('INSERT OR REPLACE INTO creature_stats VALUES (?,?,?)', ('orc_shaman', stat, val))

    # Bug NPCs (generic, many allowed)
    con.execute('''INSERT OR REPLACE INTO creatures
        (key, name, title, species, level, sex, age,
         behavior, description, cumulative_limit, concurrent_limit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        ('cricket', 'Cricket', 'Cricket', 'bug', 1, None, 10,
         'RandomWanderBehavior', 'A chirping cricket', -1, 10))

    con.execute('''INSERT OR REPLACE INTO creatures
        (key, name, title, species, level, sex, age,
         behavior, description, cumulative_limit, concurrent_limit)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        ('rat', 'Rat', 'Rat', 'bug', 2, None, 15,
         'StatWeightedBehavior', 'A scurrying rat with beady eyes', -1, 8))

    for stat, val in [('strength',5),('vitality',6),('agility',14),('perception',12)]:
        con.execute('INSERT OR REPLACE INTO creature_stats VALUES (?,?,?)', ('rat', stat, val))

    con.commit()
    con.close()

    print('Seeded diverse content:')
    print('  Items:')
    print('    3 boots (strength/speed/stealth)')
    print('    4 rings (poison res, magic res, luck, strength)')
    print('    2 amulets (wisdom, charm)')
    print('    2 shields (wood, iron)')
    print('    2 weapons (magic staff, venom dagger)')
    print('    3 consumables (giant elixir, antidote, fire scroll)')
    print('  Species:')
    print('    orc (strong, aggressive, STR 14)')
    print('    bug (tiny, fast, AGL 12)')
    print('    human (updated with sprite + stats)')
    print('  NPCs:')
    print('    blacksmith Torvin (human, STR 15, trader)')
    print('    healer Miriel (human, INT 15, compassionate)')
    print('    thief Shade (human, AGL 16, sneaky)')
    print('    warchief Groknak (orc, STR 18, violent)')
    print('    shaman Zugga (orc, INT 13, death-worshipper)')
    print('    cricket (bug, ambient, unlimited spawns)')
    print('    rat (bug, scavenger, unlimited)')
    print('  Sprites: 7 creature + 1 egg + 16 item = 24 new')


if __name__ == '__main__':
    seed()
