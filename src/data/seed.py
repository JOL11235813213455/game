"""
Populate src/data/game.db from the existing Python data files.
Run from the src/ directory:  python data/seed.py
"""
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from classes.inventory import _ITEM_DEFAULTS

# Import raw data directly — before the shims are installed
from data.species import PLAYABLE, NONPLAYABLE
from data.items import ITEMS
from data.sprites import SPRITE_DATA

DB_PATH = Path(__file__).parent / 'game.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS species (
    name        TEXT PRIMARY KEY,
    playable    INTEGER NOT NULL,
    sprite_name TEXT REFERENCES sprites(name)
);
CREATE TABLE IF NOT EXISTS species_stats (
    species_name TEXT NOT NULL REFERENCES species(name),
    stat         TEXT NOT NULL,
    value        INTEGER NOT NULL,
    PRIMARY KEY (species_name, stat)
);
CREATE TABLE IF NOT EXISTS items (
    key                TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    item_type          TEXT NOT NULL,
    state              TEXT NOT NULL,
    value              INTEGER NOT NULL DEFAULT 0,
    weight             INTEGER NOT NULL DEFAULT 0,
    damage             INTEGER NOT NULL DEFAULT 0,
    defense            INTEGER NOT NULL DEFAULT 0,
    health             INTEGER NOT NULL DEFAULT 0,
    poison             INTEGER NOT NULL DEFAULT 0,
    equippable         INTEGER NOT NULL DEFAULT 1,
    slot_count         INTEGER NOT NULL DEFAULT 1,
    consumable         INTEGER NOT NULL DEFAULT 0,
    stackable          INTEGER NOT NULL DEFAULT 0,
    quantity           INTEGER NOT NULL DEFAULT 1,
    durability         INTEGER NOT NULL DEFAULT 100,
    durability_current INTEGER NOT NULL DEFAULT 100,
    sprite_name        TEXT REFERENCES sprites(name)
);
CREATE TABLE IF NOT EXISTS item_slots (
    item_key TEXT NOT NULL REFERENCES items(key),
    slot     TEXT NOT NULL,
    PRIMARY KEY (item_key, slot)
);
CREATE TABLE IF NOT EXISTS sprites (
    name    TEXT PRIMARY KEY,
    palette TEXT NOT NULL,
    pixels  TEXT NOT NULL
);
"""


def seed():
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    # Species
    for name, stats in PLAYABLE.items():
        con.execute('INSERT INTO species VALUES (?, 1)', (name,))
        for stat_enum, val in stats.items():
            con.execute('INSERT INTO species_stats VALUES (?, ?, ?)', (name, stat_enum.value, val))

    for name, stats in NONPLAYABLE.items():
        con.execute('INSERT INTO species VALUES (?, 0)', (name,))
        for stat_enum, val in stats.items():
            con.execute('INSERT INTO species_stats VALUES (?, ?, ?)', (name, stat_enum.value, val))

    # Items
    def g(item, attr):
        return getattr(item, attr, _ITEM_DEFAULTS[attr])

    for key, item in ITEMS.items():
        con.execute(
            '''INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                key
                ,g(item, 'name')
                ,g(item, 'description')
                ,g(item, 'item_type').value
                ,g(item, 'state').value
                ,g(item, 'value')
                ,g(item, 'weight')
                ,g(item, 'damage')
                ,g(item, 'defense')
                ,g(item, 'health')
                ,int(g(item, 'poison'))
                ,int(g(item, 'equippable'))
                ,g(item, 'slot_count')
                ,int(g(item, 'consumable'))
                ,int(g(item, 'stackable'))
                ,g(item, 'quantity')
                ,g(item, 'durability')
                ,g(item, 'durability_current')
            )
        )
        for slot_enum in g(item, 'slots'):
            con.execute('INSERT INTO item_slots VALUES (?, ?)', (key, slot_enum.value))

    # Sprites
    for name, data in SPRITE_DATA.items():
        con.execute(
            'INSERT INTO sprites VALUES (?, ?, ?)',
            (
                name
                ,json.dumps({char: list(rgb) for char, rgb in data['palette'].items()})
                ,json.dumps(data['pixels'])
            )
        )

    con.commit()
    con.close()
    print(f"Seeded {DB_PATH}")
    print(f"  {len(PLAYABLE)} playable species, {len(NONPLAYABLE)} non-playable species")
    print(f"  {len(ITEMS)} items")
    print(f"  {len(SPRITE_DATA)} sprites")


if __name__ == '__main__':
    seed()
