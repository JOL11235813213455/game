import sqlite3
import json
from pathlib import Path

from classes.stats import Stat
from classes.inventory import (
    Item, Stackable, Consumable, Ammunition,
    Equippable, Weapon, Wearable, Structure, Slot, CLASS_MAP
)

_DB_PATH = Path(__file__).parent / 'game.db'
_loaded  = False

SPECIES:     dict[str, dict] = {}
PLAYABLE:    dict[str, dict] = {}
NONPLAYABLE: dict[str, dict] = {}
CREATURES:   dict[str, dict] = {}
DIALOGUE:    dict[int, dict] = {}      # id → dialogue node dict
DIALOGUE_ROOTS: dict[str, list] = {}   # conversation → [root node ids]
SPELLS:      dict[str, dict] = {}      # key → spell definition dict
SPELL_LISTS: dict[str, list] = {}      # creature_key or species_name → [spell_keys]
QUESTS:      dict[str, dict] = {}      # quest_name → quest definition
QUEST_STEPS: dict[str, list] = {}      # quest_name → [step dicts]
GODS:        dict[str, dict] = {}      # god_name → god definition
ITEMS:       dict[str, Item] = {}
SPRITE_DATA: dict[str, dict] = {}
TILE_TEMPLATES: dict[str, dict] = {}
MAPS:  dict[str, object] = {}
MAP_GRAPH = None  # MapGraph instance, built after maps are loaded
ITEM_FRAMES: dict[str, dict] = {}  # frame_key → {recipe, output_item_key, auto_pop, ...}
JOBS:         dict[str, object] = {}  # job_key → Job instance (classes.jobs.Job)
PROCESSING_RECIPES: list = []          # list of classes.recipes.Recipe
SCHEDULES:    dict[str, object] = {}  # schedule_key → classes.jobs.Schedule
STRUCTURES: dict[str, 'Structure'] = {}  # key → Structure instance (templates from DB)
ANIMATIONS: dict[str, dict] = {}    # name → {target_type, frames: [{sprite_name, duration_ms}]}
ANIM_BINDINGS: dict[tuple, str] = {}  # (target_name, behavior) → animation_name
COMPOSITES: dict[str, dict] = {}    # name → {root_layer, layers, connections, variants, animations}
COMPOSITE_ANIMS: dict[str, dict] = {}  # name → {composite_name, loop, duration_ms, keyframes}
COMPOSITE_ANIM_BINDINGS: dict[tuple, dict] = {}  # (target_name, behavior) → {animation_name, flip_h}


