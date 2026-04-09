"""
Seed a complete world: map, composite animation, spells, dialogue, quests.
Run from project root: python src/data/seed_world.py
"""
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
DB_PATH = Path(__file__).parent / 'game.db'


def ins(con, table, **kw):
    cols = list(kw.keys())
    con.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
                list(kw.values()))


def sprite(con, name, palette, pixels):
    w = len(pixels[0]) if pixels else 0
    con.execute('INSERT OR REPLACE INTO sprites (name,palette,pixels,width,height) VALUES (?,?,?,?,?)',
                (name, json.dumps(palette), json.dumps(pixels), w, len(pixels)))


def seed():
    con = sqlite3.connect(DB_PATH)

    # ======================================================================
    # COMPOSITE: z_ball_man (ball orbiting a person)
    # ======================================================================

    # Person body sprite
    sprite(con, 'z_body', {
        'S': [220,190,160], 'H': [80,50,30], 'B': [60,60,150], 'C': [100,80,60],
    }, [
        '..HHH...','.HSSSH..','.SSSSS..','..CSC...','.CCBCC..','..BBB...','.BB.BB..','........',
    ])

    # Ball sprite (bright yellow)
    sprite(con, 'z_ball', {
        'Y': [255,220,40], 'G': [220,180,20], 'W': [255,255,200],
    }, [
        '.GG.','.YWY','GYWY','.YY.',
    ])

    # Composite sprite: body as root
    ins(con, 'composite_sprites', name='z_ball_man', root_layer='body')

    # Layers (using actual column names)
    con.execute('INSERT OR REPLACE INTO composite_layers (composite_name, layer_name, z_layer, default_sprite) VALUES (?,?,?,?)',
                ('z_ball_man', 'body', 0, 'z_body'))
    con.execute('INSERT OR REPLACE INTO composite_layers (composite_name, layer_name, z_layer, default_sprite) VALUES (?,?,?,?)',
                ('z_ball_man', 'ball', 1, 'z_ball'))

    # Animation: ball orbiting the body (total duration = 8 * 150ms = 1200ms)
    con.execute('INSERT OR REPLACE INTO composite_animations (name, composite_name, loop, duration_ms) VALUES (?,?,?,?)',
                ('orbit', 'z_ball_man', 1, 1200))

    # 8 keyframes: ball moves in a circle around the body
    positions = [
        (0, 4, -2),     # top
        (150, 6, 0),    # top-right
        (300, 6, 3),    # right
        (450, 4, 5),    # bottom-right
        (600, 0, 5),    # bottom
        (750, -2, 3),   # bottom-left
        (900, -2, 0),   # left
        (1050, 0, -2),  # top-left
    ]
    for time_ms, ox, oy in positions:
        con.execute(
            '''INSERT INTO composite_anim_keyframes
               (animation_name, layer_name, time_ms, offset_x, offset_y)
               VALUES (?,?,?,?,?)''',
            ('orbit', 'ball', time_ms, ox, oy))

    # Bind the orbit animation to idle behavior for z_ball_man
    con.execute(
        'INSERT OR REPLACE INTO composite_anim_bindings (target_name, behavior, animation_name, flip_h) VALUES (?,?,?,?)',
        ('z_ball_man', 'idle', 'orbit', 0))

    # ======================================================================
    # SPELLS
    # ======================================================================

    for key, name, desc, dmg, mana, stam, rng, rad, dc, dodge, ttype, etype, buffs, dur, s_res, s_dc, reqs in [
        ('fireball', 'Fireball', 'A ball of searing flame', 12, 8, 0, 6, 2, 14, 1, 'area', 'damage',
         '{}', 0, None, None, '{"intelligence": 12}'),
        ('heal', 'Heal', 'Restore health to a creature', 15, 5, 0, 3, 0, 0, 0, 'single', 'heal',
         '{}', 0, None, None, '{}'),
        ('lightning', 'Lightning Bolt', 'A crackling bolt of electricity', 10, 6, 0, 8, 0, 12, 1, 'single', 'damage',
         '{}', 0, 'stagger resist', 10, '{"intelligence": 10}'),
        ('shield_spell', 'Arcane Shield', 'Encase yourself in protective magic', 0, 4, 0, 0, 0, 0, 0, 'self', 'buff',
         '{"armor": 5, "magic resist": 3}', 30.0, None, None, '{}'),
        ('poison_cloud', 'Poison Cloud', 'A noxious cloud that sickens enemies', 5, 7, 0, 5, 3, 10, 0, 'area', 'damage',
         '{}', 0, 'poison resist', 14, '{"intelligence": 14}'),
        ('bless', 'Bless', 'Grant an ally divine favor', 0, 3, 0, 4, 0, 0, 0, 'single', 'buff',
         '{"strength": 2, "vitality": 2, "luck": 1}', 60.0, None, None, '{}'),
        ('curse', 'Curse', 'Weaken an enemy with dark magic', 0, 5, 0, 5, 0, 12, 0, 'single', 'debuff',
         '{"strength": -3, "agility": -2, "perception": -2}', 30.0, None, None, '{"intelligence": 11}'),
        ('mana_drain', 'Mana Drain', 'Steal mana from a target', 0, 2, 0, 4, 0, 10, 1, 'single', 'debuff',
         '{"max mana": -10}', 20.0, None, None, '{}'),
    ]:
        ins(con, 'spells', key=key, name=name, description=desc, damage=dmg,
            mana_cost=mana, stamina_cost=stam, range=rng, radius=rad, spell_dc=dc,
            dodgeable=dodge, target_type=ttype, effect_type=etype,
            buffs=buffs, duration=dur, secondary_resist=s_res, secondary_dc=s_dc,
            requirements=reqs)

    # Assign spells to species
    for species, spell_keys in [
        ('human', ['heal', 'shield_spell', 'bless', 'lightning']),
        ('orc', ['curse', 'poison_cloud']),
    ]:
        for sk in spell_keys:
            con.execute('INSERT OR REPLACE INTO species_spells VALUES (?,?)', (species, sk))

    # Assign spells to specific NPCs
    for npc, spell_keys in [
        ('healer', ['heal', 'bless']),
        ('orc_shaman', ['curse', 'poison_cloud', 'mana_drain']),
    ]:
        for sk in spell_keys:
            con.execute('INSERT OR REPLACE INTO creature_spells VALUES (?,?)', (npc, sk))

    # ======================================================================
    # MAP: "village" — 30x30 with water border and obstacles
    # ======================================================================

    ins(con, 'maps', name='village', tile_set='village_tiles',
        default_tile_template='grass',
        entrance_x=15, entrance_y=15,
        x_min=0, x_max=30, y_min=0, y_max=30,
        z_min=0, z_max=0)

    # Build tile set: grass interior, water border, dirt paths, sand patches
    tile_id = con.execute('SELECT MAX(id) FROM tile_sets').fetchone()[0] or 0

    for x in range(30):
        for y in range(30):
            # Water border (3 tiles thick)
            if x < 3 or x > 26 or y < 3 or y > 26:
                tmpl = 'water'
            # Dirt paths (cross pattern)
            elif x == 15 or y == 15:
                tmpl = 'dirt'
            # Sand patches
            elif (10 <= x <= 12 and 10 <= y <= 12) or (20 <= x <= 22 and 20 <= y <= 22):
                tmpl = 'sand'
            # Some random water ponds
            elif (x - 8) ** 2 + (y - 8) ** 2 <= 4:
                tmpl = 'water'
            elif (x - 22) ** 2 + (y - 8) ** 2 <= 3:
                tmpl = 'water'
            else:
                tmpl = 'grass'

            tile_id += 1
            con.execute(
                'INSERT INTO tile_sets (id, tile_set, x, y, z, tile_template) VALUES (?,?,?,?,?,?)',
                (tile_id, 'village_tiles', x, y, 0, tmpl))

    # ======================================================================
    # DIALOGUE TREES
    # ======================================================================

    # Blacksmith dialogue
    dialogues = [
        # Root: blacksmith greets
        (1, 'blacksmith_talk', None, 'blacksmith', None, 'npc',
         'Well met, traveler. Need a blade sharpened or armor mended?',
         '{}', '{}', '{}', None, '{}', 0),
        # Player responses
        (2, 'blacksmith_talk', None, None, 1, 'player',
         'What do you have for sale?', '{}', '{}', '{}', 'trade', '{}', 0),
        (3, 'blacksmith_talk', None, None, 1, 'player',
         'Tell me about this village.', '{}', '{}', '{}', None, '{}', 1),
        (4, 'blacksmith_talk', None, None, 1, 'player',
         'Nothing, thanks.', '{}', '{}', '{}', None, '{"sentiment": -0.5}', 2),
        # Blacksmith responds to village question
        (5, 'blacksmith_talk', None, 'blacksmith', 3, 'npc',
         'Small place. Orcs to the east keep raiding our stores. Watch yourself out there.',
         '{}', '{}', '{}', None, '{}', 0),

        # Healer dialogue
        (10, 'healer_talk', None, 'healer', None, 'npc',
         'Solmara\'s light upon you. Are you injured?',
         '{}', '{}', '{}', None, '{}', 0),
        (11, 'healer_talk', None, None, 10, 'player',
         'Can you heal me?', '{}', '{}', '{}', None, '{"sentiment": 1.0}', 0),
        (12, 'healer_talk', None, None, 10, 'player',
         'I seek wisdom.', '{}', '{}', '{}', None, '{}', 1),
        (13, 'healer_talk', None, 'healer', 11, 'npc',
         'Hold still... [Heals you] There. Solmara provides.',
         '{}', '{}', '{}', None, '{"give_item": "potion_health"}', 0),
        (14, 'healer_talk', None, 'healer', 12, 'npc',
         'Seek compassion in all things. Even the orc has a soul worth saving.',
         '{}', '{}', '{}', None, '{}', 0),

        # Orc chief dialogue
        (20, 'orc_chief_talk', None, 'orc_chief', None, 'npc',
         'HRAAAGH! What puny creature dares approach Groknak?',
         '{}', '{}', '{}', None, '{}', 0),
        (21, 'orc_chief_talk', None, None, 20, 'player',
         'I come in peace.', '{}', '{}', '{}', None, '{}', 0),
        (22, 'orc_chief_talk', None, None, 20, 'player',
         'Prepare to die!', '{}', '{}', '{}', None, '{"sentiment": -5.0}', 1),
        (23, 'orc_chief_talk', None, 'orc_chief', 21, 'npc',
         'Peace? Bah! Peace is for the weak. But... you have guts. I respect that.',
         '{}', '{}', '{}', None, '{"sentiment": 2.0}', 0),
        (24, 'orc_chief_talk', None, 'orc_chief', 22, 'npc',
         'HAHAHA! Finally someone with spine! Come then!',
         '{}', '{}', '{}', 'attack', '{}', 0),
    ]

    for d in dialogues:
        con.execute(
            '''INSERT OR REPLACE INTO dialogue
               (id, conversation, species, creature_key, parent_id, speaker,
                text, char_conditions, world_conditions, quest_conditions,
                behavior, effects, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', d)

    # ======================================================================
    # QUESTS (simple jobs)
    # ======================================================================

    ins(con, 'quests', name='gather_herbs', giver='healer',
        description='Miriel needs herbs from the eastern fields',
        quest_type='job', conditions='', reward_action='',
        fail_action='', time_limit=None, repeatable=1, cooldown_days=3)

    for step_no, sub, desc, succ, fail in [
        (1, 'a', 'Travel to the eastern sand patch', '', ''),
        (2, 'a', 'Search for herbs (search 3 tiles)', '', ''),
        (3, 'a', 'Return herbs to Miriel', '', ''),
    ]:
        con.execute(
            '''INSERT OR REPLACE INTO quest_steps
               (quest_name, step_no, step_sub, description,
                success_condition, fail_condition, success_action, fail_action)
               VALUES (?,?,?,?,?,?,?,?)''',
            ('gather_herbs', step_no, sub, desc, succ, fail, '', ''))

    ins(con, 'quests', name='orc_bounty', giver='blacksmith',
        description='Torvin wants you to deal with the orc raiders',
        quest_type='quest', conditions='', reward_action='',
        fail_action='', time_limit=600, repeatable=0, cooldown_days=None)

    for step_no, sub, desc in [
        (1, 'a', 'Talk to Torvin about the orc problem'),
        (2, 'a', 'Travel east to the orc camp'),
        (2, 'b', 'Defeat 3 orc warriors'),
        (3, 'a', 'Confront Groknak the Warchief'),
        (4, 'a', 'Return to Torvin with proof'),
    ]:
        con.execute(
            '''INSERT OR REPLACE INTO quest_steps
               (quest_name, step_no, step_sub, description,
                success_condition, fail_condition, success_action, fail_action)
               VALUES (?,?,?,?,?,?,?,?)''',
            ('orc_bounty', step_no, sub, desc, '', '', '', ''))

    ins(con, 'quests', name='rat_problem', giver='blacksmith',
        description='Rats are getting into the forge stores',
        quest_type='job', conditions='', reward_action='',
        fail_action='', time_limit=300, repeatable=1, cooldown_days=1)

    con.execute(
        '''INSERT OR REPLACE INTO quest_steps
           (quest_name, step_no, step_sub, description,
            success_condition, fail_condition, success_action, fail_action)
           VALUES (?,?,?,?,?,?,?,?)''',
        ('rat_problem', 1, 'a', 'Kill 3 rats near the forge', '', '', '', ''))

    con.commit()
    con.close()

    print('Seeded world content:')
    print('  Composite: z_ball_man (body + orbiting ball, 8 keyframes)')
    print('  Spells: 8 (fireball, heal, lightning, shield, poison cloud, bless, curse, mana drain)')
    print('  Species spells: human 4, orc 2')
    print('  NPC spells: healer 2, shaman 3')
    print('  Map: village (30x30, water border, dirt paths, ponds)')
    print('  Dialogue: blacksmith (5 nodes), healer (5), orc chief (5)')
    print('  Quests: gather_herbs (job), orc_bounty (story), rat_problem (job)')


if __name__ == '__main__':
    seed()
