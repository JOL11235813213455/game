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
    name               TEXT PRIMARY KEY,
    playable           INTEGER NOT NULL,
    sprite_name        TEXT REFERENCES sprites(name),
    sprite_name_f      TEXT REFERENCES sprites(name),
    composite_name     TEXT,
    composite_name_f   TEXT,
    tile_scale         REAL NOT NULL DEFAULT 1.0,
    size               TEXT NOT NULL DEFAULT 'medium',
    description        TEXT NOT NULL DEFAULT '',
    prudishness        REAL NOT NULL DEFAULT 0.5,
    base_move_speed    REAL NOT NULL DEFAULT 4.0,
    lifespan           INTEGER NOT NULL DEFAULT 365,
    maturity_age       INTEGER NOT NULL DEFAULT 18,
    young_max          INTEGER NOT NULL DEFAULT 30,
    fecundity_peak     INTEGER NOT NULL DEFAULT 100,
    fecundity_end      INTEGER NOT NULL DEFAULT 300,
    aggression         REAL NOT NULL DEFAULT 0.3,
    sociability        REAL NOT NULL DEFAULT 0.5,
    territoriality     REAL NOT NULL DEFAULT 0.3,
    curiosity_modifier REAL NOT NULL DEFAULT 0.0,
    preferred_deity    TEXT,
    egg_sprite         TEXT REFERENCES sprites(name)
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
    hit_dice                   INTEGER,
    hit_dice_count             INTEGER,
    crit_chance_mod            INTEGER,
    crit_damage_mod            REAL,
    stagger_dc                 INTEGER,
    stamina_cost               INTEGER,
    status_effect              TEXT,
    status_dc                  INTEGER,
    heal_amount                INTEGER,
    mana_restore               INTEGER,
    stamina_restore            INTEGER,
    recoverable                INTEGER,
    action_word                TEXT NOT NULL DEFAULT '',
    requirements               TEXT NOT NULL DEFAULT '{}',
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
CREATE TABLE IF NOT EXISTS creatures (
    key              TEXT PRIMARY KEY,
    name             TEXT NOT NULL DEFAULT '',
    title            TEXT NOT NULL DEFAULT '',
    species          TEXT NOT NULL REFERENCES species(name),
    level            INTEGER,
    sex              TEXT,
    age              INTEGER,
    prudishness      REAL,
    behavior         TEXT,
    items            TEXT NOT NULL DEFAULT '[]',
    deity            TEXT,
    piety            REAL,
    gold             INTEGER,
    observation_mask TEXT,
    is_unique        INTEGER NOT NULL DEFAULT 1,
    spawn_map        TEXT,
    spawn_x          INTEGER,
    spawn_y          INTEGER,
    dialogue_tree    TEXT,
    description      TEXT NOT NULL DEFAULT '',
    cumulative_limit INTEGER NOT NULL DEFAULT -1,
    concurrent_limit INTEGER NOT NULL DEFAULT -1
);
CREATE TABLE IF NOT EXISTS creature_stats (
    creature_key TEXT NOT NULL REFERENCES creatures(key),
    stat         TEXT NOT NULL,
    value        INTEGER NOT NULL,
    PRIMARY KEY (creature_key, stat)
);
CREATE TABLE IF NOT EXISTS spells (
    key                TEXT PRIMARY KEY,
    name               TEXT NOT NULL DEFAULT '',
    description        TEXT NOT NULL DEFAULT '',
    action_word        TEXT NOT NULL DEFAULT 'cast',
    damage             REAL NOT NULL DEFAULT 0,
    mana_cost          INTEGER NOT NULL DEFAULT 0,
    stamina_cost       INTEGER NOT NULL DEFAULT 0,
    range              INTEGER NOT NULL DEFAULT 5,
    radius             INTEGER NOT NULL DEFAULT 0,
    spell_dc           INTEGER NOT NULL DEFAULT 10,
    dodgeable          INTEGER NOT NULL DEFAULT 1,
    target_type        TEXT NOT NULL DEFAULT 'single',
    effect_type        TEXT NOT NULL DEFAULT 'damage',
    buffs              TEXT NOT NULL DEFAULT '{}',
    duration           REAL NOT NULL DEFAULT 0,
    secondary_resist   TEXT,
    secondary_dc       INTEGER,
    requirements       TEXT NOT NULL DEFAULT '{}',
    sprite_name        TEXT REFERENCES sprites(name),
    animation_name     TEXT REFERENCES animations(name),
    composite_name     TEXT
);
CREATE TABLE IF NOT EXISTS creature_spells (
    creature_key TEXT NOT NULL,
    spell_key    TEXT NOT NULL REFERENCES spells(key),
    PRIMARY KEY (creature_key, spell_key)
);
CREATE TABLE IF NOT EXISTS species_spells (
    species_name TEXT NOT NULL REFERENCES species(name),
    spell_key    TEXT NOT NULL REFERENCES spells(key),
    PRIMARY KEY (species_name, spell_key)
);
CREATE TABLE IF NOT EXISTS quests (
    name             TEXT PRIMARY KEY,
    giver            TEXT NOT NULL REFERENCES creatures(key),
    description      TEXT NOT NULL DEFAULT '',
    quest_type       TEXT NOT NULL DEFAULT 'quest',
    conditions       TEXT NOT NULL DEFAULT '{}',
    reward_action    TEXT NOT NULL DEFAULT '',
    fail_action      TEXT NOT NULL DEFAULT '',
    time_limit       INTEGER,
    repeatable       INTEGER NOT NULL DEFAULT 0,
    cooldown_days    INTEGER
);
CREATE TABLE IF NOT EXISTS quest_steps (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_name       TEXT NOT NULL REFERENCES quests(name),
    step_no          INTEGER NOT NULL,
    step_sub         TEXT NOT NULL DEFAULT 'a',
    description      TEXT NOT NULL DEFAULT '',
    success_condition TEXT NOT NULL DEFAULT '',
    fail_condition   TEXT NOT NULL DEFAULT '',
    success_action   TEXT NOT NULL DEFAULT '',
    fail_action      TEXT NOT NULL DEFAULT '',
    step_map         TEXT,
    step_location_x  INTEGER,
    step_location_y  INTEGER,
    step_npc         TEXT,
    time_limit       INTEGER,
    UNIQUE(quest_name, step_no, step_sub)
);
CREATE TABLE IF NOT EXISTS gods (
    name             TEXT PRIMARY KEY,
    domain           TEXT NOT NULL DEFAULT '',
    opposed_god      TEXT REFERENCES gods(name),
    aligned_actions  TEXT NOT NULL DEFAULT '[]',
    opposed_actions  TEXT NOT NULL DEFAULT '[]',
    description      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dialogue (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation      TEXT NOT NULL,
    species           TEXT REFERENCES species(name),
    creature_key      TEXT REFERENCES creatures(key),
    parent_id         INTEGER REFERENCES dialogue(id),
    speaker           TEXT NOT NULL DEFAULT 'npc',
    text              TEXT NOT NULL DEFAULT '',
    char_conditions   TEXT NOT NULL DEFAULT '{}',
    world_conditions  TEXT NOT NULL DEFAULT '{}',
    quest_conditions  TEXT NOT NULL DEFAULT '{}',
    behavior          TEXT,
    effects           TEXT NOT NULL DEFAULT '{}',
    sort_order        INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS tile_templates (
    key            TEXT PRIMARY KEY,
    name           TEXT NOT NULL DEFAULT '',
    walkable       INTEGER NOT NULL DEFAULT 1,
    covered        INTEGER NOT NULL DEFAULT 0,
    sprite_name    TEXT REFERENCES sprites(name),
    tile_scale     REAL NOT NULL DEFAULT 1.0,
    animation_name TEXT REFERENCES animations(name),
    stat_mods      TEXT,
    speed_modifier REAL NOT NULL DEFAULT 1.0,
    bg_color       TEXT
);
CREATE TABLE IF NOT EXISTS tile_sets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tile_set      TEXT NOT NULL,
    x             INTEGER NOT NULL,
    y             INTEGER NOT NULL,
    z             INTEGER NOT NULL DEFAULT 0,
    tile_template TEXT REFERENCES tile_templates(key),
    walkable      INTEGER,
    covered       INTEGER,
    sprite_name   TEXT REFERENCES sprites(name),
    tile_scale    REAL,
    bounds_n      TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w  TEXT,
    bounds_ne     TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT,
    nested_map    TEXT REFERENCES maps(name),
    linked_map    TEXT REFERENCES maps(name),
    linked_x      INTEGER,
    linked_y      INTEGER,
    linked_z      INTEGER,
    link_auto     INTEGER NOT NULL DEFAULT 0,
    stat_mods      TEXT,
    animation_name TEXT,
    search_text    TEXT,
    speed_modifier REAL,
    bg_color       TEXT
);
CREATE VIEW IF NOT EXISTS tile_set_names AS
    SELECT DISTINCT tile_set AS name FROM tile_sets ORDER BY tile_set;
CREATE TABLE IF NOT EXISTS maps (
    name         TEXT PRIMARY KEY,
    tile_set     TEXT,
    default_tile_template TEXT REFERENCES tile_templates(key),
    entrance_x   INTEGER NOT NULL DEFAULT 0,
    entrance_y   INTEGER NOT NULL DEFAULT 0,
    x_min INTEGER NOT NULL DEFAULT 0,  x_max INTEGER NOT NULL DEFAULT 0,
    y_min INTEGER NOT NULL DEFAULT 0,  y_max INTEGER NOT NULL DEFAULT 0,
    z_min INTEGER NOT NULL DEFAULT 0,  z_max INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nn_models (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    version          INTEGER NOT NULL,
    parent_version   INTEGER,
    weights          BLOB NOT NULL,
    observation_size INTEGER NOT NULL,
    num_actions      INTEGER NOT NULL,
    training_params  TEXT NOT NULL DEFAULT '{}',
    training_stats   TEXT NOT NULL DEFAULT '{}',
    training_seconds REAL NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    UNIQUE(name, version)
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
