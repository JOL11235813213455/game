import json
import sqlite3
from pathlib import Path

DB_PATH = str(Path(__file__).parent.parent / 'src' / 'data' / 'game.db')


def get_con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def fetch_sprite_names() -> list[str]:
    con = get_con()
    try:
        rows = con.execute('SELECT name FROM sprites ORDER BY name').fetchall()
        return [r['name'] for r in rows]
    finally:
        con.close()


def fetch_sprite(name: str) -> dict | None:
    """Return sprite dict with palette, pixels, width, height, action_point, or None."""
    if not name:
        return None
    con = get_con()
    try:
        row = con.execute(
            'SELECT palette, pixels, width, height, action_point_x, action_point_y'
            ' FROM sprites WHERE name=?', (name,)
        ).fetchone()
        if row is None:
            return None
        raw_palette = json.loads(row['palette'])
        palette = {}
        for char, val in raw_palette.items():
            if isinstance(val, (list, tuple)):
                r, g, b = val
                palette[char] = f'#{r:02x}{g:02x}{b:02x}'
            else:
                palette[char] = val  # already a hex string
        apx = row['action_point_x']
        apy = row['action_point_y']
        return {
            'palette':        palette,
            'pixels':         json.loads(row['pixels']),
            'width':          row['width'],
            'height':         row['height'],
            'action_point':   (apx, apy) if apx is not None and apy is not None else None,
        }
    finally:
        con.close()


def fetch_tile_keys() -> list[str]:
    con = get_con()
    try:
        return [r['key'] for r in con.execute('SELECT key FROM tiles ORDER BY key').fetchall()]
    finally:
        con.close()


def fetch_tile_set_names() -> list[str]:
    con = get_con()
    try:
        return [r['name'] for r in con.execute('SELECT name FROM tile_sets ORDER BY name').fetchall()]
    finally:
        con.close()


def fetch_map_names() -> list[str]:
    con = get_con()
    try:
        return [r['name'] for r in con.execute('SELECT name FROM maps ORDER BY name').fetchall()]
    finally:
        con.close()


def migrate_db():
    """Add columns introduced after initial schema — safe to run on every startup."""
    con = get_con()
    try:
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
            "CREATE TABLE IF NOT EXISTS tile_sets (name TEXT PRIMARY KEY)",
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
    finally:
        con.close()
