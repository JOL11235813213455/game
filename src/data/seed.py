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
    sprite_name TEXT REFERENCES sprites(name),
    tile_scale  REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE IF NOT EXISTS species_stats (
    species_name TEXT NOT NULL REFERENCES species(name),
    stat         TEXT NOT NULL,
    value        INTEGER NOT NULL,
    PRIMARY KEY (species_name, stat)
);
CREATE TABLE IF NOT EXISTS items (
    class                      TEXT NOT NULL DEFAULT 'Item',
    key                        TEXT PRIMARY KEY,
    name                       TEXT NOT NULL DEFAULT '',
    description                TEXT NOT NULL DEFAULT '',
    weight                     REAL NOT NULL DEFAULT 0,
    value                      REAL NOT NULL DEFAULT 0,
    sprite_name                TEXT REFERENCES sprites(name),
    inventoriable              INTEGER NOT NULL DEFAULT 1,
    collision                  INTEGER NOT NULL DEFAULT 0,
    tile_scale                 REAL NOT NULL DEFAULT 1.0,
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
    ammunition_type            TEXT,
    footprint                  TEXT,
    collision_mask             TEXT,
    entry_points               TEXT,
    nested_map                 TEXT
);
CREATE TABLE IF NOT EXISTS item_slots (
    item_key TEXT NOT NULL REFERENCES items(key),
    slot     TEXT NOT NULL,
    PRIMARY KEY (item_key, slot)
);
CREATE TABLE IF NOT EXISTS sprites (
    name           TEXT PRIMARY KEY,
    palette        TEXT NOT NULL,
    pixels         TEXT NOT NULL,
    width          INTEGER NOT NULL DEFAULT 32,
    height         INTEGER NOT NULL DEFAULT 32,
    action_point_x INTEGER,
    action_point_y INTEGER
);
CREATE TABLE IF NOT EXISTS tiles (
    key         TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    walkable    INTEGER NOT NULL DEFAULT 1,
    covered     INTEGER NOT NULL DEFAULT 0,
    sprite_name TEXT REFERENCES sprites(name),
    tile_scale  REAL NOT NULL DEFAULT 1.0,
    bounds_n    TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w  TEXT,
    bounds_ne   TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT,
    animation_name TEXT REFERENCES animations(name)
);
CREATE TABLE IF NOT EXISTS tile_sets (
    name TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS tile_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tile_set      TEXT NOT NULL REFERENCES tile_sets(name),
    w             INTEGER NOT NULL DEFAULT 0,
    x             INTEGER NOT NULL,
    y             INTEGER NOT NULL,
    z             INTEGER NOT NULL DEFAULT 0,
    tile_template TEXT REFERENCES tiles(key),
    walkable      INTEGER,
    covered       INTEGER,
    sprite_name   TEXT REFERENCES sprites(name),
    tile_scale    REAL,
    bounds_n      TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w  TEXT,
    bounds_ne     TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT,
    nested_map    TEXT REFERENCES maps(name)
);
CREATE TABLE IF NOT EXISTS maps (
    name         TEXT PRIMARY KEY,
    tile_set     TEXT REFERENCES tile_sets(name),
    default_tile TEXT REFERENCES tiles(key),
    entrance_x   INTEGER NOT NULL DEFAULT 0,
    entrance_y   INTEGER NOT NULL DEFAULT 0,
    w_min INTEGER NOT NULL DEFAULT 0,  w_max INTEGER NOT NULL DEFAULT 0,
    x_min INTEGER NOT NULL DEFAULT 0,  x_max INTEGER NOT NULL DEFAULT 0,
    y_min INTEGER NOT NULL DEFAULT 0,  y_max INTEGER NOT NULL DEFAULT 0,
    z_min INTEGER NOT NULL DEFAULT 0,  z_max INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS animations (
    name        TEXT PRIMARY KEY,
    target_type TEXT NOT NULL DEFAULT 'creature'
);
CREATE TABLE IF NOT EXISTS animation_frames (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    animation_name  TEXT    NOT NULL REFERENCES animations(name),
    frame_index     INTEGER NOT NULL,
    sprite_name     TEXT    NOT NULL REFERENCES sprites(name),
    duration_ms     INTEGER NOT NULL DEFAULT 150,
    UNIQUE(animation_name, frame_index)
);
CREATE TABLE IF NOT EXISTS animation_bindings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name     TEXT NOT NULL,
    behavior        TEXT NOT NULL DEFAULT 'idle',
    animation_name  TEXT NOT NULL REFERENCES animations(name),
    UNIQUE(target_name, behavior)
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
