"""
Seed game content: tiles, sprites, items, animations.
Run from src/:  python data/seed_content.py
"""
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
DB_PATH = Path(__file__).parent / 'game.db'


def insert_sprite(con, name, palette, pixels, width=None, height=None):
    """Insert a sprite. Width auto-detected from first row."""
    if width is None:
        width = len(pixels[0])
    if height is None:
        height = len(pixels)
    con.execute(
        'INSERT OR REPLACE INTO sprites (name, palette, pixels, width, height) VALUES (?,?,?,?,?)',
        (name, json.dumps(palette), json.dumps(pixels), width, height)
    )


def insert_item(con, cls, key, name, **kwargs):
    """Insert an item with arbitrary columns."""
    kwargs['class'] = cls
    kwargs['key'] = key
    kwargs['name'] = name
    cols = list(kwargs.keys())
    vals = list(kwargs.values())
    placeholders = ','.join(['?'] * len(cols))
    con.execute(f"INSERT OR REPLACE INTO items ({','.join(cols)}) VALUES ({placeholders})", vals)


def insert_slots(con, item_key, slots):
    """Insert item_slots for an equippable."""
    con.execute('DELETE FROM item_slots WHERE item_key=?', (item_key,))
    for slot in slots:
        con.execute('INSERT INTO item_slots VALUES (?,?)', (item_key, slot))


