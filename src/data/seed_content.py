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


if __name__ == '__main__':
    seed()