def _migrate(con: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema creation."""
    for stmt in [
        "ALTER TABLE sprites ADD COLUMN width  INTEGER NOT NULL DEFAULT 8",
        "ALTER TABLE sprites ADD COLUMN height INTEGER NOT NULL DEFAULT 8",
        "ALTER TABLE sprites ADD COLUMN action_point_x INTEGER",
        "ALTER TABLE sprites ADD COLUMN action_point_y INTEGER",
        "ALTER TABLE items   ADD COLUMN tile_scale REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE species ADD COLUMN tile_scale REAL NOT NULL DEFAULT 1.0",
        """CREATE TABLE IF NOT EXISTS tile_templates (
    key TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
    walkable INTEGER NOT NULL DEFAULT 1, covered INTEGER NOT NULL DEFAULT 0,
    sprite_name TEXT, tile_scale REAL NOT NULL DEFAULT 1.0,
    bounds_n TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w TEXT,
    bounds_ne TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT)""",
        """CREATE TABLE IF NOT EXISTS tile_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tile_set TEXT NOT NULL,
    x INTEGER NOT NULL, y INTEGER NOT NULL, z INTEGER NOT NULL DEFAULT 0,
    tile_template TEXT, walkable INTEGER, covered INTEGER,
    sprite_name TEXT, tile_scale REAL,
    bounds_n TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w TEXT,
    bounds_ne TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT,
    nested_map TEXT)""",
        """CREATE TABLE IF NOT EXISTS maps (
    name TEXT PRIMARY KEY, tile_set TEXT, default_tile_template TEXT,
    entrance_x INTEGER NOT NULL DEFAULT 0, entrance_y INTEGER NOT NULL DEFAULT 0,
    x_min INTEGER NOT NULL DEFAULT 0, x_max INTEGER NOT NULL DEFAULT 0,
    y_min INTEGER NOT NULL DEFAULT 0, y_max INTEGER NOT NULL DEFAULT 0,
    z_min INTEGER NOT NULL DEFAULT 0, z_max INTEGER NOT NULL DEFAULT 0)""",
        "ALTER TABLE maps ADD COLUMN tile_set TEXT",
        "ALTER TABLE tile_templates ADD COLUMN animation_name TEXT",
        "ALTER TABLE items ADD COLUMN collision INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE items ADD COLUMN footprint TEXT",
        "ALTER TABLE items ADD COLUMN collision_mask TEXT",
        "ALTER TABLE items ADD COLUMN entry_points TEXT",
        "ALTER TABLE items ADD COLUMN nested_map TEXT",
        "ALTER TABLE species ADD COLUMN composite_name TEXT",
        "ALTER TABLE sprites ADD COLUMN sprite_set TEXT",
        "ALTER TABLE species ADD COLUMN size TEXT NOT NULL DEFAULT 'medium'",
        "ALTER TABLE species ADD COLUMN description TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE species ADD COLUMN base_move_speed REAL NOT NULL DEFAULT 4.0",
        "ALTER TABLE species ADD COLUMN lifespan INTEGER NOT NULL DEFAULT 365",
        "ALTER TABLE species ADD COLUMN maturity_age INTEGER NOT NULL DEFAULT 18",
        "ALTER TABLE species ADD COLUMN young_max INTEGER NOT NULL DEFAULT 30",
        "ALTER TABLE species ADD COLUMN fecundity_peak INTEGER NOT NULL DEFAULT 100",
        "ALTER TABLE species ADD COLUMN fecundity_end INTEGER NOT NULL DEFAULT 300",
        "ALTER TABLE species ADD COLUMN aggression REAL NOT NULL DEFAULT 0.3",
        "ALTER TABLE species ADD COLUMN sociability REAL NOT NULL DEFAULT 0.5",
        "ALTER TABLE species ADD COLUMN territoriality REAL NOT NULL DEFAULT 0.3",
        "ALTER TABLE species ADD COLUMN curiosity_modifier REAL NOT NULL DEFAULT 0.0",
        "ALTER TABLE species ADD COLUMN preferred_deity TEXT",
        "ALTER TABLE creatures ADD COLUMN title TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE creatures ADD COLUMN deity TEXT",
        "ALTER TABLE creatures ADD COLUMN piety REAL",
        "ALTER TABLE creatures ADD COLUMN gold INTEGER",
        "ALTER TABLE creatures ADD COLUMN observation_mask TEXT",
        "ALTER TABLE creatures ADD COLUMN is_unique INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE creatures ADD COLUMN spawn_map TEXT",
        "ALTER TABLE creatures ADD COLUMN spawn_x INTEGER",
        "ALTER TABLE creatures ADD COLUMN spawn_y INTEGER",
        "ALTER TABLE creatures ADD COLUMN dialogue_tree TEXT",
        "ALTER TABLE creatures ADD COLUMN description TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE species ADD COLUMN sprite_name_f TEXT",
        "ALTER TABLE species ADD COLUMN composite_name_f TEXT",
        "ALTER TABLE species ADD COLUMN egg_sprite TEXT",
        "ALTER TABLE creatures ADD COLUMN cumulative_limit INTEGER NOT NULL DEFAULT -1",
        "ALTER TABLE creatures ADD COLUMN concurrent_limit INTEGER NOT NULL DEFAULT -1",
        "ALTER TABLE items ADD COLUMN action_word TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE items ADD COLUMN requirements TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE items ADD COLUMN hit_dice INTEGER",
        "ALTER TABLE items ADD COLUMN hit_dice_count INTEGER",
        "ALTER TABLE items ADD COLUMN crit_chance_mod INTEGER",
        "ALTER TABLE items ADD COLUMN crit_damage_mod REAL",
        "ALTER TABLE items ADD COLUMN stagger_dc INTEGER",
        "ALTER TABLE items ADD COLUMN stamina_cost INTEGER",
        "ALTER TABLE items ADD COLUMN status_effect TEXT",
        "ALTER TABLE items ADD COLUMN status_dc INTEGER",
        "ALTER TABLE items ADD COLUMN heal_amount INTEGER",
        "ALTER TABLE items ADD COLUMN mana_restore INTEGER",
        "ALTER TABLE items ADD COLUMN stamina_restore INTEGER",
        "ALTER TABLE items ADD COLUMN recoverable INTEGER",
        "ALTER TABLE species ADD COLUMN sex TEXT",
        "ALTER TABLE species ADD COLUMN prudishness REAL",
        """CREATE TABLE IF NOT EXISTS creatures (
    key TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
    species TEXT NOT NULL REFERENCES species(name),
    level INTEGER, sex TEXT, age INTEGER, prudishness REAL,
    behavior TEXT, items TEXT NOT NULL DEFAULT '[]')""",
        """CREATE TABLE IF NOT EXISTS creature_stats (
    creature_key TEXT NOT NULL REFERENCES creatures(key),
    stat TEXT NOT NULL, value INTEGER NOT NULL,
    PRIMARY KEY (creature_key, stat))""",
        """CREATE TABLE IF NOT EXISTS dialogue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation TEXT NOT NULL, species TEXT, creature_key TEXT,
    parent_id INTEGER REFERENCES dialogue(id),
    speaker TEXT NOT NULL DEFAULT 'npc',
    text TEXT NOT NULL DEFAULT '',
    char_conditions TEXT NOT NULL DEFAULT '{}',
    world_conditions TEXT NOT NULL DEFAULT '{}',
    quest_conditions TEXT NOT NULL DEFAULT '{}',
    behavior TEXT, effects TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS spells (
    key TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '', action_word TEXT NOT NULL DEFAULT 'cast',
    damage REAL NOT NULL DEFAULT 0, mana_cost INTEGER NOT NULL DEFAULT 0,
    stamina_cost INTEGER NOT NULL DEFAULT 0, range INTEGER NOT NULL DEFAULT 5,
    radius INTEGER NOT NULL DEFAULT 0, spell_dc INTEGER NOT NULL DEFAULT 10,
    dodgeable INTEGER NOT NULL DEFAULT 1, target_type TEXT NOT NULL DEFAULT 'single',
    effect_type TEXT NOT NULL DEFAULT 'damage', buffs TEXT NOT NULL DEFAULT '{}',
    duration REAL NOT NULL DEFAULT 0, secondary_resist TEXT, secondary_dc INTEGER,
    requirements TEXT NOT NULL DEFAULT '{}', sprite_name TEXT, animation_name TEXT,
    composite_name TEXT)""",
        """CREATE TABLE IF NOT EXISTS creature_spells (
    creature_key TEXT NOT NULL, spell_key TEXT NOT NULL REFERENCES spells(key),
    PRIMARY KEY (creature_key, spell_key))""",
        """CREATE TABLE IF NOT EXISTS species_spells (
    species_name TEXT NOT NULL REFERENCES species(name),
    spell_key TEXT NOT NULL REFERENCES spells(key),
    PRIMARY KEY (species_name, spell_key))""",
        """CREATE TABLE IF NOT EXISTS quests (
    name TEXT PRIMARY KEY, giver TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', quest_type TEXT NOT NULL DEFAULT 'quest',
    conditions TEXT NOT NULL DEFAULT '{}', reward_action TEXT NOT NULL DEFAULT '',
    fail_action TEXT NOT NULL DEFAULT '', time_limit INTEGER,
    repeatable INTEGER NOT NULL DEFAULT 0, cooldown_days INTEGER)""",
        """CREATE TABLE IF NOT EXISTS quest_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_name TEXT NOT NULL REFERENCES quests(name),
    step_no INTEGER NOT NULL, step_sub TEXT NOT NULL DEFAULT 'a',
    description TEXT NOT NULL DEFAULT '',
    success_condition TEXT NOT NULL DEFAULT '', fail_condition TEXT NOT NULL DEFAULT '',
    success_action TEXT NOT NULL DEFAULT '', fail_action TEXT NOT NULL DEFAULT '',
    step_map TEXT, step_location_x INTEGER, step_location_y INTEGER,
    step_npc TEXT, time_limit INTEGER,
    UNIQUE(quest_name, step_no, step_sub))""",
        """CREATE TABLE IF NOT EXISTS gods (
    name TEXT PRIMARY KEY, domain TEXT NOT NULL DEFAULT '',
    opposed_god TEXT, aligned_actions TEXT NOT NULL DEFAULT '[]',
    opposed_actions TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS nn_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, version INTEGER NOT NULL,
    parent_version INTEGER, weights BLOB NOT NULL,
    observation_size INTEGER NOT NULL, num_actions INTEGER NOT NULL,
    training_params TEXT NOT NULL DEFAULT '{}',
    training_stats TEXT NOT NULL DEFAULT '{}',
    training_seconds REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(name, version))""",
        "ALTER TABLE species ADD COLUMN sentient INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE species ADD COLUMN model_name TEXT",
        "ALTER TABLE species ADD COLUMN model_version INTEGER",
        "ALTER TABLE creatures ADD COLUMN model_name TEXT",
        "ALTER TABLE creatures ADD COLUMN model_version INTEGER",
        "ALTER TABLE nn_models ADD COLUMN obs_schema_id INTEGER",
        "ALTER TABLE nn_models ADD COLUMN act_schema_id INTEGER",
        "ALTER TABLE nn_models ADD COLUMN goal_weights BLOB",
        "ALTER TABLE nn_models ADD COLUMN goal_obs_size INTEGER",
        "ALTER TABLE nn_models ADD COLUMN num_purposes INTEGER",
        "ALTER TABLE tile_templates ADD COLUMN liquid INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tile_templates ADD COLUMN flow_direction TEXT",
        "ALTER TABLE tile_templates ADD COLUMN flow_speed REAL NOT NULL DEFAULT 0.0",
        "ALTER TABLE tile_templates ADD COLUMN depth INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tile_sets ADD COLUMN liquid INTEGER",
        "ALTER TABLE tile_sets ADD COLUMN flow_direction TEXT",
        "ALTER TABLE tile_sets ADD COLUMN flow_speed REAL",
        "ALTER TABLE tile_sets ADD COLUMN depth INTEGER",
        "ALTER TABLE tile_templates ADD COLUMN purpose TEXT",
        "ALTER TABLE tile_sets ADD COLUMN purpose TEXT",
        "ALTER TABLE tile_templates ADD COLUMN resource_type TEXT",
        "ALTER TABLE tile_templates ADD COLUMN resource_amount INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tile_templates ADD COLUMN resource_max INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tile_templates ADD COLUMN growth_rate REAL NOT NULL DEFAULT 0.0",
        "ALTER TABLE tile_sets ADD COLUMN resource_type TEXT",
        "ALTER TABLE tile_sets ADD COLUMN resource_amount INTEGER",
        "ALTER TABLE tile_sets ADD COLUMN resource_max INTEGER",
        "ALTER TABLE tile_sets ADD COLUMN growth_rate REAL",
        # Items: food flag + kpi_metric (for valuation specificity)
        "ALTER TABLE items ADD COLUMN is_food INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE items ADD COLUMN kpi_metric TEXT",
        # Jobs / schedules / recipes — the economy catalog
        """CREATE TABLE IF NOT EXISTS schedules (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    sleep_bands TEXT NOT NULL DEFAULT '[]',
    work_bands TEXT NOT NULL DEFAULT '[]',
    open_bands TEXT NOT NULL DEFAULT '[]')""",
        """CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL,
    wage_per_tick REAL NOT NULL DEFAULT 1.0,
    required_stat TEXT NOT NULL DEFAULT 'STR',
    required_level INTEGER NOT NULL DEFAULT 8,
    workplace_purposes TEXT NOT NULL DEFAULT '[]',
    schedule_template TEXT NOT NULL DEFAULT 'day_worker')""",
        """CREATE TABLE IF NOT EXISTS processing_recipes (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    output_item_key TEXT NOT NULL REFERENCES items(key),
    output_quantity INTEGER NOT NULL DEFAULT 1,
    category TEXT NOT NULL DEFAULT 'food',
    required_tile_purpose TEXT NOT NULL DEFAULT 'crafting',
    stamina_cost INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS processing_recipe_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_key TEXT NOT NULL REFERENCES processing_recipes(key),
    ingredient_item_key TEXT NOT NULL REFERENCES items(key),
    quantity INTEGER NOT NULL DEFAULT 1,
    UNIQUE(recipe_key, ingredient_item_key))""",
        "ALTER TABLE creatures ADD COLUMN job_key TEXT REFERENCES jobs(key)",
        # Curriculum stages — RL training plan
        """CREATE TABLE IF NOT EXISTS curriculum_stages (
    stage_number       INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    active_signals     TEXT NOT NULL DEFAULT '[]',
    signal_scales      TEXT NOT NULL DEFAULT '{}',
    hunger_drain       INTEGER NOT NULL DEFAULT 1,
    combat_enabled     INTEGER NOT NULL DEFAULT 1,
    gestation_enabled  INTEGER NOT NULL DEFAULT 1,
    fatigue_enabled    INTEGER NOT NULL DEFAULT 1,
    allowed_actions    TEXT NOT NULL DEFAULT '[]',
    mappo_steps        INTEGER NOT NULL DEFAULT 50000,
    es_generations     INTEGER NOT NULL DEFAULT 0,
    es_variants        INTEGER NOT NULL DEFAULT 20,
    es_steps           INTEGER NOT NULL DEFAULT 1000,
    ppo_steps          INTEGER NOT NULL DEFAULT 50000,
    learning_rate      REAL NOT NULL DEFAULT 0.0003,
    ent_coef           REAL NOT NULL DEFAULT 0.05,
    resume_from_stage  INTEGER)""",
        "ALTER TABLE curriculum_stages ADD COLUMN fatigue_enabled INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE curriculum_stages ADD COLUMN allowed_actions TEXT NOT NULL DEFAULT '[]'",
        """CREATE TABLE IF NOT EXISTS item_frames (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    output_item_key TEXT NOT NULL REFERENCES items(key),
    auto_pop INTEGER NOT NULL DEFAULT 0,
    composite_name TEXT)""",
        """CREATE TABLE IF NOT EXISTS item_frame_recipe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_key TEXT NOT NULL REFERENCES item_frames(key),
    ingredient_key TEXT NOT NULL REFERENCES items(key),
    quantity INTEGER NOT NULL DEFAULT 1,
    UNIQUE(frame_key, ingredient_key))""",
        "ALTER TABLE items ADD COLUMN item_frame TEXT REFERENCES item_frames(key)",
        "ALTER TABLE items ADD COLUMN disassemblable INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE items ADD COLUMN crafter_uid INTEGER",
        """CREATE TABLE IF NOT EXISTS purpose_places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map_name TEXT NOT NULL REFERENCES maps(name),
    purpose TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    x_min INTEGER NOT NULL,
    y_min INTEGER NOT NULL,
    z_min INTEGER NOT NULL DEFAULT 0,
    x_max INTEGER NOT NULL,
    y_max INTEGER NOT NULL,
    z_max INTEGER NOT NULL DEFAULT 0)""",
    ]:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column/table already exists

    # Migrate old tile_sets table (has map_name column) → tile_entries → tile_sets
    try:
        con.execute("SELECT map_name FROM tile_sets LIMIT 1")
    except sqlite3.OperationalError:
        pass  # already new schema or table doesn't exist
    else:
        # Very old schema with map_name column
        con.execute("ALTER TABLE tile_sets RENAME TO _old_tile_sets")
        con.execute("""CREATE TABLE tile_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tile_set TEXT NOT NULL, w INTEGER NOT NULL DEFAULT 0,
            x INTEGER NOT NULL, y INTEGER NOT NULL, z INTEGER NOT NULL DEFAULT 0,
            tile_template TEXT, walkable INTEGER, covered INTEGER,
            sprite_name TEXT, tile_scale REAL,
            bounds_n TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w TEXT,
            bounds_ne TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT,
            nested_map TEXT)""")
        con.execute("""INSERT OR IGNORE INTO tile_sets
            (tile_set, w, x, y, z, tile_template, walkable, covered,
             sprite_name, tile_scale, bounds_n, bounds_s, bounds_e, bounds_w,
             bounds_ne, bounds_nw, bounds_se, bounds_sw, nested_map)
            SELECT map_name, w, x, y, z, tile_template, walkable, covered,
             sprite_name, tile_scale, bounds_n, bounds_s, bounds_e, bounds_w,
             bounds_ne, bounds_nw, bounds_se, bounds_sw, nested_map
            FROM _old_tile_sets""")
        con.execute("UPDATE maps SET tile_set = name WHERE tile_set IS NULL")
        con.execute("DROP TABLE _old_tile_sets")

    # Migrate tile_entries into tile_sets (consolidation)
    try:
        con.execute("SELECT id FROM tile_entries LIMIT 1")
    except sqlite3.OperationalError:
        pass  # tile_entries doesn't exist — already migrated or fresh DB
    else:
        # tile_entries exists alongside a names-only tile_sets — consolidate
        con.execute("DROP TABLE IF EXISTS tile_sets")
        con.execute("ALTER TABLE tile_entries RENAME TO tile_sets")

    # Create convenience view for distinct tile set names
    con.execute("CREATE VIEW IF NOT EXISTS tile_set_names AS "
                "SELECT DISTINCT tile_set AS name FROM tile_sets ORDER BY tile_set")

    # Migrate tiles → tile_templates
    try:
        con.execute("SELECT key FROM tiles LIMIT 1")
    except sqlite3.OperationalError:
        pass  # old table doesn't exist
    else:
        con.execute("""INSERT OR IGNORE INTO tile_templates
            (key, name, walkable, covered, sprite_name, tile_scale,
             bounds_n, bounds_s, bounds_e, bounds_w,
             bounds_ne, bounds_nw, bounds_se, bounds_sw)
            SELECT key, name, walkable, covered, sprite_name, tile_scale,
             bounds_n, bounds_s, bounds_e, bounds_w,
             bounds_ne, bounds_nw, bounds_se, bounds_sw
            FROM tiles""")
        try:
            for r in con.execute("SELECT key, animation_name FROM tiles WHERE animation_name IS NOT NULL").fetchall():
                con.execute("UPDATE tile_templates SET animation_name=? WHERE key=?",
                            (r['animation_name'], r['key']))
        except sqlite3.OperationalError:
            pass
        con.execute("DROP TABLE tiles")

    # Rename maps.default_tile → maps.default_tile_template
    try:
        con.execute("SELECT default_tile FROM maps LIMIT 1")
    except sqlite3.OperationalError:
        pass  # already renamed or fresh DB
    else:
        con.execute("ALTER TABLE maps RENAME COLUMN default_tile TO default_tile_template")

    # Drop vestigial W columns
    for stmt in [
        "ALTER TABLE maps DROP COLUMN w_min",
        "ALTER TABLE maps DROP COLUMN w_max",
        "ALTER TABLE tile_sets DROP COLUMN w",
    ]:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass  # already dropped

    # Rename warp_* → linked_*
    for old, new in [('warp_map', 'linked_map'), ('warp_x', 'linked_x'),
                      ('warp_y', 'linked_y'), ('warp_auto', 'link_auto')]:
        try:
            con.execute(f'ALTER TABLE tile_sets RENAME COLUMN {old} TO {new}')
        except sqlite3.OperationalError:
            pass

    # Animation tables
    for stmt in [
        """CREATE TABLE IF NOT EXISTS animations (
            name TEXT PRIMARY KEY, target_type TEXT NOT NULL DEFAULT 'creature')""",
        """CREATE TABLE IF NOT EXISTS animation_frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            animation_name TEXT NOT NULL REFERENCES animations(name),
            frame_index INTEGER NOT NULL,
            sprite_name TEXT NOT NULL REFERENCES sprites(name),
            duration_ms INTEGER NOT NULL DEFAULT 150,
            UNIQUE(animation_name, frame_index))""",
        """CREATE TABLE IF NOT EXISTS animation_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_name TEXT NOT NULL,
            behavior TEXT NOT NULL DEFAULT 'idle',
            animation_name TEXT NOT NULL REFERENCES animations(name),
            UNIQUE(target_name, behavior))""",
    ]:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Composite sprite tables
    for stmt in [
        """CREATE TABLE IF NOT EXISTS composite_sprites (
            name TEXT PRIMARY KEY,
            root_layer TEXT NOT NULL DEFAULT 'root')""",
        """CREATE TABLE IF NOT EXISTS composite_layers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            composite_name TEXT NOT NULL REFERENCES composite_sprites(name),
            layer_name TEXT NOT NULL,
            z_layer INTEGER NOT NULL DEFAULT 0,
            default_sprite TEXT REFERENCES sprites(name),
            UNIQUE(composite_name, layer_name))""",
        """CREATE TABLE IF NOT EXISTS layer_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            composite_name TEXT NOT NULL REFERENCES composite_sprites(name),
            layer_name TEXT NOT NULL,
            variant_name TEXT NOT NULL,
            sprite_name TEXT NOT NULL REFERENCES sprites(name),
            UNIQUE(composite_name, layer_name, variant_name))""",
        """CREATE TABLE IF NOT EXISTS layer_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            composite_name TEXT NOT NULL REFERENCES composite_sprites(name),
            parent_layer TEXT NOT NULL,
            child_layer TEXT NOT NULL,
            parent_socket_x INTEGER NOT NULL DEFAULT 0,
            parent_socket_y INTEGER NOT NULL DEFAULT 0,
            child_anchor_x INTEGER NOT NULL DEFAULT 0,
            child_anchor_y INTEGER NOT NULL DEFAULT 0,
            UNIQUE(composite_name, child_layer))""",
        """CREATE TABLE IF NOT EXISTS composite_animations (
            name TEXT PRIMARY KEY,
            composite_name TEXT NOT NULL REFERENCES composite_sprites(name),
            loop INTEGER NOT NULL DEFAULT 1,
            duration_ms INTEGER NOT NULL DEFAULT 1000)""",
        """CREATE TABLE IF NOT EXISTS composite_anim_keyframes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            animation_name TEXT NOT NULL REFERENCES composite_animations(name),
            layer_name TEXT NOT NULL,
            time_ms INTEGER NOT NULL DEFAULT 0,
            offset_x INTEGER NOT NULL DEFAULT 0,
            offset_y INTEGER NOT NULL DEFAULT 0,
            rotation_deg REAL NOT NULL DEFAULT 0.0,
            variant_name TEXT,
            UNIQUE(animation_name, layer_name, time_ms))""",
        "ALTER TABLE composite_animations ADD COLUMN time_scale REAL NOT NULL DEFAULT 1.0",
        """CREATE TABLE IF NOT EXISTS composite_anim_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_name TEXT NOT NULL,
            behavior TEXT NOT NULL,
            animation_name TEXT NOT NULL
                REFERENCES composite_animations(name),
            flip_h INTEGER NOT NULL DEFAULT 0,
            UNIQUE(target_name, behavior))""",
        "ALTER TABLE composite_anim_keyframes ADD COLUMN tint_r INTEGER",
        "ALTER TABLE composite_anim_keyframes ADD COLUMN tint_g INTEGER",
        "ALTER TABLE composite_anim_keyframes ADD COLUMN tint_b INTEGER",
        "ALTER TABLE composite_anim_keyframes ADD COLUMN opacity REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE composite_anim_keyframes ADD COLUMN scale REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE tile_sets ADD COLUMN animation_name TEXT",
        "ALTER TABLE tile_sets ADD COLUMN linked_map TEXT",
        "ALTER TABLE tile_sets ADD COLUMN linked_x INTEGER",
        "ALTER TABLE tile_sets ADD COLUMN linked_y INTEGER",
        "ALTER TABLE tile_sets ADD COLUMN linked_z INTEGER",
        "ALTER TABLE tile_sets ADD COLUMN link_auto INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tile_sets ADD COLUMN stat_mods TEXT",
        "ALTER TABLE tile_templates ADD COLUMN stat_mods TEXT",
        "ALTER TABLE tile_templates ADD COLUMN speed_modifier REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE tile_sets ADD COLUMN search_text TEXT",
        "ALTER TABLE tile_sets ADD COLUMN speed_modifier REAL",
        "ALTER TABLE tile_templates ADD COLUMN bg_color TEXT",
        "ALTER TABLE tile_sets ADD COLUMN bg_color TEXT",
    ]:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Rename CON (constitution) → VIT (vitality) in species_stats
    con.execute("UPDATE species_stats SET stat='vitality' WHERE stat='constitution'")

    con.commit()


def load(db_path: Path = _DB_PATH) -> None:
    global _loaded
    if _loaded:
        return
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        _migrate(con)
        _load_species(con)
        # Schedules and jobs load BEFORE creatures so creature rows can
        # resolve their job_key into a live Job instance at load time.
        _load_schedules(con)
        _load_jobs(con)
        _load_creatures(con)
        _load_dialogue(con)
        _load_spells(con)
        _load_quests(con)
        _load_gods(con)
        _load_items(con)
        _load_sprites(con)
        _load_tile_templates(con)
        _load_maps(con)
        _load_animations(con)
        _load_composites(con)
        _load_item_frames(con)
        # Recipes load last because their output_factory closures clone
        # items from the ITEMS catalog.
        _load_processing_recipes(con)
    finally:
        con.close()

    # Build map connectivity graph after all maps are loaded
    global MAP_GRAPH
    try:
        from classes.map_graph import MapGraph
        MAP_GRAPH = MapGraph()
        MAP_GRAPH.build_from_maps(MAPS)
    except Exception:
        MAP_GRAPH = None

    _loaded = True


def _load_species(con: sqlite3.Connection) -> None:
    rows      = con.execute('SELECT * FROM species').fetchall()
    stat_rows = con.execute('SELECT species_name, stat, value FROM species_stats').fetchall()

    stats_by_species: dict[str, dict] = {r['name']: {} for r in rows}
    for r in stat_rows:
        stats_by_species[r['species_name']][Stat(r['stat'])] = r['value']

    for r in rows:
        name  = r['name']
        block = stats_by_species[name]
        if r['sprite_name'] is not None:
            block['sprite_name'] = r['sprite_name']
        if r['sprite_name_f'] is not None:
            block['sprite_name_f'] = r['sprite_name_f']
        if r['composite_name'] is not None:
            block['composite_name'] = r['composite_name']
        if r['composite_name_f'] is not None:
            block['composite_name_f'] = r['composite_name_f']
        block['tile_scale'] = r['tile_scale'] if r['tile_scale'] is not None else 1.0
        if r['prudishness'] is not None:
            block['prudishness'] = r['prudishness']
        block['size'] = r['size'] or 'medium'
        if r['egg_sprite'] is not None:
            block['egg_sprite'] = r['egg_sprite']
        SPECIES[name] = block
        if r['playable']:
            PLAYABLE[name] = block
        else:
            NONPLAYABLE[name] = block


def _load_creatures(con: sqlite3.Connection) -> None:
    rows      = con.execute('SELECT * FROM creatures').fetchall()
    stat_rows = con.execute('SELECT creature_key, stat, value FROM creature_stats').fetchall()

    stats_by_key: dict[str, dict] = {r['key']: {} for r in rows}
    for r in stat_rows:
        stats_by_key[r['creature_key']][Stat(r['stat'])] = r['value']

    for r in rows:
        key = r['key']
        block = {
            'name':     r['name'],
            'species':  r['species'],
            'stats':    stats_by_key.get(key, {}),
            'items':    json.loads(r['items'] or '[]'),
        }
        if r['level'] is not None:
            block['level'] = r['level']
        if r['sex'] is not None:
            block['sex'] = r['sex']
        if r['age'] is not None:
            block['age'] = r['age']
        if r['prudishness'] is not None:
            block['prudishness'] = r['prudishness']
        if r['behavior'] is not None:
            block['behavior'] = r['behavior']
        # Spawn hints — used by the game runtime (main.py) to place
        # seeded NPCs at fixed positions when a map loads.
        for field in ('spawn_map', 'spawn_x', 'spawn_y', 'dialogue_tree',
                       'deity', 'gold', 'description', 'title'):
            try:
                val = r[field]
            except (KeyError, IndexError):
                val = None
            if val is not None:
                block[field] = val
        # Resolve job from the DB reference — JOBS was populated earlier
        # in the load sequence. Unknown or missing job_key → wanderer.
        try:
            job_key = r['job_key']
        except (KeyError, IndexError):
            job_key = None
        block['job_key'] = job_key
        if job_key and job_key in JOBS:
            block['job'] = JOBS[job_key]
        CREATURES[key] = block


def _load_dialogue(con: sqlite3.Connection) -> None:
    rows = con.execute(
        'SELECT * FROM dialogue ORDER BY conversation, parent_id, sort_order'
    ).fetchall()

    for r in rows:
        node = {
            'id':               r['id'],
            'conversation':     r['conversation'],
            'species':          r['species'],
            'creature_key':     r['creature_key'],
            'parent_id':        r['parent_id'],
            'speaker':          r['speaker'],
            'text':             r['text'],
            'char_conditions':  json.loads(r['char_conditions'] or '{}'),
            'world_conditions': json.loads(r['world_conditions'] or '{}'),
            'quest_conditions': json.loads(r['quest_conditions'] or '{}'),
            'behavior':         r['behavior'],
            'effects':          json.loads(r['effects'] or '{}'),
            'sort_order':       r['sort_order'],
            'children':         [],  # populated below
        }
        DIALOGUE[node['id']] = node

        if node['parent_id'] is None:
            DIALOGUE_ROOTS.setdefault(node['conversation'], []).append(node['id'])

    # Build children lists
    for node in DIALOGUE.values():
        pid = node['parent_id']
        if pid is not None and pid in DIALOGUE:
            DIALOGUE[pid]['children'].append(node['id'])


def _load_spells(con: sqlite3.Connection) -> None:
    rows = con.execute('SELECT * FROM spells').fetchall()
    for r in rows:
        key = r['key']
        SPELLS[key] = {
            'key':              key,
            'name':             r['name'],
            'description':      r['description'],
            'action_word':      r['action_word'],
            'damage':           r['damage'],
            'mana_cost':        r['mana_cost'],
            'stamina_cost':     r['stamina_cost'],
            'range':            r['range'],
            'radius':           r['radius'],
            'spell_dc':         r['spell_dc'],
            'dodgeable':        bool(r['dodgeable']),
            'target_type':      r['target_type'],   # self / single / area
            'effect_type':      r['effect_type'],   # damage / heal / buff / debuff
            'buffs':            _parse_buffs(r['buffs']),
            'duration':         r['duration'],
            'secondary_resist': r['secondary_resist'],
            'secondary_dc':     r['secondary_dc'],
            'requirements':     _parse_buffs(r['requirements']),
            'sprite_name':      r['sprite_name'],
            'animation_name':   r['animation_name'],
            'composite_name':   r['composite_name'],
        }

    # Load creature spell lists
    for r in con.execute('SELECT * FROM creature_spells').fetchall():
        SPELL_LISTS.setdefault(r['creature_key'], []).append(r['spell_key'])

    # Load species spell lists
    for r in con.execute('SELECT * FROM species_spells').fetchall():
        SPELL_LISTS.setdefault(r['species_name'], []).append(r['spell_key'])


def _load_quests(con: sqlite3.Connection) -> None:
    rows = con.execute('SELECT * FROM quests').fetchall()
    for r in rows:
        name = r['name']
        QUESTS[name] = {
            'name':          name,
            'giver':         r['giver'],
            'description':   r['description'],
            'quest_type':    r['quest_type'],
            'conditions':    r['conditions'],
            'reward_action': r['reward_action'],
            'fail_action':   r['fail_action'],
            'time_limit':    r['time_limit'],
            'repeatable':    bool(r['repeatable']),
            'cooldown_days': r['cooldown_days'],
        }

    step_rows = con.execute(
        'SELECT * FROM quest_steps ORDER BY quest_name, step_no, step_sub'
    ).fetchall()
    for r in step_rows:
        step = {
            'quest_name':        r['quest_name'],
            'step_no':           r['step_no'],
            'step_sub':          r['step_sub'],
            'description':       r['description'],
            'success_condition': r['success_condition'],
            'fail_condition':    r['fail_condition'],
            'success_action':    r['success_action'],
            'fail_action':       r['fail_action'],
            'step_map':          r['step_map'],
            'step_location_x':   r['step_location_x'],
            'step_location_y':   r['step_location_y'],
            'step_npc':          r['step_npc'],
            'time_limit':        r['time_limit'],
        }
        QUEST_STEPS.setdefault(r['quest_name'], []).append(step)


def _load_gods(con: sqlite3.Connection) -> None:
    rows = con.execute('SELECT * FROM gods').fetchall()
    for r in rows:
        GODS[r['name']] = {
            'name':            r['name'],
            'domain':          r['domain'],
            'opposed_god':     r['opposed_god'],
            'aligned_actions': json.loads(r['aligned_actions'] or '[]'),
            'opposed_actions': json.loads(r['opposed_actions'] or '[]'),
            'description':     r['description'],
        }


_STAT_BY_VALUE = {s.value: s for s in Stat}

def _parse_buffs(raw: str | None) -> dict[Stat, int]:
    """Convert JSON buffs string to {Stat: amount} dict."""
    if not raw:
        return {}
    data = json.loads(raw)
    result = {}
    for key, val in data.items():
        stat = _STAT_BY_VALUE.get(key)
        if stat is not None:
            result[stat] = val
    return result


def _load_items(con: sqlite3.Connection) -> None:
    rows      = con.execute('SELECT * FROM items').fetchall()
    slot_rows = con.execute('SELECT item_key, slot FROM item_slots').fetchall()

    slots_by_key: dict[str, list] = {}
    for r in slot_rows:
        slots_by_key.setdefault(r['item_key'], []).append(Slot(r['slot']))

    for r in rows:
        key   = r['key']
        cls   = CLASS_MAP.get(r['class'], Item)
        base  = dict(
            name        = r['name']
            ,description = r['description']
            ,weight      = r['weight']
            ,value       = r['value']
            ,inventoriable = bool(r['inventoriable'])
            ,buffs       = _parse_buffs(r['buffs'])
            ,action_word = r['action_word'] or ''
            ,requirements = _parse_buffs(r['requirements'])
        )
        if r['sprite_name'] is not None:
            base['sprite_name'] = r['sprite_name']

        if cls in (Stackable, Consumable, Ammunition):
            if r['max_stack_size'] is not None:
                base['max_stack_size'] = r['max_stack_size']
            if r['quantity'] is not None:
                base['quantity'] = r['quantity']

        if cls == Consumable:
            if r['duration'] is not None:
                base['duration'] = r['duration']
            if r['heal_amount'] is not None:
                base['heal_amount'] = r['heal_amount']
            if r['mana_restore'] is not None:
                base['mana_restore'] = r['mana_restore']
            if r['stamina_restore'] is not None:
                base['stamina_restore'] = r['stamina_restore']

        if cls == Ammunition:
            if r['damage'] is not None:
                base['damage'] = r['damage']
            if r['destroy_on_use_probability'] is not None:
                base['destroy_on_use_probability'] = r['destroy_on_use_probability']
            if r['recoverable'] is not None:
                base['recoverable'] = bool(r['recoverable'])
            if r['status_effect'] is not None:
                base['status_effect'] = r['status_effect']
            if r['status_dc'] is not None:
                base['status_dc'] = r['status_dc']

        if cls in (Equippable, Weapon, Wearable):
            base['slots']              = slots_by_key.get(key, [])
            base['slot_count']         = r['slot_count'] or 1
            base['durability_max']     = r['durability_max'] or 100
            base['durability_current'] = r['durability_current'] or r['durability_max'] or 100
            base['render_on_creature'] = bool(r['render_on_creature'] or 0)

        if cls == Weapon:
            if r['damage'] is not None:
                base['damage'] = r['damage']
            if r['attack_time_ms'] is not None:
                base['attack_time_ms'] = r['attack_time_ms']
            if r['directions'] is not None:
                base['directions'] = json.loads(r['directions'])
            if r['range'] is not None:
                base['range'] = r['range']
            if r['ammunition_type'] is not None:
                base['ammunition_type'] = r['ammunition_type']
            if r['hit_dice'] is not None:
                base['hit_dice'] = r['hit_dice']
            if r['hit_dice_count'] is not None:
                base['hit_dice_count'] = r['hit_dice_count']
            if r['crit_chance_mod'] is not None:
                base['crit_chance_mod'] = r['crit_chance_mod']
            if r['crit_damage_mod'] is not None:
                base['crit_damage_mod'] = r['crit_damage_mod']
            if r['stagger_dc'] is not None:
                base['stagger_dc'] = r['stagger_dc']
            if r['stamina_cost'] is not None:
                base['stamina_cost'] = r['stamina_cost']
            if r['status_effect'] is not None:
                base['status_effect'] = r['status_effect']
            if r['status_dc'] is not None:
                base['status_dc'] = r['status_dc']

        if cls == Structure:
            if r['footprint'] is not None:
                base['footprint'] = json.loads(r['footprint'])
            if r['collision_mask'] is not None:
                base['collision_mask'] = json.loads(r['collision_mask'])
            if r['entry_points'] is not None:
                base['entry_points'] = json.loads(r['entry_points'])
            if r['nested_map'] is not None:
                base['nested_map'] = r['nested_map']

        obj = cls(**base)
        if r['tile_scale'] is not None:
            obj.tile_scale = r['tile_scale']
        obj.collision = bool(r['collision'])
        # Food flag and KPI metric hint
        try:
            obj.is_food = bool(r['is_food'])
        except (KeyError, IndexError):
            obj.is_food = False
        try:
            if r['kpi_metric']:
                obj.kpi_metric = r['kpi_metric']
        except (KeyError, IndexError):
            pass
        obj.key = key                 # remember catalog key for lookups
        ITEMS[key] = obj
        if cls == Structure:
            STRUCTURES[key] = obj


def _load_tile_templates(con: sqlite3.Connection) -> None:
    for r in con.execute('SELECT * FROM tile_templates').fetchall():
        TILE_TEMPLATES[r['key']] = {
            'name':        r['name'],
            'walkable':    bool(r['walkable']),
            'covered':     bool(r['covered']),
            'sprite_name': r['sprite_name'],
            'tile_scale':  r['tile_scale'] if r['tile_scale'] is not None else 1.0,
            'animation_name': r['animation_name'],
            'stat_mods':   json.loads(r['stat_mods']) if r['stat_mods'] else {},
            'speed_modifier': r['speed_modifier'] if r['speed_modifier'] is not None else 1.0,
            'bg_color': r['bg_color'],
            'liquid': bool(r['liquid']) if r['liquid'] is not None else False,
            'flow_direction': r['flow_direction'],
            'flow_speed': r['flow_speed'] if r['flow_speed'] is not None else 0.0,
            'depth': r['depth'] if r['depth'] is not None else 0,
            'purpose': r['purpose'],
            'resource_type': r['resource_type'],
            'resource_amount': r['resource_amount'] if r['resource_amount'] is not None else 0,
            'resource_max': r['resource_max'] if r['resource_max'] is not None else 0,
            'growth_rate': r['growth_rate'] if r['growth_rate'] is not None else 0.0,
        }


def _load_maps(con: sqlite3.Connection) -> None:
    from classes.maps import Map, MapKey, Tile, Bounds

    map_rows = con.execute('SELECT * FROM maps').fetchall()
    te_rows  = con.execute('SELECT * FROM tile_sets ORDER BY tile_set').fetchall()

    # Index tile entries by tile_set name
    entries_by_ts: dict[str, list] = {}
    for r in te_rows:
        entries_by_ts.setdefault(r['tile_set'], []).append(r)

    # Pass 1 — create Map shells
    map_objs: dict[str, Map] = {}
    for r in map_rows:
        m = Map(
            tile_set  = {},
            entrance  = (r['entrance_x'], r['entrance_y']),
            name      = r['name'],
            default_tile_template = r['default_tile_template'],
            x_min=r['x_min'], x_max=r['x_max'],
            y_min=r['y_min'], y_max=r['y_max'],
            z_min=r['z_min'], z_max=r['z_max'],
        )
        map_objs[r['name']] = m
        MAPS[r['name']] = m

    # Pass 2 — populate tiles from each map's tile_set
    BOUND_ATTRS = ('n','s','e','w','ne','nw','se','sw')
    for r in map_rows:
        m = map_objs[r['name']]
        entries = entries_by_ts.get(r['tile_set'], []) if r['tile_set'] else []
        for te in entries:
            tmpl = TILE_TEMPLATES.get(te['tile_template']) if te['tile_template'] else {}
            has_bounds = any(te[f'bounds_{a}'] for a in BOUND_ATTRS)
            if has_bounds:
                b_kwargs = {a: not (te[f'bounds_{a}'] == 0) for a in BOUND_ATTRS}
                bounds = Bounds(**b_kwargs)
            else:
                bounds = None
            m.tiles[MapKey(te['x'], te['y'], te['z'])] = Tile(
                template       = tmpl,
                map            = map_objs.get(te['nested_map']),
                walkable       = bool(te['walkable']) if te['walkable'] is not None else None,
                covered        = bool(te['covered'])  if te['covered']  is not None else None,
                bounds         = bounds,
                tile_template  = te['tile_template'],
                sprite_name    = te['sprite_name'] or None,
                tile_scale     = float(te['tile_scale']) if te['tile_scale'] is not None else None,
                animation_name = te['animation_name'] or None,
                linked_map     = te['linked_map'] or None,
                linked_x       = te['linked_x'],
                linked_y       = te['linked_y'],
                linked_z       = te['linked_z'],
                link_auto      = bool(te['link_auto']) if te['link_auto'] is not None else False,
                stat_mods      = json.loads(te['stat_mods']) if te['stat_mods'] else None,
                speed_modifier = float(te['speed_modifier']) if te['speed_modifier'] is not None else None,
                bg_color       = te['bg_color'] or None,
                liquid         = bool(te['liquid']) if te['liquid'] is not None else None,
                flow_direction = te['flow_direction'] or None,
                flow_speed     = float(te['flow_speed']) if te['flow_speed'] is not None else None,
                depth          = int(te['depth']) if te['depth'] is not None else None,
                purpose        = te['purpose'] or None,
                resource_type  = te['resource_type'] or None,
                resource_amount= int(te['resource_amount']) if te['resource_amount'] is not None else 0,
                resource_max   = int(te['resource_max']) if te['resource_max'] is not None else 0,
                growth_rate    = float(te['growth_rate']) if te['growth_rate'] is not None else 0.0,
            )

    # Fill remaining coords with default tile
    for m in map_objs.values():
        tmpl = TILE_TEMPLATES.get(m.default_tile_template) if m.default_tile_template else None
        if tmpl is None:
            continue
        for x in range(m.x_min, m.x_max + 1):
            for y in range(m.y_min, m.y_max + 1):
                for z in range(m.z_min, m.z_max + 1):
                    key = MapKey(x, y, z)
                    if key not in m.tiles:
                        m.tiles[key] = Tile(
                            template      = tmpl,
                            tile_template = m.default_tile_template,
                        )


def _load_sprites(con: sqlite3.Connection) -> None:
    rows = con.execute(
        'SELECT name, palette, pixels, width, height, action_point_x, action_point_y FROM sprites'
    ).fetchall()
    for r in rows:
        palette_raw = json.loads(r['palette'])
        apx = r['action_point_x']
        apy = r['action_point_y']
        SPRITE_DATA[r['name']] = {
            'palette':      {char: tuple(rgb) for char, rgb in palette_raw.items()}
            ,'pixels':      json.loads(r['pixels'])
            ,'width':       r['width']
            ,'height':      r['height']
            ,'action_point': (apx, apy) if apx is not None and apy is not None else None
        }


def _load_item_frames(con: sqlite3.Connection) -> None:
    """Load item frame blueprints and their recipes."""
    global ITEM_FRAMES
    ITEM_FRAMES.clear()
    try:
        frames = con.execute('SELECT * FROM item_frames').fetchall()
    except Exception:
        return  # table may not exist yet

    for r in frames:
        recipe = {}
        for ing in con.execute(
                'SELECT ingredient_key, quantity FROM item_frame_recipe WHERE frame_key = ?',
                (r['key'],)).fetchall():
            recipe[ing['ingredient_key']] = ing['quantity']
        ITEM_FRAMES[r['key']] = {
            'name': r['name'],
            'description': r['description'] if r['description'] else '',
            'output_item_key': r['output_item_key'],
            'auto_pop': bool(r['auto_pop']),
            'composite_name': r['composite_name'],
            'recipe': recipe,
        }


def _load_schedules(con: sqlite3.Connection) -> None:
    """Load daily schedules from the schedules table.

    Each row becomes a :class:`~classes.jobs.Schedule` instance with
    band lists keyed by activity ('sleep', 'work', 'open'). Publishes
    into the ``SCHEDULES`` module global for later use by ``_load_jobs``.

    Also overwrites the module-level fallback templates (DAY_WORKER,
    NIGHT_WORKER, WANDERER) in ``classes.jobs`` so any code that
    imports those constants directly sees DB-authoritative data.
    """
    global SCHEDULES
    SCHEDULES.clear()

    from classes import jobs as jobs_mod
    from classes.jobs import Schedule

    try:
        rows = con.execute(
            'SELECT key, sleep_bands, work_bands, open_bands FROM schedules'
        ).fetchall()
    except sqlite3.OperationalError:
        return  # table absent — keep hardcoded fallback templates

    for r in rows:
        bands = {}
        for activity, col in (('sleep', 'sleep_bands'),
                               ('work',  'work_bands'),
                               ('open',  'open_bands')):
            raw = r[col] or '[]'
            pairs = json.loads(raw)
            if pairs:
                bands[activity] = [tuple(p) for p in pairs]
        schedule = Schedule(bands=bands)
        SCHEDULES[r['key']] = schedule

    # Keep the module-level fallback constants in sync with DB where
    # possible. Preserves backward compatibility for any caller that
    # imports DAY_WORKER etc. directly.
    if 'day_worker' in SCHEDULES:
        jobs_mod.DAY_WORKER = SCHEDULES['day_worker']
    if 'night_worker' in SCHEDULES:
        jobs_mod.NIGHT_WORKER = SCHEDULES['night_worker']
    if 'wanderer' in SCHEDULES:
        jobs_mod.WANDERER = SCHEDULES['wanderer']


def _load_jobs(con: sqlite3.Connection) -> None:
    """Load the jobs catalog and publish into classes.jobs.DEFAULT_JOBS.

    Each job row becomes a fully-constructed Job instance with its schedule
    resolved from the SCHEDULES global (which must have been populated by
    ``_load_schedules`` first). The module-level ``classes.jobs.DEFAULT_JOBS``
    dict is cleared and repopulated so every caller that imports it sees
    the DB-authoritative catalog.
    """
    global JOBS
    JOBS.clear()

    from classes.jobs import Job, DAY_WORKER, DEFAULT_JOBS
    from classes.stats import Stat

    try:
        rows = con.execute(
            'SELECT key, name, description, purpose, wage_per_tick, '
            'required_stat, required_level, workplace_purposes, '
            'schedule_template FROM jobs'
        ).fetchall()
    except sqlite3.OperationalError:
        return  # table absent (fresh DB) — tests will use hardcoded fallback

    DEFAULT_JOBS.clear()
    for r in rows:
        try:
            stat = Stat[r['required_stat']]
        except KeyError:
            stat = Stat.STR
        schedule = SCHEDULES.get(r['schedule_template'], DAY_WORKER)
        workplaces = tuple(json.loads(r['workplace_purposes'] or '[]'))
        if not workplaces:
            workplaces = (r['purpose'],)
        job = Job(
            name=r['name'] or r['key'],
            purpose=r['purpose'],
            schedule=schedule,
            wage_per_tick=float(r['wage_per_tick']),
            required_stat=stat,
            required_level=int(r['required_level']),
            workplace_purposes=workplaces,
        )
        job.key = r['key']
        job.description = r['description'] or ''
        JOBS[r['key']] = job
        DEFAULT_JOBS[r['key']] = job


def _load_processing_recipes(con: sqlite3.Connection) -> None:
    """Load processing recipes and publish into classes.recipes.PROCESSING_RECIPES.

    Each recipe becomes a ``Recipe`` whose ``output_factory`` clones the
    target item from the ITEMS catalog (so quantity and attributes are
    consistent with the DB). Inputs come from processing_recipe_inputs.
    """
    global PROCESSING_RECIPES
    PROCESSING_RECIPES.clear()

    from classes.recipes import Recipe, PROCESSING_RECIPES as LIVE_LIST
    import copy as _copy

    try:
        recipe_rows = con.execute(
            'SELECT key, name, description, output_item_key, output_quantity, '
            'category, required_tile_purpose, stamina_cost FROM processing_recipes'
        ).fetchall()
    except sqlite3.OperationalError:
        return

    LIVE_LIST.clear()
    for r in recipe_rows:
        inputs: dict[str, int] = {}
        for ing in con.execute(
            'SELECT ingredient_item_key, quantity FROM processing_recipe_inputs '
            'WHERE recipe_key=?', (r['key'],)
        ).fetchall():
            # Use the catalog key (stable across display-name renames).
            # The recipe matcher in classes.recipes counts inventory items
            # under both key and name, so either side can reference the
            # ingredient and still match.
            inputs[ing['ingredient_item_key']] = int(ing['quantity'])

        output_item = ITEMS.get(r['output_item_key'])
        if output_item is None:
            continue  # orphan recipe — skip
        output_qty = int(r['output_quantity'] or 1)

        def _make_factory(template_item, qty):
            def _factory():
                clone = _copy.copy(template_item)
                # Fresh quantity
                clone.quantity = qty
                return clone
            return _factory

        recipe = Recipe(
            name=r['key'],
            inputs=inputs,
            output_factory=_make_factory(output_item, output_qty),
            category=r['category'] or 'food',
        )
        recipe.display_name = r['name'] or r['key']
        recipe.description = r['description'] or ''
        recipe.required_tile_purpose = r['required_tile_purpose'] or 'crafting'
        recipe.stamina_cost = int(r['stamina_cost'] or 1)

        PROCESSING_RECIPES.append(recipe)
        LIVE_LIST.append(recipe)


def _load_animations(con: sqlite3.Connection) -> None:
    for r in con.execute('SELECT name, target_type FROM animations').fetchall():
        ANIMATIONS[r['name']] = {
            'target_type': r['target_type'],
            'frames': [],
        }

    for r in con.execute(
        'SELECT animation_name, frame_index, sprite_name, duration_ms'
        ' FROM animation_frames ORDER BY animation_name, frame_index'
    ).fetchall():
        anim = ANIMATIONS.get(r['animation_name'])
        if anim is not None:
            anim['frames'].append({
                'sprite_name': r['sprite_name'],
                'duration_ms': r['duration_ms'],
            })

    # Pre-compute total duration for each animation
    for anim in ANIMATIONS.values():
        anim['total_duration_ms'] = sum(f['duration_ms'] for f in anim['frames'])

    for r in con.execute(
        'SELECT target_name, behavior, animation_name FROM animation_bindings'
    ).fetchall():
        ANIM_BINDINGS[(r['target_name'], r['behavior'])] = r['animation_name']


def _load_composites(con: sqlite3.Connection) -> None:
    # Load composite definitions
    for r in con.execute('SELECT name, root_layer FROM composite_sprites').fetchall():
        COMPOSITES[r['name']] = {
            'root_layer': r['root_layer'],
            'layers': {},       # layer_name → {z_layer, default_sprite}
            'connections': {},  # child_layer → {parent_layer, parent_socket, child_anchor}
            'variants': {},     # layer_name → {variant_name → sprite_name}
        }

    # Load layers
    for r in con.execute(
        'SELECT composite_name, layer_name, z_layer, default_sprite'
        ' FROM composite_layers ORDER BY z_layer'
    ).fetchall():
        comp = COMPOSITES.get(r['composite_name'])
        if comp:
            comp['layers'][r['layer_name']] = {
                'z_layer': r['z_layer'],
                'default_sprite': r['default_sprite'],
            }

    # Load connections
    for r in con.execute(
        'SELECT composite_name, parent_layer, child_layer,'
        ' parent_socket_x, parent_socket_y, child_anchor_x, child_anchor_y'
        ' FROM layer_connections'
    ).fetchall():
        comp = COMPOSITES.get(r['composite_name'])
        if comp:
            comp['connections'][r['child_layer']] = {
                'parent_layer': r['parent_layer'],
                'parent_socket': (r['parent_socket_x'], r['parent_socket_y']),
                'child_anchor': (r['child_anchor_x'], r['child_anchor_y']),
            }

    # Load variants
    for r in con.execute(
        'SELECT composite_name, layer_name, variant_name, sprite_name'
        ' FROM layer_variants'
    ).fetchall():
        comp = COMPOSITES.get(r['composite_name'])
        if comp:
            comp['variants'].setdefault(r['layer_name'], {})[r['variant_name']] = r['sprite_name']

    # Load composite animations
    for r in con.execute(
        'SELECT name, composite_name, loop, duration_ms, time_scale'
        ' FROM composite_animations'
    ).fetchall():
        COMPOSITE_ANIMS[r['name']] = {
            'composite_name': r['composite_name'],
            'loop': bool(r['loop']),
            'duration_ms': r['duration_ms'],
            'time_scale': r['time_scale'] if r['time_scale'] is not None else 1.0,
            'keyframes': {},
        }

    for r in con.execute(
        'SELECT animation_name, layer_name, time_ms, offset_x, offset_y,'
        ' rotation_deg, variant_name, tint_r, tint_g, tint_b, opacity, scale'
        ' FROM composite_anim_keyframes ORDER BY animation_name, layer_name, time_ms'
    ).fetchall():
        anim = COMPOSITE_ANIMS.get(r['animation_name'])
        if anim:
            tint = None
            if r['tint_r'] is not None and r['tint_g'] is not None and r['tint_b'] is not None:
                tint = (r['tint_r'], r['tint_g'], r['tint_b'])
            anim['keyframes'].setdefault(r['layer_name'], []).append({
                'time_ms': r['time_ms'],
                'offset_x': r['offset_x'],
                'offset_y': r['offset_y'],
                'rotation_deg': r['rotation_deg'],
                'variant_name': r['variant_name'],
                'tint': tint,
                'opacity': r['opacity'] if r['opacity'] is not None else 1.0,
                'scale': r['scale'] if r['scale'] is not None else 1.0,
            })

    # Load composite animation bindings
    for r in con.execute(
        'SELECT target_name, behavior, animation_name, flip_h'
        ' FROM composite_anim_bindings'
    ).fetchall():
        COMPOSITE_ANIM_BINDINGS[(r['target_name'], r['behavior'])] = {
            'animation_name': r['animation_name'],
            'flip_h': bool(r['flip_h']),
        }
