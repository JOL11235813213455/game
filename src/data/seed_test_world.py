"""
Seed the "Test Town" — a hand-laid demo world for direct play.

Run from the project root:
    python src/data/seed_test_world.py

Creates:
  - 8 new tile templates (cobblestone, path, pond shallow/deep, stream
    flowing, plowed field, wood floor, stone cave floor)
  - ~15 new sprites: tiles, structures, items, props, an NPC composite
  - 1 town map (24x24) with:
      * cobblestone town square in the middle
      * 5 wooden houses around the square (each with a nested 8x8 interior)
      * a well in the square
      * wheat fields to the south
      * a pond to the east, with a stream flowing south into it
      * a road heading west to a cave entrance structure
  - 5 house interior maps (8x8 each)
  - 1 cave map (12x12) with dim stone tiles, a quest objective item,
    a hostile creature, and a treasure chest
  - 6 NPCs in the town:
      * Mayor Eldon (quest giver: clear the cave)
      * Farmer Peg (quest giver: pond cleanup)
      * Smith Bram
      * Trader Lila
      * Healer Yara
      * Guardsman Tovin
  - 2 quests with multi-step structure
  - dialogue trees for the quest givers

This is purely DATA — no behavior code, no UI. The HUD/menu/keybinding
work happens in separate modules under src/main/.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
DB_PATH = Path(__file__).parent / 'game.db'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sprite(con, name, palette, pixels):
    w = len(pixels[0]) if pixels else 0
    con.execute(
        'INSERT OR REPLACE INTO sprites (name, palette, pixels, width, height) '
        'VALUES (?, ?, ?, ?, ?)',
        (name, json.dumps(palette), json.dumps(pixels), w, len(pixels))
    )


def tile_template(con, key, name, walkable=1, sprite_name=None,
                   bg_color=None, liquid=0, flow_direction=None,
                   flow_speed=0.0, depth=0, purpose=None,
                   speed_modifier=1.0):
    con.execute(
        'INSERT OR REPLACE INTO tile_templates '
        '(key, name, walkable, sprite_name, bg_color, liquid, flow_direction, '
        ' flow_speed, depth, purpose, speed_modifier) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (key, name, walkable, sprite_name, bg_color, liquid, flow_direction,
         flow_speed, depth, purpose, speed_modifier)
    )


def tile_set_entry(con, tile_set_name, x, y, z, template, **overrides):
    cols = ['tile_set', 'x', 'y', 'z', 'tile_template']
    vals = [tile_set_name, x, y, z, template]
    for k, v in overrides.items():
        cols.append(k)
        vals.append(v)
    placeholders = ','.join(['?'] * len(cols))
    con.execute(
        f'INSERT INTO tile_sets ({",".join(cols)}) VALUES ({placeholders})',
        vals
    )


def map_row(con, name, tile_set, default_template, x_max, y_max,
            entrance_x=0, entrance_y=0):
    con.execute(
        'INSERT OR REPLACE INTO maps '
        '(name, tile_set, default_tile_template, x_min, y_min, z_min, '
        ' x_max, y_max, z_max, entrance_x, entrance_y) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (name, tile_set, default_template, 0, 0, 0,
         x_max, y_max, 0, entrance_x, entrance_y)
    )


def insert_item(con, cls, key, name, **kwargs):
    kwargs['class'] = cls
    kwargs['key'] = key
    kwargs['name'] = name
    cols = list(kwargs.keys())
    vals = list(kwargs.values())
    placeholders = ','.join(['?'] * len(cols))
    con.execute(
        f'INSERT OR REPLACE INTO items ({",".join(cols)}) VALUES ({placeholders})',
        vals
    )


def insert_creature(con, key, name, species, sex, age, behavior=None,
                     deity=None, gold=10, items=None,
                     spawn_map=None, spawn_x=None, spawn_y=None,
                     dialogue_tree=None, **stats):
    """Seed a creature. Stats passed as kwargs map to creature_stats rows."""
    con.execute(
        'INSERT OR REPLACE INTO creatures '
        '(key, name, species, sex, age, behavior, deity, gold, items, '
        ' spawn_map, spawn_x, spawn_y, dialogue_tree) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (key, name, species, sex, age, behavior, deity, gold,
         json.dumps(items or []),
         spawn_map, spawn_x, spawn_y, dialogue_tree)
    )
    con.execute('DELETE FROM creature_stats WHERE creature_key = ?', (key,))
    for stat, val in stats.items():
        con.execute(
            'INSERT INTO creature_stats (creature_key, stat, value) VALUES (?, ?, ?)',
            (key, stat, val)
        )


def seed():
    con = sqlite3.connect(DB_PATH)
    print('Seeding Test Town...')

    # ==================================================================
    # SPRITES — TILES (16x16 each)
    # ==================================================================

    # Cobblestone — gray rounded stones
    sprite(con, 't_cobble', {
        'L': [150, 150, 155], 'D': [110, 110, 115], 'M': [130, 130, 135],
        'l': [165, 165, 170], 'k': [95, 95, 100],
    }, [
        'LMLLkDMLMLLkDMLk',
        'MLDMLLkLDMLLkLDM',
        'LkLLDMLkLLDMLkLL',
        'lLMLLDLlLMLLDLLk',
        'kLDMLLkkLDMLLkLD',
        'LMLLkLDLMLLkLDLL',
        'MLDMlLkMLDMlLkML',
        'LkLLkDLLkLLkDLLk',
        'lLMLLDLlLMLLDLLM',
        'kLDMLLkkLDMLLkLD',
        'LMLLkLDLMLLkLDLM',
        'MLDMlLkMLDMlLkML',
        'LkLLkDLLkLLkDLLk',
        'lLMLLDLlLMLLDLLM',
        'kLDMLLkkLDMLLkLD',
        'LMLLkDMLMLLkDMLk',
    ])

    # Dirt path — lighter brown, packed
    sprite(con, 't_path', {
        'B': [155, 120, 80], 'b': [175, 140, 95], 'D': [135, 100, 65],
        'd': [165, 130, 88], '.': [145, 115, 78],
    }, [
        'BbBdBb.dBbBdBb.d',
        'b.BbDb.BbBbDb.Bb',
        'BdbBbdBdBdbBbdBd',
        'dBbDbBdbdBbDbBdb',
        'BbBdBb.dBbBdBb.d',
        'b.BbDb.BbBbDb.Bb',
        'BdbBbdBdBdbBbdBd',
        'dBbDbBdbdBbDbBdb',
        'BbBdBb.dBbBdBb.d',
        'b.BbDb.BbBbDb.Bb',
        'BdbBbdBdBdbBbdBd',
        'dBbDbBdbdBbDbBdb',
        'BbBdBb.dBbBdBb.d',
        'b.BbDb.BbBbDb.Bb',
        'BdbBbdBdBdbBbdBd',
        'dBbDbBdbdBbDbBdb',
    ])

    # Pond — deep stationary water with subtle ripples
    sprite(con, 't_pond', {
        'W': [25, 70, 140], 'w': [35, 90, 165], 'D': [18, 55, 115],
        'L': [55, 120, 195], '.': [30, 80, 155],
    }, [
        'WwDwWwDwWwDwWwDw',
        'wWLwwWLwwWLwwWLw',
        'DwWwDwWwDwWwDwWw',
        'wLwWwLwWwLwWwLwW',
        'WwDwWwDwWwDwWwDw',
        'wWLwwWLwwWLwwWLw',
        'DwWwDwWwDwWwDwWw',
        'wLwWwLwWwLwWwLwW',
        'WwDwWwDwWwDwWwDw',
        'wWLwwWLwwWLwwWLw',
        'DwWwDwWwDwWwDwWw',
        'wLwWwLwWwLwWwLwW',
        'WwDwWwDwWwDwWwDw',
        'wWLwwWLwwWLwwWLw',
        'DwWwDwWwDwWwDwWw',
        'wLwWwLwWwLwWwLwW',
    ])

    # Stream — flowing water (south)
    sprite(con, 't_stream', {
        'W': [40, 110, 200], 'w': [60, 140, 220], 'L': [80, 165, 235],
        'D': [30, 90, 170],
    }, [
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
        'WwLwWwLwWwLwWwLw',
        'wDwWwDwWwDwWwDwW',
    ])

    # Plowed wheat field
    sprite(con, 't_field', {
        'B': [110, 70, 40], 'b': [140, 95, 55], 'Y': [200, 170, 60],
        'y': [220, 190, 80], '.': [125, 85, 50],
    }, [
        'BbB.BbB.BbB.BbB.',
        'YyYbYyYbYyYbYyYb',
        'B.BbB.BbB.BbB.Bb',
        'bYbyBYbyBYbyBYby',
        'BbB.BbB.BbB.BbB.',
        'YyYbYyYbYyYbYyYb',
        'B.BbB.BbB.BbB.Bb',
        'bYbyBYbyBYbyBYby',
        'BbB.BbB.BbB.BbB.',
        'YyYbYyYbYyYbYyYb',
        'B.BbB.BbB.BbB.Bb',
        'bYbyBYbyBYbyBYby',
        'BbB.BbB.BbB.BbB.',
        'YyYbYyYbYyYbYyYb',
        'B.BbB.BbB.BbB.Bb',
        'bYbyBYbyBYbyBYby',
    ])

    # Wood floor (house interior)
    sprite(con, 't_wood_floor', {
        'B': [140, 95, 55], 'b': [160, 115, 70], 'D': [115, 75, 40],
        '.': [150, 105, 65],
    }, [
        'BBBBBBBBBBBBBBBB',
        'b.b.b.b.b.b.b.b.',
        'BBBBBBBBBBBBBBBB',
        'DDDDDDDDDDDDDDDD',
        'BBBBBBBBBBBBBBBB',
        'b.b.b.b.b.b.b.b.',
        'BBBBBBBBBBBBBBBB',
        'DDDDDDDDDDDDDDDD',
        'BBBBBBBBBBBBBBBB',
        'b.b.b.b.b.b.b.b.',
        'BBBBBBBBBBBBBBBB',
        'DDDDDDDDDDDDDDDD',
        'BBBBBBBBBBBBBBBB',
        'b.b.b.b.b.b.b.b.',
        'BBBBBBBBBBBBBBBB',
        'DDDDDDDDDDDDDDDD',
    ])

    # Cave floor (dim stone)
    sprite(con, 't_cave_floor', {
        'D': [55, 50, 50], 'M': [70, 65, 65], 'L': [85, 80, 80],
        '.': [40, 38, 38], 'k': [45, 42, 42],
    }, [
        'DMDkDMDkDMDkDMDk',
        'MLMDLMDMLMDMLMDM',
        'DMD.kMDkDMDkDMDk',
        'kDMLMDLMkDMLMDLM',
        'DMDkDMDkDMDkDMDk',
        'MLMDLMDMLMDMLMDM',
        'DMD.kMDkDMDkDMDk',
        'kDMLMDLMkDMLMDLM',
        'DMDkDMDkDMDkDMDk',
        'MLMDLMDMLMDMLMDM',
        'DMD.kMDkDMDkDMDk',
        'kDMLMDLMkDMLMDLM',
        'DMDkDMDkDMDkDMDk',
        'MLMDLMDMLMDMLMDM',
        'DMD.kMDkDMDkDMDk',
        'kDMLMDLMkDMLMDLM',
    ])

    # ==================================================================
    # SPRITES — STRUCTURES
    # ==================================================================

    # Wooden house — peaked roof, door, two windows. 32x32 (2x2 footprint).
    sprite(con, 's_house_wood', {
        'r': [140, 60, 40],   # roof red
        'R': [110, 45, 30],   # roof shadow
        'D': [80, 35, 20],    # roof eaves
        'B': [120, 80, 50],   # wall planks
        'b': [140, 95, 60],   # wall light
        'd': [60, 35, 20],    # door dark
        'k': [90, 55, 30],    # door wood
        'W': [200, 230, 255], # window light
        'w': [150, 190, 220], # window mid
        'F': [50, 30, 20],    # frame
        'g': [60, 50, 30],    # ground shadow
        '.': [0, 0, 0, 0],    # transparent
    }, [
        '...........rrrr...rrrr..........',
        '..........rrrrrr.rrrrrr.........',
        '.........rrrrrrrrrrrrrrr........',
        '........rRrrrrrrrrrrrrrRr.......',
        '.......rRRrrrrrrrrrrrrrRRr......',
        '......rRRRrrrrrrrrrrrrrRRRr.....',
        '.....rRRRRrrrrrrrrrrrrrRRRRr....',
        '....rRRRRRrrrrrrrrrrrrrRRRRRr...',
        '...DDDDDDDDDDDDDDDDDDDDDDDDDDD..',
        '..FBBBBBBBBBBBBBBBBBBBBBBBBBBBBF',
        '..FBbBbBbBbBbBbBbBbBbBbBbBbBbBBF',
        '..FBBFWWWFBBBBBBBBBBBBFWWWFBBBBF',
        '..FbBFWwWFBBBBBBBBBBBBFWwWFBBbBF',
        '..FBBFWWWFBBBBdddddBBBFWWWFBBBBF',
        '..FBbBBBBBBBBBdkkkdBBBBBBBBBBbBF',
        '..FBBBBBBBBBBBdkkkdBBBBBBBBBBBBF',
        '..FbBBBBBBBBBBdkkkdBBBBBBBBBBbBF',
        '..FBBBBBBBBBBBdkkkdBBBBBBBBBBBBF',
        '..FBbBBBBBBBBBdkkkdBBBBBBBBBBbBF',
        '..FBBBBBBBBBBBdkkkdBBBBBBBBBBBBF',
        '..FbBBBBBBBBBBdkkkdBBBBBBBBBBbBF',
        '..FBBBBBBBBBBBdkkkdBBBBBBBBBBBBF',
        '..FBbBbBbBbBbBdkkkdBbBbBbBbBbBBF',
        '..FBBBBBBBBBBBdkkkdBBBBBBBBBBBBF',
        '..FFFFFFFFFFFFFdkdFFFFFFFFFFFFFF',
        '..gggggggggggggdkdgggggggggggggg',
        '...gg.gg.gg.gg.dkd.gg.gg.gg.gg..',
        '..g.g.g.g.g.g.g.g.g.g.g.g.g.g.g.',
        '................................',
        '................................',
        '................................',
        '................................',
    ])

    # Stone well — circular with bucket and crank
    sprite(con, 's_well', {
        'S': [120, 120, 125], 's': [145, 145, 150], 'D': [85, 85, 90],
        'd': [60, 60, 65], 'W': [40, 90, 160], 'w': [60, 120, 190],
        'B': [80, 50, 25], 'k': [40, 25, 10], 'F': [50, 50, 55],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '......BkBk......',
        '.....k....k.....',
        '....k......k....',
        '....k.BkB..k....',
        '....k.k.k..k....',
        '...DSSSSSSSD....',
        '..DSsSDsSDsSD...',
        '..DSWwWwWwWSD...',
        '..DSwWwWwWwSD...',
        '..DSWwWwWwWSD...',
        '..DSsDsDsDsSD...',
        '..DSSSSSSSSSD...',
        '...DDDDDDDDD....',
        '....FFFFFFF.....',
        '................',
    ])

    # Cave entrance — dark archway in rock
    sprite(con, 's_cave_entrance', {
        'R': [85, 80, 75], 'r': [105, 100, 95], 'D': [60, 55, 50],
        'd': [40, 38, 35], 'B': [15, 12, 10], 'b': [25, 22, 18],
        'L': [120, 115, 105], 's': [90, 85, 75],
        '.': [0, 0, 0, 0],
    }, [
        '................................',
        '................................',
        '....RrRrRrRrRrRrRrRrRrRrRrRr....',
        '...rRRRRRRRRRRRRRRRRRRRRRRRRr...',
        '..rRRrRrRrRrRrRrRrRrRrRrRrRRr...',
        '.RRRRRRRRRRRRRRRRRRRRRRRRRRRRR..',
        '.RrRrRrRrRrRRRrRRRrRrRrRrRrRrR..',
        'RRRRRRRRRRdddddddddRRRRRRRRRRRR.',
        'rRRRRRRRdddBBBBBBBdddRRRRRRRRRRr',
        'RRRRRRddBBBBBBBBBBBBBddRRRRRRRRR',
        'RrRRddBBBBBBBBBBBBBBBBBddRRRRRrR',
        'RRRdBBBBBBBBBBBBBBBBBBBBBdRRRRRR',
        'rRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRr',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdBBBBBBBBBBBBBBBBBBBBBBBdRRRRR',
        'RRdsssssssssssssssssssssssdRRRRR',
        'rrLLLLLLLLLLLLLLLLLLLLLLLLLrrrrr',
        '.LLLLLLLLLLLLLLLLLLLLLLLLLLLLL..',
        '..LLLLLLLLLLLLLLLLLLLLLLLLLLL...',
        '...LLLLLLLLLLLLLLLLLLLLLLLLL....',
        '................................',
        '................................',
    ])

    # Wooden bed — for house interiors
    sprite(con, 's_bed', {
        'B': [80, 50, 30], 'b': [110, 75, 45], 'M': [200, 200, 220],
        'm': [180, 180, 200], 'P': [220, 100, 100], 'p': [180, 80, 80],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '.BBBBBBBBBBBBBB.',
        '.BMMMMMMMMMMMMB.',
        '.BMmMmMmMmMmMmB.',
        '.BMMMMMMMMMMMMB.',
        '.BPpPpPpPpPpPpB.',
        '.BMMMMMMMMMMMMB.',
        '.BMmMmMmMmMmMmB.',
        '.BMMMMMMMMMMMMB.',
        '.BBBBBBBBBBBBBB.',
        '.b............b.',
        '.b............b.',
        '................',
        '................',
        '................',
    ])

    # Hearth (cooking fire)
    sprite(con, 's_hearth', {
        'S': [100, 100, 105], 's': [130, 130, 135], 'D': [70, 70, 75],
        'F': [255, 100, 0], 'f': [255, 180, 0], 'r': [200, 50, 0],
        'k': [40, 20, 10], '.': [0, 0, 0, 0],
    }, [
        '................',
        '.SSSSSSSSSSSSSS.',
        '.SsSsSsSsSsSsSS.',
        '.SDDDDDDDDDDDDS.',
        '.SD..........DS.',
        '.SD..fF.Ff...DS.',
        '.SD.fFFrrFFf.DS.',
        '.SD.FrrFFrrF.DS.',
        '.SD..frFFrf..DS.',
        '.SD...kkk....DS.',
        '.SDDDDDDDDDDDDS.',
        '.SsSsSsSsSsSsSS.',
        '.SSSSSSSSSSSSSS.',
        '................',
        '................',
        '................',
    ])

    # Storage chest
    sprite(con, 's_chest', {
        'B': [80, 50, 25], 'b': [110, 75, 40], 'D': [50, 30, 15],
        'Y': [220, 180, 60], 'k': [30, 18, 8], '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '.DDDDDDDDDDDDDD.',
        '.DBBBBBBBBBBBBD.',
        '.DBbBbBbBbBbBbD.',
        '.DBBBBBYYBBBBBD.',
        '.DBBBBBYkBBBBBD.',
        '.DBBBBBBYBBBBBD.',
        '.DBbBbBbBbBbBbD.',
        '.DBBBBBBBBBBBBD.',
        '.DDDDDDDDDDDDDD.',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    # Signpost
    sprite(con, 's_sign', {
        'B': [80, 50, 25], 'b': [120, 80, 40], 'W': [240, 220, 180],
        'k': [40, 25, 10], '.': [0, 0, 0, 0],
    }, [
        '................',
        '....BBBBBBBB....',
        '....BWWWWWWB....',
        '....BWkkkWWB....',
        '....BWkWkWWB....',
        '....BWkWkWWB....',
        '....BWkkkWWB....',
        '....BWWWWWWB....',
        '....BBBbBBBB....',
        '.......b........',
        '.......b........',
        '.......b........',
        '.......b........',
        '.......b........',
        '.......b........',
        '................',
    ])

    # Treasure chest (cave reward) — same shape as storage chest but
    # with a glowing key icon
    sprite(con, 's_treasure', {
        'B': [110, 70, 30], 'b': [150, 100, 50], 'D': [70, 40, 15],
        'Y': [255, 215, 60], 'y': [220, 180, 40], 'W': [255, 255, 200],
        'k': [40, 25, 10], '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '.DDDDDDDDDDDDDD.',
        '.DBBBBBBBBBBBBD.',
        '.DBbBbBbWbBbBbD.',
        '.DBBBBBYWYBBBBD.',
        '.DBBBBYWkWYBBBD.',
        '.DBBBBBYWYBBBBD.',
        '.DBbBbBbWbBbBbD.',
        '.DBBBBBBBBBBBBD.',
        '.DDDDDDDDDDDDDD.',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    # ==================================================================
    # SPRITES — NPC composite (a humble villager)
    # ==================================================================
    #
    # Body, head, hat (variants), front-arm. Connected so the editor's
    # composite system can wave the arm in an idle animation.
    #
    # We deliberately reuse the body across NPCs but vary the hat
    # composite layer per NPC for visual differentiation.

    # Villager body — torso, legs, feet (16x16, head goes above)
    sprite(con, 'v_body', {
        'S': [220, 190, 160], 'B': [80, 50, 30], 'C': [70, 100, 140],
        'c': [90, 130, 170], 'P': [60, 50, 40], 'p': [80, 70, 50],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '................',
        '....SSSSSS......',
        '...CcCccCcC.....',
        '...CCcCcCcC.....',
        '...CCcCccCC.....',
        '....CCCCCC......',
        '....PPpPPp......',
        '....PpPpPp......',
        '....PpPpPp......',
        '....PpPpPp......',
        '....BB..BB......',
        '....BB..BB......',
        '...BBB..BBB.....',
        '................',
    ])

    # Villager head (16x16; sits above the body)
    sprite(con, 'v_head', {
        'S': [220, 190, 160], 's': [200, 170, 140], 'H': [80, 50, 30],
        'k': [30, 20, 10], 'm': [180, 130, 100],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '................',
        '......HHHHH.....',
        '.....HSSSSSH....',
        '....HSSSSSSSH...',
        '....HSkSSkSSH...',
        '....HSSSSSSSH...',
        '....HSmmmmSH....',
        '....HSSSSSSH....',
        '.....HSSSSSH....',
        '......sssss.....',
        '................',
        '................',
        '................',
        '................',
    ])

    # Hat variants (one each per major NPC)
    sprite(con, 'v_hat_mayor', {
        'P': [60, 30, 10], 'p': [80, 40, 15], 'Y': [220, 180, 60],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '....PPPPPPPP....',
        '...PpPpPpPpP....',
        '..PPPPPPPPPPP...',
        '.PPYYYYYYYPP....',
        '..PPPPPPPPP.....',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    sprite(con, 'v_hat_farmer', {
        'Y': [200, 170, 60], 'y': [220, 190, 80], 'B': [120, 90, 40],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '....YyYyYyYy....',
        '...YyYYYYYyY....',
        '..yYYYBBYYYYy...',
        '..YyyYYYYYyYY...',
        '..YYYYYYYYYYY...',
        '...YyyyyyyyY....',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    sprite(con, 'v_hat_smith', {
        'D': [60, 60, 65], 'd': [80, 80, 85], 'L': [110, 110, 115],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '....DDDDDDDD....',
        '...DdDdDdDdD....',
        '..DLLLLLLLLD....',
        '..DdDdDdDdDD....',
        '..DDDDDDDDDD....',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    sprite(con, 'v_hat_trader', {
        'P': [80, 40, 100], 'p': [110, 60, 130], 'Y': [220, 180, 60],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '....PPPPPPPP....',
        '...PpPpPpPpP....',
        '..PPYYYYYYYPP...',
        '..PpPpPpPpPpP...',
        '..PPPPPPPPPPP...',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    sprite(con, 'v_hat_healer', {
        'W': [240, 240, 250], 'w': [200, 210, 230], 'R': [180, 50, 50],
        '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '....WWWWWWWW....',
        '...WwWwWwWwW....',
        '..WWWWRRWWWWW...',
        '..WwWwRRWwWwW...',
        '..WWWWWWWWWWW...',
        '...WwWwWwWwW....',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    sprite(con, 'v_hat_guard', {
        'D': [80, 80, 90], 'd': [110, 110, 120], 'L': [150, 150, 160],
        'R': [180, 60, 60], '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '......RRRR......',
        '......RRRR......',
        '....DDDDDDDD....',
        '...DdLLLLLLdD...',
        '..DDDDDDDDDDD...',
        '...dDdDdDdDd....',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    # Cave bat (the hostile in the cave)
    sprite(con, 'c_bat', {
        'B': [40, 30, 50], 'b': [60, 50, 70], 'D': [25, 20, 35],
        'R': [200, 50, 50], 'k': [10, 8, 12], '.': [0, 0, 0, 0],
    }, [
        '................',
        '................',
        '...BB......BB...',
        '..BbBB....BBbB..',
        '.BbDBBB..BBBDbB.',
        '.BbDDBBBBBBDDbB.',
        '.BbDDBBkkBBDDbB.',
        '..BBBBkkkkBBBB..',
        '...BB.RRRR.BB...',
        '....k.kkkk.k....',
        '................',
        '................',
        '................',
        '................',
        '................',
        '................',
    ])

    # ==================================================================
    # COMPOSITE: villager (body + head + hat + arm wave)
    # ==================================================================

    # Wave arm — small overlay sprite
    sprite(con, 'v_arm', {
        'S': [220, 190, 160], 'B': [60, 40, 25], '.': [0, 0, 0, 0],
    }, [
        '....',
        '.SS.',
        '.SS.',
        '.BB.',
    ])

    def make_villager_composite(name, hat_sprite):
        con.execute('INSERT OR REPLACE INTO composite_sprites (name, root_layer) VALUES (?, ?)',
                    (name, 'body'))
        # Layers: body root, then head, hat, arm
        for layer, z, sprite_name in [
            ('body', 0, 'v_body'),
            ('head', 1, 'v_head'),
            ('hat',  2, hat_sprite),
            ('arm',  3, 'v_arm'),
        ]:
            con.execute(
                'INSERT OR REPLACE INTO composite_layers '
                '(composite_name, layer_name, z_layer, default_sprite) VALUES (?,?,?,?)',
                (name, layer, z, sprite_name))
        # Connections: head sits on top of body shoulders;
        # hat sits on top of head; arm sticks out to the right of body.
        for parent, child, psx, psy, cax, cay in [
            ('body', 'head', 8, 4, 8, 14),    # head's foot lands on body's collar
            ('head', 'hat',  8, 4, 8, 14),    # hat's brim lands on head's crown
            ('body', 'arm',  11, 6, 1, 1),    # arm's shoulder pivots on body's right
        ]:
            con.execute(
                '''INSERT OR REPLACE INTO layer_connections
                   (composite_name, parent_layer, child_layer,
                    parent_socket_x, parent_socket_y,
                    child_anchor_x, child_anchor_y)
                   VALUES (?,?,?,?,?,?,?)''',
                (name, parent, child, psx, psy, cax, cay))

        # Idle wave animation: arm rocks back and forth
        anim_name = f'{name}_wave'
        con.execute(
            'INSERT OR REPLACE INTO composite_animations '
            '(name, composite_name, loop, duration_ms) VALUES (?,?,?,?)',
            (anim_name, name, 1, 1600))
        con.execute('DELETE FROM composite_anim_keyframes WHERE animation_name=?',
                    (anim_name,))
        for time_ms, dx, dy in [
            (0,    0, 0),
            (200,  1, -1),
            (400,  2, -2),
            (600,  1, -1),
            (800,  0, 0),
            (1000, -1, 0),
            (1200, -2, 0),
            (1400, -1, 0),
        ]:
            con.execute(
                '''INSERT INTO composite_anim_keyframes
                   (animation_name, layer_name, time_ms, offset_x, offset_y)
                   VALUES (?,?,?,?,?)''',
                (anim_name, 'arm', time_ms, dx, dy))
        con.execute(
            'INSERT OR REPLACE INTO composite_anim_bindings '
            '(target_name, behavior, animation_name, flip_h) VALUES (?,?,?,?)',
            (name, 'idle', anim_name, 0))

    make_villager_composite('villager_mayor',  'v_hat_mayor')
    make_villager_composite('villager_farmer', 'v_hat_farmer')
    make_villager_composite('villager_smith',  'v_hat_smith')
    make_villager_composite('villager_trader', 'v_hat_trader')
    make_villager_composite('villager_healer', 'v_hat_healer')
    make_villager_composite('villager_guard',  'v_hat_guard')

    # ==================================================================
    # TILE TEMPLATES
    # ==================================================================

    tile_template(con, 'tt_grass', 'Grass', sprite_name='t_grass',
                   bg_color='#3a7a3a', purpose='exploring')
    tile_template(con, 'tt_cobble', 'Cobblestone', sprite_name='t_cobble',
                   bg_color='#888888', purpose='socializing')
    tile_template(con, 'tt_path', 'Dirt Path', sprite_name='t_path',
                   bg_color='#9a7050', speed_modifier=1.2)
    tile_template(con, 'tt_pond', 'Pond', sprite_name='t_pond',
                   bg_color='#1a4880', liquid=1, depth=2,
                   purpose='fishing', walkable=0)
    tile_template(con, 'tt_pond_shallow', 'Pond Edge', sprite_name='t_pond',
                   bg_color='#3060a0', liquid=1, depth=0,
                   purpose='fishing')
    tile_template(con, 'tt_stream', 'Stream', sprite_name='t_stream',
                   bg_color='#2870b8', liquid=1, depth=1,
                   flow_direction='S', flow_speed=2.0,
                   purpose='fishing', walkable=0)
    tile_template(con, 'tt_field', 'Wheat Field', sprite_name='t_field',
                   bg_color='#a07030', purpose='farming')
    tile_template(con, 'tt_wood_floor', 'Wood Floor', sprite_name='t_wood_floor',
                   bg_color='#9a6840')
    tile_template(con, 'tt_cave_floor', 'Cave Floor', sprite_name='t_cave_floor',
                   bg_color='#3a3838')

    # ==================================================================
    # ITEMS — quest target + a few new props
    # ==================================================================

    insert_item(con, 'Item', 'q_lost_locket', 'Mayor\'s Lost Locket',
                description='A silver locket the Mayor lost in the cave years ago.',
                weight=0.1, value=50,
                action_word='hold')

    insert_item(con, 'Consumable', 'food_apple', 'Apple',
                description='A crisp red apple.',
                weight=0.1, value=2, max_stack_size=20, quantity=1,
                heal_amount=2, duration=0, is_food=1, action_word='eat')

    print('  sprites + tile templates + items seeded')

    # ==================================================================
    # MAP: TEST TOWN — 24x24 hand-placed
    # ==================================================================

    map_row(con, 'test_town', 'tt_set_test_town', 'tt_grass',
            x_max=23, y_max=23, entrance_x=12, entrance_y=12)
    con.execute('DELETE FROM tile_sets WHERE tile_set = ?', ('tt_set_test_town',))

    # Helper for tile placement
    def town(x, y, template, **overrides):
        tile_set_entry(con, 'tt_set_test_town', x, y, 0, template, **overrides)

    # Roads (cobblestone) — town square 4x4 in the middle
    for x in range(10, 14):
        for y in range(10, 14):
            town(x, y, 'tt_cobble')

    # North-south road through the middle
    for y in range(0, 24):
        town(12, y, 'tt_path')
    # East-west road through the middle
    for x in range(0, 24):
        town(x, 12, 'tt_path')
    # Square overrides path
    for x in range(10, 14):
        for y in range(10, 14):
            town(x, y, 'tt_cobble')

    # Houses — 5 of them, each a single nested-map tile around the square
    # Each house tile links to its interior map.
    house_locations = [
        (8,  8,  'house_north_west'),
        (15, 8,  'house_north_east'),
        (8,  15, 'house_south_west'),
        (15, 15, 'house_south_east'),
        (15, 5,  'house_far_north'),
    ]
    for hx, hy, hmap in house_locations:
        town(hx, hy, 'tt_path', linked_map=hmap, linked_x=4, linked_y=6,
             link_auto=0)

    # Wheat fields to the south (south-west region)
    for x in range(2, 8):
        for y in range(17, 22):
            town(x, y, 'tt_field')

    # Pond to the east — central oval at columns 19-22, rows 14-19
    pond_cells = [
        (19, 15), (20, 15), (21, 15),
        (18, 16), (19, 16), (20, 16), (21, 16), (22, 16),
        (18, 17), (19, 17), (20, 17), (21, 17), (22, 17),
        (18, 18), (19, 18), (20, 18), (21, 18), (22, 18),
        (19, 19), (20, 19), (21, 19),
    ]
    for px, py in pond_cells:
        town(px, py, 'tt_pond')
    # Pond edges (shallow)
    for px, py in [(19, 14), (20, 14), (21, 14),
                    (17, 16), (17, 17), (17, 18),
                    (23, 16), (23, 17), (23, 18),
                    (19, 20), (20, 20), (21, 20)]:
        town(px, py, 'tt_pond_shallow')

    # Stream flowing south into the pond — column 20, rows 0-14
    for y in range(0, 15):
        town(20, y, 'tt_stream')

    # Cave entrance to the west — at (1, 12), linked to cave map
    town(1, 12, 'tt_path', linked_map='cave_test', linked_x=6, linked_y=10,
         link_auto=0)

    print('  test_town map (24x24) generated')

    # ==================================================================
    # HOUSE INTERIORS — 5 small 8x8 maps
    # ==================================================================

    for hx, hy, hmap in house_locations:
        map_row(con, hmap, f'tt_set_{hmap}', 'tt_wood_floor',
                x_max=7, y_max=7, entrance_x=4, entrance_y=6)
        con.execute('DELETE FROM tile_sets WHERE tile_set = ?', (f'tt_set_{hmap}',))

        def h(x, y, template, **overrides):
            tile_set_entry(con, f'tt_set_{hmap}', x, y, 0, template, **overrides)

        # Wood floor everywhere
        for x in range(8):
            for y in range(8):
                h(x, y, 'tt_wood_floor')
        # Bed in the corner
        h(1, 1, 'tt_wood_floor', purpose='sleeping')
        h(2, 1, 'tt_wood_floor', purpose='sleeping')
        # Hearth + cooking area
        h(5, 1, 'tt_wood_floor', purpose='eating')
        h(6, 1, 'tt_wood_floor', purpose='eating')
        # Crafting bench
        h(1, 5, 'tt_wood_floor', purpose='crafting')
        # Worship corner
        h(6, 5, 'tt_wood_floor', purpose='worship')
        # Exit links back to town at the original house position
        h(4, 7, 'tt_wood_floor', linked_map='test_town',
          linked_x=hx, linked_y=hy + 1, link_auto=0)

    print('  5 house interiors seeded')

    # ==================================================================
    # CAVE MAP — 12x12, dim stone, treasure + bat enemy + quest item
    # ==================================================================

    map_row(con, 'cave_test', 'tt_set_cave_test', 'tt_cave_floor',
            x_max=11, y_max=11, entrance_x=6, entrance_y=10)
    con.execute('DELETE FROM tile_sets WHERE tile_set = ?', ('tt_set_cave_test',))

    def cave(x, y, template, **overrides):
        tile_set_entry(con, 'tt_set_cave_test', x, y, 0, template, **overrides)

    for x in range(12):
        for y in range(12):
            cave(x, y, 'tt_cave_floor')
    # The locket sits at the back of the cave (4, 3) — quest target.
    # We can't place an item directly via tile_sets; it'll be placed
    # at game runtime when the cave map is loaded. Mark the tile so
    # the runtime knows where.
    cave(4, 3, 'tt_cave_floor', search_text='locket_spawn')
    cave(8, 3, 'tt_cave_floor', search_text='treasure_spawn')
    cave(6, 6, 'tt_cave_floor', search_text='bat_spawn')
    # Exit back to town at the south edge
    cave(6, 11, 'tt_cave_floor', linked_map='test_town',
         linked_x=2, linked_y=12, link_auto=0)

    print('  cave_test map (12x12) seeded with locket/treasure/bat markers')

    # ==================================================================
    # NPCs — 6 villagers
    # ==================================================================

    # Stats: light defaults appropriate for non-combat NPCs
    insert_creature(con, 'npc_mayor', 'Mayor Eldon', 'human', 'male', 56,
                     deity='Solmara', gold=120, items=['food_bread'],
                     spawn_map='test_town', spawn_x=12, spawn_y=11,
                     dialogue_tree='greeting',
                     **{'strength': 8, 'vitality': 12, 'intelligence': 14,
                        'agility': 6, 'perception': 11, 'charisma': 16, 'luck': 10})
    insert_creature(con, 'npc_farmer', 'Farmer Peg', 'human', 'female', 42,
                     gold=20, items=['food_wheat_raw', 'food_apple'],
                     spawn_map='test_town', spawn_x=6, spawn_y=18,
                     dialogue_tree='greeting',
                     **{'strength': 12, 'vitality': 14, 'intelligence': 9,
                        'agility': 11, 'perception': 12, 'charisma': 10, 'luck': 8})
    insert_creature(con, 'npc_smith', 'Smith Bram', 'human', 'male', 38,
                     gold=60, items=['i_sword_short'],
                     spawn_map='test_town', spawn_x=14, spawn_y=10,
                     **{'strength': 16, 'vitality': 14, 'intelligence': 11,
                        'agility': 10, 'perception': 10, 'charisma': 9, 'luck': 9})
    insert_creature(con, 'npc_trader', 'Trader Lila', 'human', 'female', 31,
                     gold=200, items=['food_bread', 'food_apple', 'potion_health'],
                     spawn_map='test_town', spawn_x=10, spawn_y=13,
                     **{'strength': 9, 'vitality': 11, 'intelligence': 13,
                        'agility': 12, 'perception': 13, 'charisma': 15, 'luck': 12})
    insert_creature(con, 'npc_healer', 'Healer Yara', 'human', 'female', 47,
                     deity='Aelora', gold=45, items=['potion_health', 'potion_mana'],
                     spawn_map='test_town', spawn_x=13, spawn_y=13,
                     **{'strength': 8, 'vitality': 11, 'intelligence': 16,
                        'agility': 9, 'perception': 12, 'charisma': 13, 'luck': 10})
    insert_creature(con, 'npc_guard', 'Guardsman Tovin', 'human', 'male', 29,
                     gold=35, items=['i_sword_long'],
                     spawn_map='test_town', spawn_x=11, spawn_y=10,
                     **{'strength': 15, 'vitality': 14, 'intelligence': 10,
                        'agility': 13, 'perception': 14, 'charisma': 10, 'luck': 9})

    print('  6 NPCs seeded')

    # ==================================================================
    # DIALOGUE — Mayor (cave quest) + Farmer (pond quest)
    # ==================================================================

    con.execute("DELETE FROM dialogue WHERE creature_key IN ('npc_mayor', 'npc_farmer')")

    # Mayor — cave quest
    def dlg(creature_key, conv, parent, speaker, text, sort=0,
             effects='{}'):
        cur = con.execute(
            'INSERT INTO dialogue (conversation, creature_key, parent_id, '
            'speaker, text, sort_order, effects) VALUES (?,?,?,?,?,?,?)',
            (conv, creature_key, parent, speaker, text, sort, effects)
        )
        return cur.lastrowid

    m1 = dlg('npc_mayor', 'greeting', None, 'npc',
              'Welcome to our little town, traveler. I am Mayor Eldon. '
              'You look capable. Could I trouble you with a small matter?')
    dlg('npc_mayor', 'greeting', m1, 'player',
         'What\'s the matter?', 1)
    m2 = dlg('npc_mayor', 'greeting', m1, 'npc',
              'Years ago I lost a silver locket in the cave to the west. '
              'It belonged to my mother. The cave is dangerous now — bats '
              'have moved in — but if you find the locket I\'ll reward you.',
              2, effects='{"start_quest": "lost_locket"}')
    dlg('npc_mayor', 'greeting', m2, 'player',
         'I\'ll see what I can do.', 1)

    # Farmer — pond quest
    f1 = dlg('npc_farmer', 'greeting', None, 'npc',
              'Hullo there. Peg\'s the name. You wouldn\'t happen to be a '
              'fisher, would you? Our pond\'s gone strange of late.')
    dlg('npc_farmer', 'greeting', f1, 'player',
         'Strange how?', 1)
    f2 = dlg('npc_farmer', 'greeting', f1, 'npc',
              'The fish have gone deeper than my line will reach. If you '
              'could catch even one for me to study, I\'d be grateful. '
              'Stand at the pond\'s edge and try your luck.',
              2, effects='{"start_quest": "pond_fish"}')
    dlg('npc_farmer', 'greeting', f2, 'player',
         'I\'ll catch you a fish.', 1)

    print('  dialogue trees for mayor and farmer seeded')

    # ==================================================================
    # QUESTS
    # ==================================================================

    con.execute("DELETE FROM quests WHERE name IN ('lost_locket', 'pond_fish')")
    con.execute("DELETE FROM quest_steps WHERE quest_name IN ('lost_locket', 'pond_fish')")

    con.execute(
        'INSERT INTO quests (name, giver, description, quest_type, '
        'reward_action, repeatable) VALUES (?,?,?,?,?,?)',
        ('lost_locket', 'npc_mayor',
         'Recover the Mayor\'s lost silver locket from the cave to the west.',
         'fetch', '{"give_gold": 100, "give_xp": 50}', 0))
    con.execute(
        'INSERT INTO quest_steps (quest_name, step_no, step_sub, description, '
        'success_condition, success_action, step_map, step_location_x, step_location_y) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        ('lost_locket', 1, 'a',
         'Travel to the cave west of town.',
         '{"location_in": "cave_test"}',
         '{}', 'cave_test', 6, 6))
    con.execute(
        'INSERT INTO quest_steps (quest_name, step_no, step_sub, description, '
        'success_condition, success_action, step_map, step_location_x, step_location_y) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        ('lost_locket', 2, 'a',
         'Find and pick up the silver locket.',
         '{"has_item": "q_lost_locket"}',
         '{}', 'cave_test', 4, 3))
    con.execute(
        'INSERT INTO quest_steps (quest_name, step_no, step_sub, description, '
        'success_condition, success_action, step_map, step_location_x, step_location_y, step_npc) '
        'VALUES (?,?,?,?,?,?,?,?,?,?)',
        ('lost_locket', 3, 'a',
         'Return to Mayor Eldon in the town square.',
         '{"talk_to": "npc_mayor"}',
         '{}', 'test_town', 12, 11, 'npc_mayor'))

    con.execute(
        'INSERT INTO quests (name, giver, description, quest_type, '
        'reward_action, repeatable) VALUES (?,?,?,?,?,?)',
        ('pond_fish', 'npc_farmer',
         'Catch a fish from the pond on the east side of town for Farmer Peg.',
         'fetch', '{"give_gold": 25, "give_xp": 20}', 0))
    con.execute(
        'INSERT INTO quest_steps (quest_name, step_no, step_sub, description, '
        'success_condition, success_action, step_map, step_location_x, step_location_y) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        ('pond_fish', 1, 'a',
         'Stand at the edge of the pond and harvest a fish.',
         '{"has_item": "food_fish_raw"}',
         '{}', 'test_town', 18, 17))
    con.execute(
        'INSERT INTO quest_steps (quest_name, step_no, step_sub, description, '
        'success_condition, success_action, step_map, step_location_x, step_location_y, step_npc) '
        'VALUES (?,?,?,?,?,?,?,?,?,?)',
        ('pond_fish', 2, 'a',
         'Bring the fish back to Farmer Peg.',
         '{"talk_to": "npc_farmer"}',
         '{}', 'test_town', 6, 18, 'npc_farmer'))

    print('  2 quests seeded')

    con.commit()
    con.close()
    print('Test Town seeded successfully.')


if __name__ == '__main__':
    seed()