def seed():
    con = sqlite3.connect(DB_PATH)

    # ======================================================================
    # TILE SPRITES
    # ======================================================================

    # Grass — green tones
    insert_sprite(con, 't_grass', {
        'G': [34, 139, 34], 'g': [50, 160, 50], 'D': [28, 120, 28],
        'y': [80, 170, 40], '.': [40, 145, 35],
    }, [
        'GgG.gDGgG.gDGgGg',
        'g.Gg.gG.gGg.Dg.g',
        'GDg.GgDgG.gGg.Gg',
        '.gGg.g.gDg.GDgG.',
        'Gg.DgGg.gGg.gGgD',
        'g.Gg.gGDg.Gg.Dg.',
        'DgG.gGg.gDGg.gGg',
        '.g.DgGg.Gg.gGDg.',
        'GgGg.DgGg.gGg.gG',
        'g.gGg.gGDg.Dg.Gg',
        'GDg.Gg.g.gGg.GgD',
        '.gGg.gDGg.GDg.g.',
        'Gg.DgGg.gGg.gGgG',
        'g.Gg.g.Dg.Gg.Dg.',
        'GgG.gGgDgGDg.gGg',
        'g.gDg.gG.g.gGg.g',
    ])

    # Dirt — brown tones
    insert_sprite(con, 't_dirt', {
        'B': [139, 90, 43], 'b': [160, 110, 60], 'D': [120, 75, 35],
        'd': [150, 100, 50],
    }, [
        'BbBdBDbBdBDbBbBdB',
        'bDBd.bBdBbD.bDBdb',
        'BdbBDbdBdBbBDbdBD',
        'dBbD.bBdbBD.bBbdB',
        'BDbdBDbBdBbBDbdBb',
        'bBbD.bBdbBd.BDbdB',
        'DbdBDbBdBbBDbBdbD',
        'bBbD.bBdbBD.bBbdB',
        'BDbdBDbBdBbBDbdBb',
        'dBbD.bBdbBd.BDbdB',
        'BdbBDbdBdBbBDbdBD',
        'bBbD.bBdbBD.bBbdB',
        'DbdBDbBdBbBDbBdbD',
        'bDBd.bBdBbD.bDBdb',
        'BbBdBDbBdBDbBbBdB',
        'dBbD.bBdbBd.BDbdB',
    ])

    # Sand — yellow tones
    insert_sprite(con, 't_sand', {
        'S': [210, 190, 130], 's': [225, 205, 150], 'D': [195, 175, 115],
        'd': [215, 195, 140],
    }, [
        'SsSdSDsSdSDs.sSdS',
        'sDS..sSdSsD.sDSds',
        'SdsSDs.SdSsSDs.SD',
        'dSsD.sSdsSd.sSsdS',
        'SDsdSDsSdSsSDs.Ss',
        'sSsD.sSdsSd.SDsdS',
        'DsdSDsSdSsSDs.sdD',
        'sSsD.sSdsSd.sSsdS',
        'SDsdSDsSdSsSDs.Ss',
        'dSsD.sSdsSd.SDsdS',
        'SdsSDs.SdSsSDs.SD',
        'sSsD.sSdsSd.sSsdS',
        'DsdSDsSdSsSDs.sdD',
        'sDS..sSdSsD.sDSds',
        'SsSdSDsSdSDs.sSdS',
        'dSsD.sSdsSd.SDsdS',
    ])

    # Water frame 1 — blue tones
    insert_sprite(con, 't_water_01', {
        'W': [30, 100, 200], 'w': [50, 130, 220], 'D': [20, 80, 170],
        'L': [70, 150, 235], '.': [40, 110, 210],
    }, [
        'Ww.WDwW.wWDw.WwWD',
        'wDWw.wWDwWw.DwWw.',
        'W.wWDwW.LwWDw.WwW',
        'wWDw.wLWwWDw.wWDw',
        'DwW.wWDwW.wWLw.WD',
        'wWDw.wWDwWDw.wWDw',
        'W.wWDwW.wWDwL.WwW',
        'wWDw.LwWwWDw.wWDw',
        'DwW.wWDwW.LwWw.WD',
        'wWDw.wWDwWDw.wWDw',
        'W.LwWDwW.wWDw.WwW',
        'wWDw.wWDwWDwL.wWD',
        'DwW.wWDwW.wWDw.WD',
        'wDWw.wWDwWw.DwWw.',
        'Ww.WDLwW.wWDw.WwW',
        'wWDw.wWDwWDw.wWDw',
    ])

    # Water frame 2 — shifted highlights
    insert_sprite(con, 't_water_02', {
        'W': [30, 100, 200], 'w': [50, 130, 220], 'D': [20, 80, 170],
        'L': [70, 150, 235], '.': [40, 110, 210],
    }, [
        'wW.wDWw.WwDW.wWwD',
        'WDwW.WwDWwW.dwWW.',
        'w.WwDWw.LWwDW.wWw',
        'WwDW.WLwWWDw.WwDW',
        'dWw.WwDWw.WwLW.wD',
        'WwDW.WwDWwDW.WwDW',
        'w.WwDWw.WwDWL.wWw',
        'WwDW.LWwWwDW.WwDW',
        'dWw.WwDWw.LWwW.wD',
        'WwDW.WwDWwDW.WwDW',
        'w.LWwDWw.WwDW.wWw',
        'WwDW.WwDWwDWL.WwD',
        'dWw.WwDWw.WwDW.wD',
        'WDwW.WwDWwW.dwWW.',
        'wW.wDLWw.WwDW.wWw',
        'WwDW.WwDWwDW.WwDW',
    ])

    # ======================================================================
    # TILE TEMPLATES
    # ======================================================================

    for key, name, walkable, sprite in [
        ('grass', 'Grass', 1, 't_grass'),
        ('dirt', 'Dirt', 1, 't_dirt'),
        ('sand', 'Sand', 1, 't_sand'),
        ('water', 'Water', 0, 't_water_01'),
    ]:
        con.execute(
            'INSERT OR REPLACE INTO tile_templates (key, name, walkable, sprite_name) VALUES (?,?,?,?)',
            (key, name, walkable, sprite)
        )

    # Water animation
    con.execute('INSERT OR REPLACE INTO animations (name, target_type) VALUES (?,?)',
                ('anim_water', 'tile'))
    con.execute('DELETE FROM animation_frames WHERE animation_name=?', ('anim_water',))
    con.execute('INSERT INTO animation_frames (animation_name, frame_index, sprite_name, duration_ms) VALUES (?,?,?,?)',
                ('anim_water', 0, 't_water_01', 800))
    con.execute('INSERT INTO animation_frames (animation_name, frame_index, sprite_name, duration_ms) VALUES (?,?,?,?)',
                ('anim_water', 1, 't_water_02', 800))
    con.execute('UPDATE tile_templates SET animation_name=? WHERE key=?', ('anim_water', 'water'))

    # ======================================================================
    # ITEM SPRITES — 8×8 compact icons
    # ======================================================================

    # Cotton shirt
    insert_sprite(con, 'i_shirt_cotton', {
        'W': [240, 235, 220], 'G': [200, 195, 180], 'D': [170, 165, 150],
    }, [
        '..WWWW..',
        '.WWWWWW.',
        'GWWWWWWG',
        'DWWWWWWD',
        '.GWWWWG.',
        '.GWWWWG.',
        '.GDWWDG.',
        '..GGGG..',
    ])

    # Cotton trousers
    insert_sprite(con, 'i_trousers_cotton', {
        'B': [100, 90, 70], 'b': [120, 110, 90], 'D': [80, 70, 55],
    }, [
        '.BBBBBB.',
        '.BbBBbB.',
        '.BbBBbB.',
        '.Bb..bB.',
        '.Bb..bB.',
        '.BD..DB.',
        '.BD..DB.',
        '.DD..DD.',
    ])

    # Leather shoes
    insert_sprite(con, 'i_shoes_leather', {
        'B': [100, 60, 30], 'b': [130, 80, 40], 'D': [70, 40, 20],
    }, [
        '........',
        '........',
        '.Bb.Bb..',
        'BBbb.BBb',
        'BDDb.BDD',
        'DDDD.DDD',
        '........',
        '........',
    ])

    # Felt cap
    insert_sprite(con, 'i_cap_felt', {
        'R': [140, 50, 50], 'r': [170, 70, 70], 'D': [110, 35, 35],
    }, [
        '........',
        '..rRRr..',
        '.RrrrrR.',
        '.RRRRRR.',
        'DRRRRRD.',
        'DDDDDDDD',
        '........',
        '........',
    ])

    # Iron helmet
    insert_sprite(con, 'i_helm_iron', {
        'S': [160, 160, 170], 'G': [130, 130, 140], 'D': [100, 100, 110],
        'L': [190, 190, 200],
    }, [
        '..SSSS..',
        '.SLLLLS.',
        '.SGLGLS.',
        'SSSSSSS.',
        'DGGGGGD.',
        'D.GGG.D.',
        '........',
        '........',
    ])

    # Armor upper (breastplate)
    insert_sprite(con, 'i_armor_upper', {
        'S': [160, 160, 170], 'G': [130, 130, 140], 'D': [100, 100, 110],
        'L': [190, 190, 200],
    }, [
        '.SSSSSS.',
        'SLSSSSLS',
        'GSSLSSSG',
        'GSSSSSSG',
        '.GSSLSG.',
        '.GSSSSG.',
        '..GSSG..',
        '..GGGG..',
    ])

    # Armor lower (greaves)
    insert_sprite(con, 'i_armor_lower', {
        'S': [160, 160, 170], 'G': [130, 130, 140], 'D': [100, 100, 110],
    }, [
        '.SSSSSS.',
        '.SGSSGS.',
        '.SG..GS.',
        '.SG..GS.',
        '.SG..GS.',
        '.DG..GD.',
        '.DD..DD.',
        '........',
    ])

    # Short sword
    insert_sprite(con, 'i_sword_short', {
        'S': [180, 180, 195], 'G': [140, 130, 50], 'B': [80, 60, 30],
        'L': [210, 210, 225],
    }, [
        '......L.',
        '.....LS.',
        '....LS..',
        '...LS...',
        '..LS....',
        '.GG.....',
        '.BG.....',
        '........',
    ])

    # Long sword
    insert_sprite(con, 'i_sword_long', {
        'S': [180, 180, 195], 'G': [140, 130, 50], 'B': [80, 60, 30],
        'L': [210, 210, 225],
    }, [
        '.......L',
        '......LS',
        '.....LS.',
        '....LS..',
        '...LS...',
        '..LS....',
        '.GGS....',
        '.BG.....',
    ])

    # Short bow
    insert_sprite(con, 'i_bow_short', {
        'W': [160, 120, 60], 'S': [200, 180, 140], 'T': [120, 90, 40],
    }, [
        '..W.....',
        '.W.S....',
        'W..S....',
        'W...S...',
        'W...S...',
        'W..S....',
        '.W.S....',
        '..W.....',
    ])

    # Long bow
    insert_sprite(con, 'i_bow_long', {
        'W': [160, 120, 60], 'S': [200, 180, 140], 'T': [120, 90, 40],
    }, [
        '...W....',
        '..W.S...',
        '.W..S...',
        'W...S...',
        'W....S..',
        'W...S...',
        '.W..S...',
        '..W.S...',
    ])

    # Arrow
    insert_sprite(con, 'a_arrow', {
        'W': [160, 120, 60], 'S': [180, 180, 195], 'F': [200, 200, 200],
    }, [
        '........',
        '........',
        '......SF',
        '.WWWWWS.',
        '.WWWWWS.',
        '......SF',
        '........',
        '........',
    ])

    # Poison arrow
    insert_sprite(con, 'a_arrow_poison', {
        'W': [160, 120, 60], 'S': [180, 180, 195], 'P': [80, 200, 80],
        'F': [200, 200, 200],
    }, [
        '........',
        '........',
        '......PF',
        '.WWWWWP.',
        '.WWWWWP.',
        '......PF',
        '........',
        '........',
    ])

    # Gold piece
    insert_sprite(con, 'm_gold_piece', {
        'G': [220, 180, 40], 'Y': [240, 210, 80], 'D': [180, 140, 20],
    }, [
        '..GGGG..',
        '.GYYYYG.',
        'GYYGGYYG',
        'GYGDDGYG',
        'GYGDDGYG',
        'GYYGGYYG',
        '.GYYYYG.',
        '..GGGG..',
    ])

    # Health potion
    insert_sprite(con, 'm_potion_health', {
        'R': [200, 40, 40], 'G': [160, 160, 170], 'D': [100, 100, 110],
        'L': [230, 70, 70],
    }, [
        '..GG....',
        '..GG....',
        '.GDDG...',
        '.GRRG...',
        'GRLRRG..',
        'GRRRRG..',
        'GRRRRG..',
        '.GGGG...',
    ])

    # Stamina potion
    insert_sprite(con, 'm_potion_stamina', {
        'Y': [200, 180, 40], 'G': [160, 160, 170], 'D': [100, 100, 110],
        'L': [230, 210, 80],
    }, [
        '..GG....',
        '..GG....',
        '.GDDG...',
        '.GYYG...',
        'GYLYYG..',
        'GYYYYG..',
        'GYYYYG..',
        '.GGGG...',
    ])

    # Mana potion
    insert_sprite(con, 'm_potion_mana', {
        'B': [40, 80, 200], 'G': [160, 160, 170], 'D': [100, 100, 110],
        'L': [70, 120, 230],
    }, [
        '..GG....',
        '..GG....',
        '.GDDG...',
        '.GBBG...',
        'GBLBBG..',
        'GBBBBG..',
        'GBBBBG..',
        '.GGGG...',
    ])

    # Ring of vitality
    insert_sprite(con, 'i_ring_vitality', {
        'G': [220, 180, 40], 'R': [180, 30, 30], 'D': [160, 130, 20],
    }, [
        '........',
        '..GGGG..',
        '.G....G.',
        '.G.RR.G.',
        '.G.RR.G.',
        '.D....D.',
        '..DDDD..',
        '........',
    ])

    # ======================================================================
    # ITEMS
    # ======================================================================

    # --- Clothing ---
    insert_item(con, 'Wearable', 'cotton_shirt', 'Cotton Shirt',
                description='A simple cotton shirt', weight=0.5, value=3,
                sprite_name='i_shirt_cotton', action_word='don',
                slot_count=1, durability_max=50, durability_current=50,
                buffs='{}')
    insert_slots(con, 'cotton_shirt', ['chest'])

    insert_item(con, 'Wearable', 'cotton_trousers', 'Cotton Trousers',
                description='Simple cotton trousers', weight=0.5, value=3,
                sprite_name='i_trousers_cotton', action_word='don',
                slot_count=1, durability_max=50, durability_current=50,
                buffs='{}')
    insert_slots(con, 'cotton_trousers', ['legs'])

    insert_item(con, 'Wearable', 'leather_shoes', 'Leather Shoes',
                description='Sturdy leather shoes', weight=0.8, value=5,
                sprite_name='i_shoes_leather', action_word='don',
                slot_count=1, durability_max=60, durability_current=60,
                buffs='{"move speed": 0}')
    insert_slots(con, 'leather_shoes', ['feet'])

    insert_item(con, 'Wearable', 'felt_cap', 'Felt Cap',
                description='A warm felt cap', weight=0.2, value=2,
                sprite_name='i_cap_felt', action_word='don',
                slot_count=1, durability_max=30, durability_current=30,
                buffs='{}')
    insert_slots(con, 'felt_cap', ['head'])

    # --- Armor ---
    insert_item(con, 'Wearable', 'iron_helmet', 'Iron Helmet',
                description='A solid iron helmet', weight=3.0, value=25,
                sprite_name='i_helm_iron', action_word='don',
                slot_count=1, durability_max=100, durability_current=100,
                buffs='{"armor": 3}',
                requirements='{"strength": 8}')
    insert_slots(con, 'iron_helmet', ['head'])

    insert_item(con, 'Wearable', 'iron_breastplate', 'Iron Breastplate',
                description='Heavy iron armor protecting the upper body', weight=8.0, value=50,
                sprite_name='i_armor_upper', action_word='don',
                slot_count=1, durability_max=120, durability_current=120,
                buffs='{"armor": 5, "agility": -1}',
                requirements='{"strength": 12}')
    insert_slots(con, 'iron_breastplate', ['chest'])

    insert_item(con, 'Wearable', 'iron_greaves', 'Iron Greaves',
                description='Iron leg armor', weight=5.0, value=35,
                sprite_name='i_armor_lower', action_word='don',
                slot_count=1, durability_max=100, durability_current=100,
                buffs='{"armor": 3, "agility": -1}',
                requirements='{"strength": 10}')
    insert_slots(con, 'iron_greaves', ['legs'])

    # --- Weapons ---
    insert_item(con, 'Weapon', 'short_sword', 'Short Sword',
                description='A light, quick blade', weight=2.0, value=15,
                sprite_name='i_sword_short', action_word='slash',
                slot_count=1, durability_max=80, durability_current=80,
                damage=5, attack_time_ms=400, range=1,
                hit_dice=6, hit_dice_count=1,
                directions='["front"]',
                buffs='{"melee damage": 1}')
    insert_slots(con, 'short_sword', ['hand_r'])

    insert_item(con, 'Weapon', 'long_sword', 'Long Sword',
                description='A heavy two-handed blade requiring strength to wield',
                weight=5.0, value=35,
                sprite_name='i_sword_long', action_word='cleave',
                slot_count=2, durability_max=100, durability_current=100,
                damage=8, attack_time_ms=600, range=1,
                hit_dice=8, hit_dice_count=1,
                crit_damage_mod=0.5,
                directions='["front"]',
                buffs='{"melee damage": 2}',
                requirements='{"strength": 12}')
    insert_slots(con, 'long_sword', ['hand_r', 'hand_l'])

    insert_item(con, 'Weapon', 'short_bow', 'Short Bow',
                description='A compact bow for quick shots', weight=1.5, value=12,
                sprite_name='i_bow_short', action_word='loose',
                slot_count=2, durability_max=60, durability_current=60,
                damage=3, attack_time_ms=500, range=6,
                ammunition_type='Arrow',
                directions='["front"]',
                buffs='{}')
    insert_slots(con, 'short_bow', ['hand_r', 'hand_l'])

    insert_item(con, 'Weapon', 'long_bow', 'Long Bow',
                description='A powerful longbow requiring strength to draw',
                weight=2.5, value=25,
                sprite_name='i_bow_long', action_word='loose',
                slot_count=2, durability_max=80, durability_current=80,
                damage=5, attack_time_ms=700, range=10,
                ammunition_type='Arrow',
                directions='["front"]',
                buffs='{}',
                requirements='{"strength": 12}')
    insert_slots(con, 'long_bow', ['hand_r', 'hand_l'])

    # --- Ammunition ---
    insert_item(con, 'Ammunition', 'arrow', 'Arrow',
                description='A standard wooden arrow', weight=0.1, value=1,
                sprite_name='a_arrow',
                max_stack_size=50, quantity=20,
                damage=2, destroy_on_use_probability=0.5,
                recoverable=1, action_word='nock')

    insert_item(con, 'Ammunition', 'poison_arrow', 'Poison Arrow',
                description='An arrow tipped with venom', weight=0.1, value=5,
                sprite_name='a_arrow_poison',
                max_stack_size=20, quantity=5,
                damage=2, destroy_on_use_probability=0.7,
                recoverable=1, action_word='nock',
                status_effect='poison', status_dc=12)

    # --- Stackable ---
    insert_item(con, 'Stackable', 'gold_piece', 'Gold Piece',
                description='A shiny gold coin', weight=0.05, value=10,
                sprite_name='m_gold_piece',
                max_stack_size=99, quantity=1, action_word='spend')

    # --- Consumables ---
    insert_item(con, 'Consumable', 'potion_health', 'Health Potion',
                description='Restores health when consumed', weight=0.3, value=8,
                sprite_name='m_potion_health', action_word='drink',
                max_stack_size=10, quantity=1,
                heal_amount=15, duration=0)

    insert_item(con, 'Consumable', 'potion_stamina', 'Stamina Potion',
                description='Restores stamina when consumed', weight=0.3, value=6,
                sprite_name='m_potion_stamina', action_word='drink',
                max_stack_size=10, quantity=1,
                stamina_restore=20, duration=0)

    insert_item(con, 'Consumable', 'potion_mana', 'Mana Potion',
                description='Restores mana when consumed', weight=0.3, value=10,
                sprite_name='m_potion_mana', action_word='drink',
                max_stack_size=10, quantity=1,
                mana_restore=15, duration=0)

    # --- Ring ---
    insert_item(con, 'Wearable', 'ring_vitality', 'Ring of Vitality',
                description='A gold ring set with a blood-red gem. Enhances vitality.',
                weight=0.1, value=40,
                sprite_name='i_ring_vitality', action_word='wear',
                slot_count=1, durability_max=200, durability_current=200,
                buffs='{"vitality": 2, "max health": 3}')
    insert_slots(con, 'ring_vitality', ['ring_l', 'ring_r'])

    # ======================================================================
    # ECONOMY — raw & processed food, materials, jobs, recipes
    # ======================================================================

    # --- Raw food (harvested from resource tiles) ---
    insert_item(con, 'Stackable', 'food_wheat_raw', 'Wheat',
                description='Sheaves of raw wheat, straight from the field.',
                weight=0.15, value=1.0, max_stack_size=99, quantity=1,
                is_food=0, action_word='gather')
    insert_item(con, 'Stackable', 'food_fish_raw', 'Fish',
                description='A freshly caught fish, still slick with river water.',
                weight=0.4, value=2.0, max_stack_size=20, quantity=1,
                is_food=0, action_word='catch')
    insert_item(con, 'Stackable', 'food_berries_raw', 'Berries',
                description='A handful of wild berries — sweet but quick to spoil.',
                weight=0.1, value=1.0, max_stack_size=50, quantity=1,
                is_food=1, action_word='pick')
    insert_item(con, 'Stackable', 'food_game_raw', 'Raw Game',
                description='A butchered cut of game meat. Best cooked.',
                weight=0.8, value=2.5, max_stack_size=10, quantity=1,
                is_food=0, action_word='take')
    insert_item(con, 'Stackable', 'food_mushrooms_raw', 'Mushrooms',
                description='Woodland mushrooms — earthy, firm, and filling.',
                weight=0.1, value=1.2, max_stack_size=50, quantity=1,
                is_food=1, action_word='forage')

    # --- Processed food (from PROCESS action on crafting tiles) ---
    insert_item(con, 'Consumable', 'food_bread', 'Bread',
                description='A warm, crusty loaf. Sustaining and simple.',
                weight=0.25, value=4.0, max_stack_size=20, quantity=1,
                heal_amount=5, duration=0, is_food=1, action_word='eat')
    insert_item(con, 'Consumable', 'food_cooked_fish', 'Cooked Fish',
                description='Fish grilled over coals. Savory and rich.',
                weight=0.35, value=5.0, max_stack_size=20, quantity=1,
                heal_amount=7, duration=0, is_food=1, action_word='eat')
    insert_item(con, 'Consumable', 'food_jam', 'Berry Jam',
                description='Thick berry preserves, stored in a clay pot.',
                weight=0.3, value=4.0, max_stack_size=10, quantity=1,
                heal_amount=4, duration=0, is_food=1, action_word='eat')
    insert_item(con, 'Consumable', 'food_roast_meat', 'Roast Meat',
                description='A seared, tender cut of roasted game.',
                weight=0.6, value=6.0, max_stack_size=10, quantity=1,
                heal_amount=8, duration=0, is_food=1, action_word='eat')
    insert_item(con, 'Consumable', 'food_dried_mushrooms', 'Dried Mushrooms',
                description='Mushrooms preserved by drying. Keeps for weeks.',
                weight=0.05, value=2.0, max_stack_size=50, quantity=1,
                heal_amount=3, duration=0, is_food=1, action_word='eat')
    insert_item(con, 'Consumable', 'food_stew', 'Hearty Stew',
                description='A rich stew of meat and mushrooms.',
                weight=0.7, value=9.0, max_stack_size=5, quantity=1,
                heal_amount=12, duration=0, is_food=1, action_word='eat')

    # --- Raw materials (harvested from mining/lumbering tiles) ---
    insert_item(con, 'Stackable', 'material_ore_iron', 'Iron Ore',
                description='Chunks of iron-rich ore. Worthless until smelted.',
                weight=1.0, value=2.0, max_stack_size=50, quantity=1,
                action_word='break')
    insert_item(con, 'Stackable', 'material_ore_copper', 'Copper Ore',
                description='Reddish copper ore. Soft but workable.',
                weight=0.9, value=1.5, max_stack_size=50, quantity=1,
                action_word='break')
    insert_item(con, 'Stackable', 'material_coal', 'Coal',
                description='Lumps of black coal. Fuels forges and hearths.',
                weight=0.6, value=1.0, max_stack_size=99, quantity=1,
                action_word='take')
    insert_item(con, 'Stackable', 'material_stone', 'Stone',
                description='A rough chunk of worked stone.',
                weight=2.0, value=0.5, max_stack_size=20, quantity=1,
                action_word='haul')

    # --- Processed materials (from smelting/refining recipes) ---
    insert_item(con, 'Stackable', 'material_ingot_iron', 'Iron Ingot',
                description='A bar of refined iron, ready for the smithy.',
                weight=1.5, value=8.0, max_stack_size=20, quantity=1,
                action_word='carry')
    insert_item(con, 'Stackable', 'material_ingot_copper', 'Copper Ingot',
                description='A bar of refined copper. Trades well.',
                weight=1.4, value=6.0, max_stack_size=20, quantity=1,
                action_word='carry')
    insert_item(con, 'Stackable', 'material_charcoal', 'Charcoal',
                description='Lightweight black fuel — hotter than coal.',
                weight=0.3, value=2.0, max_stack_size=50, quantity=1,
                action_word='pack')

    # --- Shovel (needed for DIG action, was runtime-only before) ---
    insert_item(con, 'Weapon', 'tool_shovel', 'Shovel',
                description='A sturdy digging shovel. Doubles as a club at need.',
                weight=3.0, value=5.0,
                damage=2, range=1, durability_max=150, durability_current=150,
                slot_count=1, action_word='dig')
    insert_slots(con, 'tool_shovel', ['hand_r'])

    # --- Schedules (seeded into schedules table) ---
    import json as _json
    def _schedule(key, name, description, sleep, work, open_):
        con.execute(
            'INSERT OR REPLACE INTO schedules (key, name, description, '
            'sleep_bands, work_bands, open_bands) VALUES (?,?,?,?,?,?)',
            (key, name, description,
             _json.dumps(sleep), _json.dumps(work), _json.dumps(open_))
        )

    _schedule('day_worker', 'Day Worker',
              'Typical dawn-to-dusk schedule: sleep overnight, two work '
              'blocks with a midday break, evening leisure.',
              sleep=[[22.0, 6.0]],
              work=[[8.0, 12.0], [13.0, 17.0]],
              open_=[[6.0, 8.0], [12.0, 13.0], [17.0, 22.0]])
    _schedule('night_worker', 'Night Worker',
              'Dusk-to-dawn schedule for guards and watchmen.',
              sleep=[[8.0, 16.0]],
              work=[[18.0, 24.0], [0.0, 6.0]],
              open_=[[16.0, 18.0], [6.0, 8.0]])
    _schedule('wanderer', 'Wanderer',
              'No set work hours; free to roam during daylight.',
              sleep=[[22.0, 6.0]],
              work=[],
              open_=[[6.0, 22.0]])

    # --- Jobs (seeded into jobs table) ---
    def _job(key, name, description, purpose, wage, stat, level, workplaces, sched):
        con.execute(
            'INSERT OR REPLACE INTO jobs (key, name, description, purpose, '
            'wage_per_tick, required_stat, required_level, workplace_purposes, '
            'schedule_template) VALUES (?,?,?,?,?,?,?,?,?)',
            (key, name, description, purpose, wage, stat, level,
             _json.dumps(workplaces), sched)
        )

    _job('farmer', 'Farmer',
         'Tends fields of wheat and other crops. Up at dawn, in bed by dusk.',
         'farming', 1.0, 'VIT', 8, ['farming'], 'day_worker')
    _job('miner', 'Miner',
         'Works the ore veins. Heavy labor, decent wages.',
         'mining', 1.5, 'STR', 10, ['mining'], 'day_worker')
    _job('crafter', 'Crafter',
         'Turns raw goods into finished wares at the workshop.',
         'crafting', 1.2, 'INT', 10, ['crafting'], 'day_worker')
    _job('trader', 'Trader',
         'Buys and sells at the market. Lives off the spread.',
         'trading', 1.3, 'CHR', 10, ['trading'], 'day_worker')
    _job('hunter', 'Hunter',
         'Stalks game in the wild. Patient, observant, self-reliant.',
         'hunting', 1.1, 'PER', 10, ['hunting'], 'day_worker')
    _job('healer', 'Healer',
         'Tends the sick and channels blessings at the temple.',
         'healing', 1.4, 'INT', 12, ['healing'], 'day_worker')
    _job('guard', 'Guard',
         'Watches the walls by night. Extra pay for the late shift.',
         'guarding', 1.2, 'STR', 10, ['guarding'], 'night_worker')

    # --- Processing recipes (seeded into processing_recipes) ---
    def _recipe(key, name, description, output_key, output_qty, category,
                 ingredients, tile_purpose='crafting', stamina=1):
        con.execute('DELETE FROM processing_recipe_inputs WHERE recipe_key=?', (key,))
        con.execute(
            'INSERT OR REPLACE INTO processing_recipes '
            '(key, name, description, output_item_key, output_quantity, category, '
            'required_tile_purpose, stamina_cost) VALUES (?,?,?,?,?,?,?,?)',
            (key, name, description, output_key, output_qty, category,
             tile_purpose, stamina)
        )
        for ing_key, qty in ingredients.items():
            con.execute(
                'INSERT INTO processing_recipe_inputs '
                '(recipe_key, ingredient_item_key, quantity) VALUES (?,?,?)',
                (key, ing_key, qty)
            )

    _recipe('bake_bread', 'Bake Bread',
            'Turn raw wheat into loaves of bread.',
            'food_bread', 1, 'food',
            {'food_wheat_raw': 2})
    _recipe('cook_fish', 'Cook Fish',
            'Grill raw fish over a hot fire.',
            'food_cooked_fish', 1, 'food',
            {'food_fish_raw': 1})
    _recipe('make_jam', 'Make Jam',
            'Preserve wild berries as thick jam.',
            'food_jam', 1, 'food',
            {'food_berries_raw': 3})
    _recipe('roast_meat', 'Roast Meat',
            'Roast a cut of raw game meat.',
            'food_roast_meat', 1, 'food',
            {'food_game_raw': 1})
    _recipe('dry_mushrooms', 'Dry Mushrooms',
            'Preserve mushrooms by drying.',
            'food_dried_mushrooms', 1, 'food',
            {'food_mushrooms_raw': 2})
    _recipe('make_stew', 'Make Stew',
            'A hearty stew of meat and mushrooms — a full meal.',
            'food_stew', 1, 'food',
            {'food_game_raw': 1, 'food_mushrooms_raw': 1})
    _recipe('smelt_iron', 'Smelt Iron',
            'Refine iron ore into tradeable ingots.',
            'material_ingot_iron', 1, 'material',
            {'material_ore_iron': 2, 'material_coal': 1}, stamina=2)
    _recipe('smelt_copper', 'Smelt Copper',
            'Refine copper ore into ingots.',
            'material_ingot_copper', 1, 'material',
            {'material_ore_copper': 2, 'material_coal': 1}, stamina=2)
    _recipe('burn_charcoal', 'Burn Charcoal',
            'Convert raw stone-like coal into hotter charcoal.',
            'material_charcoal', 2, 'material',
            {'material_coal': 1}, stamina=1)

    # --- Curriculum stages (RL training plan) ---
    # Soft fade design: when a stage activates a new signal, older signals
    # stay on at reduced strength to prevent catastrophic forgetting. Each
    # stage's signal_scales dict is a SUPERSET of the previous stage's,
    # with old signals dropped to ~0.3 of full strength.
    def _stage(num, name, desc, signals, hunger, combat, gestation,
               mappo, es_gens, es_vars, es_steps, ppo, lr=0.0003, ent=0.05,
               resume=None, allowed_actions=None, fatigue_enabled=True):
        con.execute(
            'INSERT OR REPLACE INTO curriculum_stages '
            '(stage_number, name, description, active_signals, signal_scales, '
            'hunger_drain, combat_enabled, gestation_enabled, '
            'mappo_steps, es_generations, es_variants, es_steps, ppo_steps, '
            'learning_rate, ent_coef, resume_from_stage, '
            'allowed_actions, fatigue_enabled) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (num, name, desc,
             _json.dumps(list(signals.keys())),
             _json.dumps(signals),
             1 if hunger else 0, 1 if combat else 0, 1 if gestation else 0,
             mappo, es_gens, es_vars, es_steps, ppo, lr, ent, resume,
             _json.dumps(allowed_actions or []),
             1 if fatigue_enabled else 0)
        )

    # Stage 1: Wander — learn to move purposefully
    # Failed actions are penalized from stage 1 because wall-bashing
    # is the single biggest form of wasted movement. Water danger is
    # also on from day one so non-swimmers learn water is death.
    # Wipe any pre-existing curriculum stages so the seed is the
    # canonical source. Old stages 1-7 from the prior 7-stage
    # curriculum get cleaned up.
    con.execute('DELETE FROM curriculum_stages')

    # ==================================================================
    # 14-STAGE GRANULAR CURRICULUM
    # Each stage introduces one new mechanic at full strength while
    # fading older signals to ~0.3-0.5. Designed to match the rebuilt
    # perception system (10-slot persistent ids, social topology,
    # water awareness, hearing).
    #
    # Progressive action masking: each stage unlocks a cumulative set
    # of actions. Actions outside the mask are impossible for the net
    # to select, so the policy focuses on what's relevant.
    # ==================================================================

    # Action groups for progressive unlock (32-action space)
    # MOVE (0) auto-resolves direction toward goal. JOB auto-triggers on
    # arrival. BRIBE/SHARE_RUMOR/EXIT_BLOCK/EXIT_GUARD removed (merged/auto).
    # Dynamic masking prevents impossible actions each tick.
    _MOVE_BASE = [0, 18]                 # MOVE, SEARCH (no WAIT until S3)
    _PICKUP_DROP = [13, 14]              # PICKUP, DROP
    _WAIT = [16]                         # WAIT (introduced with hunger in S3)
    _USE = [15]                          # USE_ITEM
    _SNEAK = [1]                         # SET_SNEAK
    _FOLLOW = [3]                        # FOLLOW
    _HARVEST = [23, 27, 28]              # DIG, HARVEST, FARM
    _PROCESS = [25, 26, 29]              # CRAFT, DISASSEMBLE, PROCESS
    _TRADE = [10, 11, 31]               # TRADE, STEAL, REPAY_LOAN
    _SLEEP = [17, 19]                    # GUARD, SLEEP
    _SOCIAL = [8, 9, 12, 22]            # INTIMIDATE, DECEIVE, TALK, CALL_BACKUP
    _COMBAT = [2, 4, 5, 6, 7, 20, 21, 24]  # FLEE, MELEE, RANGED, GRAPPLE, CAST_SPELL, SET_TRAP, BLOCK_STANCE, PUSH
    _PAIR = [30]                         # PAIR

    # Build cumulative action sets per stage
    _s1_actions = sorted(_MOVE_BASE)
    _s2_actions = sorted(_s1_actions + _PICKUP_DROP)
    _s3_actions = sorted(_s2_actions + _USE + _SNEAK + _WAIT)
    _s4_actions = sorted(_s3_actions + _FOLLOW)
    _s5_actions = sorted(_s4_actions + _HARVEST)
    _s6_actions = sorted(_s5_actions + _PROCESS)
    _s7_actions = sorted(_s6_actions)     # JOB is auto — no new action
    _s8_actions = sorted(_s7_actions + _TRADE)
    _s9_actions = sorted(_s8_actions + _SLEEP)
    _s10_actions = sorted(_s9_actions + _SOCIAL)
    _s11_actions = sorted(_s10_actions + _COMBAT)
    _s12_actions = sorted(_s11_actions + _PAIR)  # all 32

    # S1 — Wander
    _stage(1, 'Wander',
           'Move and explore. No WAIT available — must move or search. '
           'Failed actions and water danger penalized.',
           {'exploration': 3.0, 'hp': 0.3,
            'failed_actions': 0.2, 'water_danger': 1.0},
           hunger=False, combat=False, gestation=False,
           mappo=20000, es_gens=0, es_vars=20, es_steps=1000, ppo=20000,
           allowed_actions=_s1_actions, fatigue_enabled=False)

    # S2 — Pickup
    _stage(2, 'Pickup',
           'Grab items and surface gold off the ground. No WAIT, no hunger.',
           {'exploration': 1.0, 'hp': 0.3,
            'gold': 1.0, 'inventory': 1.0,
            'failed_actions': 0.3, 'water_danger': 1.0,
            'pickup_success': 0.5},
           hunger=False, combat=False, gestation=False,
           mappo=20000, es_gens=0, es_vars=20, es_steps=1000, ppo=30000,
           resume=1, allowed_actions=_s2_actions, fatigue_enabled=False)

    # S3 — Hunger
    _stage(3, 'Hunger',
           'Hunger drain enabled. Eating food gives a bonus.',
           {'exploration': 0.3, 'hp': 0.3,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 1.0,
            'failed_actions': 0.5, 'water_danger': 0.7,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=0, es_vars=20, es_steps=1000, ppo=50000,
           resume=2, allowed_actions=_s3_actions, fatigue_enabled=False)

    # S4 — Purpose
    _stage(4, 'Purpose',
           'Tile-purpose alignment matters. Goal progress and '
           'completion signals turn on.',
           {'exploration': 0.3, 'hp': 0.3,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 0.7,
            'xp': 0.1,
            'goal_progress': 0.7, 'goal_completed': 1.0,
            'purpose_proximity': 1.0,
            'failed_actions': 0.5, 'water_danger': 0.7,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=0, es_vars=20, es_steps=1000, ppo=50000,
           resume=3, allowed_actions=_s4_actions, fatigue_enabled=False)

    # S5 — Harvest
    _stage(5, 'Harvest',
           'HARVEST action becomes valuable via inventory delta on '
           'resource tiles.',
           {'exploration': 0.3, 'hp': 0.3,
            'gold': 0.5, 'inventory': 0.7,
            'hunger': 0.7,
            'xp': 0.1, 'equipment': 0.3,
            'equipment_upgrade': 0.3, 'encumbrance_relief': 0.3,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.7,
            'failed_actions': 0.5, 'water_danger': 0.7,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=0, es_vars=20, es_steps=1000, ppo=60000,
           resume=4, allowed_actions=_s5_actions, fatigue_enabled=False)

    # S6 — Process
    _stage(6, 'Process',
           'PROCESS action becomes valuable: refined items have '
           'higher value and more healing.',
           {'exploration': 0.3, 'hp': 0.3,
            'gold': 0.5, 'inventory': 1.0,
            'hunger': 0.7,
            'xp': 0.1, 'equipment': 0.3,
            'equipment_upgrade': 0.3, 'encumbrance_relief': 0.3,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'failed_actions': 0.5, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=0, es_vars=20, es_steps=1000, ppo=60000,
           resume=5, allowed_actions=_s6_actions, fatigue_enabled=False)

    # S7 — Jobs
    _stage(7, 'Jobs',
           'JOB action wages turn on. Creatures learn schedule-based '
           'work at workplace tiles.',
           {'exploration': 0.3, 'hp': 0.3,
            'gold': 0.7, 'inventory': 0.7,
            'hunger': 0.7,
            'wage': 1.0,
            'xp': 0.2, 'equipment': 0.3,
            'equipment_upgrade': 0.3, 'encumbrance_relief': 0.3,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'failed_actions': 0.5, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=10, es_vars=20, es_steps=1500, ppo=60000,
           resume=6, allowed_actions=_s7_actions, fatigue_enabled=False)

    # S8 — Trade
    _stage(8, 'Trade',
           'Trade surplus rewards turn on. ES phase enabled.',
           {'exploration': 0.2, 'hp': 0.3,
            'gold': 0.7, 'inventory': 0.7,
            'hunger': 0.7,
            'wage': 0.7, 'trade': 1.0, 'theft': 0.5,
            'xp': 0.2, 'equipment': 0.5, 'debt': 0.5,
            'equipment_upgrade': 0.5, 'encumbrance_relief': 0.5,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'failed_actions': 0.5, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=15, es_vars=30, es_steps=1500, ppo=80000,
           resume=7, allowed_actions=_s8_actions, fatigue_enabled=False)

    # S9 — Schedule
    _stage(9, 'Schedule',
           'Fatigue and crowding penalties added. Sleep at night '
           'becomes meaningful.',
           {'exploration': 0.2, 'hp': 0.3,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 0.7,
            'wage': 0.7, 'trade': 0.7, 'theft': 0.3,
            'xp': 0.2, 'equipment': 0.5, 'debt': 0.5,
            'equipment_upgrade': 0.5, 'encumbrance_relief': 0.5,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'fatigue': 1.0, 'crowding': 1.0,
            'sleep_quality': 0.7,
            'failed_actions': 0.5, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=10, es_vars=30, es_steps=1500, ppo=60000,
           resume=8, allowed_actions=_s9_actions, fatigue_enabled=True)

    # S10 — Reputation
    _stage(10, 'Reputation',
           'Reputation and ally count signals turn on. Building '
           'relationships starts to matter.',
           {'exploration': 0.2, 'hp': 0.3,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 0.7,
            'wage': 0.5, 'trade': 0.7,
            'xp': 0.3, 'equipment': 0.5, 'debt': 0.7,
            'equipment_upgrade': 0.5, 'encumbrance_relief': 0.5,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'reputation': 1.0, 'allies': 1.0,
            'theft': 0.3, 'deception_stress': 1.0,
            'fatigue': 1.0, 'crowding': 1.0,
            'sleep_quality': 1.0, 'social_success': 0.5,
            'failed_actions': 0.7, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=False, gestation=False,
           mappo=20000, es_gens=10, es_vars=30, es_steps=1500, ppo=60000,
           resume=9, allowed_actions=_s10_actions, fatigue_enabled=True)

    # S11 — Combat
    _stage(11, 'Combat',
           'Combat enabled. Kill rewards turn on. Creatures can '
           'attack each other but should already have a productive '
           'baseline from earlier stages.',
           {'exploration': 0.2, 'hp': 0.7,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 0.7,
            'wage': 0.5, 'trade': 0.5,
            'xp': 0.3, 'equipment': 0.7, 'debt': 0.7,
            'equipment_upgrade': 0.7, 'encumbrance_relief': 0.7,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'reputation': 0.7, 'allies': 0.7,
            'kills': 1.0,
            'theft': 0.3, 'deception_stress': 1.0,
            'fatigue': 1.0, 'crowding': 1.0,
            'sleep_quality': 1.0, 'social_success': 0.7, 'damage_dealt': 0.7,
            'failed_actions': 1.0, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=True, gestation=False,
           mappo=20000, es_gens=10, es_vars=30, es_steps=1500, ppo=80000,
           resume=10, allowed_actions=_s11_actions, fatigue_enabled=True)

    # S12 — Lifecycle
    _stage(12, 'Lifecycle',
           'PAIR action and gestation enabled. Reproduction reward '
           'via life_goals.',
           {'exploration': 0.2, 'hp': 0.5,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 0.7,
            'wage': 0.5, 'trade': 0.5,
            'xp': 0.3, 'equipment': 0.7, 'debt': 0.7,
            'equipment_upgrade': 0.7, 'encumbrance_relief': 0.7,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'reputation': 0.7, 'allies': 0.7,
            'kills': 0.7,
            'theft': 0.3, 'deception_stress': 1.0,
            'fatigue': 1.0, 'crowding': 0.5,
            'life_goals': 1.0,
            'sleep_quality': 1.0, 'social_success': 0.7, 'damage_dealt': 0.5,
            'failed_actions': 1.0, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=True, gestation=True,
           mappo=20000, es_gens=10, es_vars=30, es_steps=1500, ppo=80000,
           resume=11, allowed_actions=_s12_actions, fatigue_enabled=True)

    # S13 — Religion
    _stage(13, 'Religion',
           'Piety, quests, and xp signals turn on.',
           {'exploration': 0.2, 'hp': 0.5,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 0.7,
            'wage': 0.5, 'trade': 0.5,
            'xp': 0.5, 'equipment': 0.7, 'debt': 0.7,
            'equipment_upgrade': 0.7, 'encumbrance_relief': 0.7,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'reputation': 0.7, 'allies': 0.7,
            'kills': 0.7,
            'theft': 0.3, 'deception_stress': 1.0,
            'fatigue': 1.0, 'crowding': 0.5,
            'life_goals': 0.7,
            'piety': 1.0, 'quests': 1.0,
            'sleep_quality': 1.0, 'social_success': 0.7, 'damage_dealt': 0.5,
            'failed_actions': 1.0, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=True, gestation=True,
           mappo=20000, es_gens=10, es_vars=30, es_steps=1500, ppo=60000,
           resume=12, allowed_actions=_s12_actions, fatigue_enabled=True)

    # S14 — Mastery
    _stage(14, 'Mastery',
           'Final stage. Every mechanic active at calibrated weights.',
           {'exploration': 0.2, 'hp': 0.5,
            'gold': 0.5, 'inventory': 0.5,
            'hunger': 0.7,
            'wage': 0.5, 'trade': 0.7,
            'xp': 0.5, 'equipment': 0.7, 'debt': 0.7,
            'equipment_upgrade': 0.7, 'encumbrance_relief': 0.7,
            'goal_progress': 0.5, 'goal_completed': 1.0,
            'purpose_proximity': 0.5,
            'reputation': 0.7, 'allies': 0.7,
            'kills': 0.7,
            'theft': 0.5, 'deception_stress': 1.0,
            'fatigue': 1.0, 'crowding': 0.5,
            'life_goals': 1.0,
            'piety': 0.7, 'quests': 0.7,
            'sleep_quality': 1.0, 'social_success': 0.7, 'damage_dealt': 0.5,
            'failed_actions': 1.0, 'water_danger': 0.5,
            'idleness': 0.5, 'pickup_success': 0.5},
           hunger=True, combat=True, gestation=True,
           mappo=20000, es_gens=15, es_vars=40, es_steps=2000, ppo=120000,
           resume=13, allowed_actions=_s12_actions, fatigue_enabled=True)

    con.commit()
    con.close()

    print('Seeded content:')
    print('  4 tile sprites (grass, dirt, sand, water×2)')
    print('  4 tile templates + water animation')
    print('  16 item sprites')
    print('  4 clothing items (shirt, trousers, shoes, cap)')
    print('  3 armor pieces (helmet, breastplate, greaves)')
    print('  4 weapons (short sword, long sword, short bow, long bow)')
    print('  2 ammo types (arrow, poison arrow)')
    print('  1 stackable (gold piece)')
    print('  3 potions (health, stamina, mana)')
    print('  1 ring (ring of vitality)')
    print('  5 raw food items (wheat, fish, berries, game, mushrooms)')
    print('  6 processed food items (bread, cooked fish, jam, roast, dried mushrooms, stew)')
    print('  4 raw materials (iron ore, copper ore, coal, stone)')
    print('  3 processed materials (iron ingot, copper ingot, charcoal)')
    print('  1 tool (shovel)')
    print('  7 jobs (farmer, miner, crafter, trader, hunter, healer, guard)')
    print('  9 processing recipes (bake, cook, jam, roast, dry, stew, smelt×2, charcoal)')
    print('  14 curriculum stages (wander -> pickup -> hunger -> purpose -> harvest ->')
    print('                          process -> jobs -> trade -> schedule -> reputation ->')
    print('                          combat -> lifecycle -> religion -> mastery)')


if __name__ == '__main__':
    seed()
