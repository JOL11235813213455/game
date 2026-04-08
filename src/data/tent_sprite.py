"""
Insert the pairing tent sprite into game.db.

Run from src/:  python data/tent_sprite.py
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / 'game.db'

TENT_NAME = 'tent_pairing'
TENT_WIDTH = 32
TENT_HEIGHT = 32

# Palette: R=red, W=white, G=gold(peak), P=pole(brown), D=dark red, .=transparent
PALETTE = {
    'R': [200, 30, 30],
    'W': [240, 230, 220],
    'D': [140, 20, 20],
    'G': [220, 180, 40],
    'P': [100, 70, 40],
    'B': [60, 40, 25],
}

# 32x32 circus tent — peaked top, alternating red/white stripes, brown poles
PIXELS = [
    '................GG................',  # 0 - peak finial
    '...............GGGG...............',  # 1
    '..............GRRRRG..............',  # 2
    '.............RRRRRRRR.............',  # 3
    '............RRRRWWRRRR............',  # 4
    '...........RRRWWWWWWRRR...........',  # 5
    '..........RRRWWWWWWWWRRR..........',  # 6
    '.........RRWWWWWWWWWWWWRR.........',  # 7
    '........RRWWWWRRRRRRWWWWRR........',  # 8
    '.......RRWWWRRRRRRRRRRWWWRR.......',  # 9
    '......RRWWRRRRRRRRRRRRRRWWRR......',  # 10
    '.....RRWWRRRRWWWWWWRRRRRRWWRR.....',  # 11
    '....RRWWRRRWWWWWWWWWWRRRRWWWRR....',  # 12
    '...RRWWRRWWWWWWWWWWWWWWRRRRWWRR...',  # 13
    '..RRWWRRWWWWRRRRRRRRWWWWRRRRWWRR..',  # 14
    '.RRWWRRWWWRRRRRRRRRRRRWWWRRRRWWRR.',  # 15
    'RRWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWRR',  # 16 - widest point
    'DDWWDDWWWDDDDDDDDDDDDDDWWWDDDDWWD',  # 17 - scalloped edge
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 18 - poles start
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 19
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 20
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 21
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 22
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 23
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 24
    '.PWWRRWWWRRRRRRRRRRRRRRWWWRRRRWWP.',  # 25
    '.PDDRRDDDDDDDDDDDDDDDDDDDDDDDWP.',  # 26 - ground line
    '.PB..............................P.',  # 27 - entrance dark
    '.PB..............................P.',  # 28
    '.PB..............................P.',  # 29
    '.PP..............................PP.',  # 30 - pole bases
    '..BB............................BB..',  # 31 - pole feet
]

# Trim to exactly 32 chars wide
PIXELS = [row[:TENT_WIDTH].ljust(TENT_WIDTH, '.') for row in PIXELS]


def insert_tent():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Check if already exists
    existing = con.execute('SELECT name FROM sprites WHERE name=?', (TENT_NAME,)).fetchone()
    if existing:
        con.execute('DELETE FROM sprites WHERE name=?', (TENT_NAME,))

    con.execute(
        'INSERT INTO sprites (name, palette, pixels, width, height, action_point_x, action_point_y) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            TENT_NAME,
            json.dumps(PALETTE),
            json.dumps(PIXELS),
            TENT_WIDTH,
            TENT_HEIGHT,
            TENT_WIDTH // 2,  # action point at center bottom
            TENT_HEIGHT,
        )
    )
    con.commit()
    con.close()
    print(f"Inserted sprite '{TENT_NAME}' ({TENT_WIDTH}x{TENT_HEIGHT})")


if __name__ == '__main__':
    insert_tent()
