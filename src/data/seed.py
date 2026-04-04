"""
Populate src/data/game.db from scratch.
Run from the src/ directory:  python data/seed.py
"""
import sqlite3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

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
    class                      TEXT NOT NULL DEFAULT 'item',
    key                        TEXT PRIMARY KEY,
    name                       TEXT NOT NULL DEFAULT '',
    description                TEXT NOT NULL DEFAULT '',
    weight                     REAL NOT NULL DEFAULT 0,
    value                      REAL NOT NULL DEFAULT 0,
    sprite_name                TEXT REFERENCES sprites(name),
    inventoriable              INTEGER NOT NULL DEFAULT 1,
    buffs                      TEXT NOT NULL DEFAULT '{}',
    max_stack_size             INTEGER,
    quantity                   INTEGER,
    duration                   REAL,
    destroy_on_use_probability REAL,
    slot_count                 INTEGER,
    durability_max             INTEGER,
    durability_current         INTEGER,
    render_on_creature         INTEGER,
    damage                     REAL,
    attack_time_ms             INTEGER,
    directions                 TEXT,
    range                      INTEGER,
    ammunition_type            TEXT
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
    con.commit()
    con.close()
    print(f"Created empty database at {DB_PATH}")
    print("Use the editor (python editor.py) to populate data.")


if __name__ == '__main__':
    seed()
