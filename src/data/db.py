import sqlite3
import json
from pathlib import Path

from classes.creature import Stat
from classes.inventory import (
    Item, Stackable, Consumable, Ammunition,
    Equippable, Weapon, Wearable, Slot, CLASS_MAP
)

_DB_PATH = Path(__file__).parent / 'game.db'
_loaded  = False

SPECIES:     dict[str, dict] = {}
PLAYABLE:    dict[str, dict] = {}
NONPLAYABLE: dict[str, dict] = {}
ITEMS:       dict[str, Item] = {}
SPRITE_DATA: dict[str, dict] = {}
TILES: dict[str, dict] = {}
MAPS:  dict[str, object] = {}


def _migrate(con: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema creation."""
    for stmt in [
        "ALTER TABLE sprites ADD COLUMN width  INTEGER NOT NULL DEFAULT 8",
        "ALTER TABLE sprites ADD COLUMN height INTEGER NOT NULL DEFAULT 8",
        "ALTER TABLE sprites ADD COLUMN action_point_x INTEGER",
        "ALTER TABLE sprites ADD COLUMN action_point_y INTEGER",
        "ALTER TABLE items   ADD COLUMN tile_scale REAL NOT NULL DEFAULT 1.0",
        "ALTER TABLE species ADD COLUMN tile_scale REAL NOT NULL DEFAULT 1.0",
        """CREATE TABLE IF NOT EXISTS tiles (
    key TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
    walkable INTEGER NOT NULL DEFAULT 1, covered INTEGER NOT NULL DEFAULT 0,
    sprite_name TEXT, tile_scale REAL NOT NULL DEFAULT 1.0,
    bounds_n TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w TEXT,
    bounds_ne TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT)""",
        """CREATE TABLE IF NOT EXISTS tile_sets (
    name TEXT PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS tile_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tile_set TEXT NOT NULL, w INTEGER NOT NULL DEFAULT 0,
    x INTEGER NOT NULL, y INTEGER NOT NULL, z INTEGER NOT NULL DEFAULT 0,
    tile_template TEXT, walkable INTEGER, covered INTEGER,
    sprite_name TEXT, tile_scale REAL,
    bounds_n TEXT, bounds_s TEXT, bounds_e TEXT, bounds_w TEXT,
    bounds_ne TEXT, bounds_nw TEXT, bounds_se TEXT, bounds_sw TEXT,
    nested_map TEXT)""",
        """CREATE TABLE IF NOT EXISTS maps (
    name TEXT PRIMARY KEY, tile_set TEXT, default_tile TEXT,
    entrance_x INTEGER NOT NULL DEFAULT 0, entrance_y INTEGER NOT NULL DEFAULT 0,
    w_min INTEGER NOT NULL DEFAULT 0, w_max INTEGER NOT NULL DEFAULT 0,
    x_min INTEGER NOT NULL DEFAULT 0, x_max INTEGER NOT NULL DEFAULT 0,
    y_min INTEGER NOT NULL DEFAULT 0, y_max INTEGER NOT NULL DEFAULT 0,
    z_min INTEGER NOT NULL DEFAULT 0, z_max INTEGER NOT NULL DEFAULT 0)""",
        "ALTER TABLE maps ADD COLUMN tile_set TEXT",
    ]:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column/table already exists

    # Migrate old tile_sets table (has map_name column) → tile_entries
    try:
        con.execute("SELECT map_name FROM tile_sets LIMIT 1")
    except sqlite3.OperationalError:
        pass  # already new schema or table doesn't exist
    else:
        # Old schema — rename, recreate, migrate data
        con.execute("ALTER TABLE tile_sets RENAME TO _old_tile_sets")
        con.execute("CREATE TABLE tile_sets (name TEXT PRIMARY KEY)")
        con.execute("""INSERT OR IGNORE INTO tile_entries
            (tile_set, w, x, y, z, tile_template, walkable, covered,
             sprite_name, tile_scale, bounds_n, bounds_s, bounds_e, bounds_w,
             bounds_ne, bounds_nw, bounds_se, bounds_sw, nested_map)
            SELECT map_name, w, x, y, z, tile_template, walkable, covered,
             sprite_name, tile_scale, bounds_n, bounds_s, bounds_e, bounds_w,
             bounds_ne, bounds_nw, bounds_se, bounds_sw, nested_map
            FROM _old_tile_sets""")
        con.execute("INSERT OR IGNORE INTO tile_sets (name) SELECT DISTINCT tile_set FROM tile_entries")
        con.execute("UPDATE maps SET tile_set = name WHERE tile_set IS NULL")
        con.execute("DROP TABLE _old_tile_sets")

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
        _load_items(con)
        _load_sprites(con)
        _load_tiles(con)
        _load_maps(con)
    finally:
        con.close()
    _loaded = True


def _load_species(con: sqlite3.Connection) -> None:
    rows      = con.execute('SELECT name, playable, sprite_name, tile_scale FROM species').fetchall()
    stat_rows = con.execute('SELECT species_name, stat, value FROM species_stats').fetchall()

    stats_by_species: dict[str, dict] = {r['name']: {} for r in rows}
    for r in stat_rows:
        stats_by_species[r['species_name']][Stat(r['stat'])] = r['value']

    for r in rows:
        name  = r['name']
        block = stats_by_species[name]
        if r['sprite_name'] is not None:
            block['sprite_name'] = r['sprite_name']
        block['tile_scale'] = r['tile_scale'] if r['tile_scale'] is not None else 1.0
        SPECIES[name] = block
        if r['playable']:
            PLAYABLE[name] = block
        else:
            NONPLAYABLE[name] = block


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
            ,buffs       = json.loads(r['buffs'] or '{}')
        )
        if r['sprite_name'] is not None:
            base['sprite_name'] = r['sprite_name']

        if cls in (Stackable, Consumable, Ammunition):
            if r['max_stack_size'] is not None:
                base['max_stack_size'] = r['max_stack_size']
            if r['quantity'] is not None:
                base['quantity'] = r['quantity']

        if cls == Consumable and r['duration'] is not None:
            base['duration'] = r['duration']

        if cls == Ammunition:
            if r['damage'] is not None:
                base['damage'] = r['damage']
            if r['destroy_on_use_probability'] is not None:
                base['destroy_on_use_probability'] = r['destroy_on_use_probability']

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

        ITEMS[key] = cls(**base)
        if r['tile_scale'] is not None:
            ITEMS[key].tile_scale = r['tile_scale']


def _load_tiles(con: sqlite3.Connection) -> None:
    from classes.maps import Bounds, Bound
    BOUND_ATTRS = ('n','s','e','w','ne','nw','se','sw')
    for r in con.execute('SELECT * FROM tiles').fetchall():
        b_kwargs = {a: (Bound(r[f'bounds_{a}']) if r[f'bounds_{a}'] else Bound.NONE) for a in BOUND_ATTRS}
        TILES[r['key']] = {
            'name':        r['name'],
            'walkable':    bool(r['walkable']),
            'covered':     bool(r['covered']),
            'sprite_name': r['sprite_name'],
            'tile_scale':  r['tile_scale'] if r['tile_scale'] is not None else 1.0,
            'bounds':      Bounds(**b_kwargs),
        }


def _load_maps(con: sqlite3.Connection) -> None:
    from classes.maps import Map, MapKey, Tile, Bounds, Bound

    map_rows = con.execute('SELECT * FROM maps').fetchall()
    te_rows  = con.execute('SELECT * FROM tile_entries ORDER BY tile_set').fetchall()

    # Index tile_entries by tile_set name
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
            default_tile = r['default_tile'],
            w_min=r['w_min'], w_max=r['w_max'],
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
            tmpl = TILES.get(te['tile_template']) if te['tile_template'] else {}
            has_bounds = any(te[f'bounds_{a}'] for a in BOUND_ATTRS)
            if has_bounds:
                b_kwargs = {a: (Bound(te[f'bounds_{a}']) if te[f'bounds_{a}'] else Bound.NONE) for a in BOUND_ATTRS}
                bounds = Bounds(**b_kwargs)
            else:
                bounds = None
            m.tiles[MapKey(te['w'], te['x'], te['y'], te['z'])] = Tile(
                template      = tmpl,
                map           = map_objs.get(te['nested_map']),
                walkable      = bool(te['walkable']) if te['walkable'] is not None else None,
                covered       = bool(te['covered'])  if te['covered']  is not None else None,
                bounds        = bounds,
                tile_template = te['tile_template'],
                sprite_name   = te['sprite_name'] or None,
                tile_scale    = float(te['tile_scale']) if te['tile_scale'] is not None else None,
            )

    # Fill remaining coords with default tile
    for m in map_objs.values():
        tmpl = TILES.get(m.default_tile) if m.default_tile else None
        if tmpl is None:
            continue
        for w in range(m.w_min, m.w_max + 1):
            for x in range(m.x_min, m.x_max + 1):
                for y in range(m.y_min, m.y_max + 1):
                    for z in range(m.z_min, m.z_max + 1):
                        key = MapKey(w, x, y, z)
                        if key not in m.tiles:
                            m.tiles[key] = Tile(
                                template      = tmpl,
                                tile_template = m.default_tile,
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
