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


def fetch_sprite_sets() -> list[str]:
    """Return distinct non-null sprite_set values."""
    con = get_con()
    try:
        rows = con.execute(
            'SELECT DISTINCT sprite_set FROM sprites'
            ' WHERE sprite_set IS NOT NULL AND sprite_set != \'\''
            ' ORDER BY sprite_set').fetchall()
        return [r['sprite_set'] for r in rows]
    finally:
        con.close()


def fetch_sprite_names_by_set(sprite_set: str | None = None) -> list[str]:
    """Return sprite names, optionally filtered by sprite_set."""
    con = get_con()
    try:
        if sprite_set:
            rows = con.execute(
                'SELECT name FROM sprites WHERE sprite_set=? ORDER BY name',
                (sprite_set,)).fetchall()
        else:
            rows = con.execute(
                'SELECT name FROM sprites ORDER BY name').fetchall()
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


def fetch_tile_template_keys() -> list[str]:
    con = get_con()
    try:
        return [r['key'] for r in con.execute('SELECT key FROM tile_templates ORDER BY key').fetchall()]
    finally:
        con.close()


def fetch_tile_set_names() -> list[str]:
    con = get_con()
    try:
        return [r['name'] for r in con.execute('SELECT name FROM tile_set_names').fetchall()]
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
            "ALTER TABLE tile_templates ADD COLUMN animation_name TEXT",
            "ALTER TABLE items   ADD COLUMN collision INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE items   ADD COLUMN footprint TEXT",
            "ALTER TABLE items   ADD COLUMN collision_mask TEXT",
            "ALTER TABLE items   ADD COLUMN entry_points TEXT",
            "ALTER TABLE items   ADD COLUMN nested_map TEXT",
            "ALTER TABLE species ADD COLUMN tile_scale REAL NOT NULL DEFAULT 1.0",
            "ALTER TABLE species ADD COLUMN composite_name TEXT",
            "ALTER TABLE sprites ADD COLUMN sprite_set TEXT",
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
        ]:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column/table already exists
        # Migrate old tile_sets table (has map_name column)
        try:
            con.execute("SELECT map_name FROM tile_sets LIMIT 1")
        except sqlite3.OperationalError:
            pass  # already new schema or table doesn't exist
        else:
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
            pass
        else:
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
            # Merge data from old tiles into tile_templates
            con.execute("""INSERT OR IGNORE INTO tile_templates
                (key, name, walkable, covered, sprite_name, tile_scale,
                 bounds_n, bounds_s, bounds_e, bounds_w,
                 bounds_ne, bounds_nw, bounds_se, bounds_sw)
                SELECT key, name, walkable, covered, sprite_name, tile_scale,
                 bounds_n, bounds_s, bounds_e, bounds_w,
                 bounds_ne, bounds_nw, bounds_se, bounds_sw
                FROM tiles""")
            # Copy animation_name if the old table had it
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
            pass
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
                pass
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
        ]:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass
        con.commit()
    finally:
        con.close()


def fetch_composite_names() -> list[str]:
    con = get_con()
    try:
        return [r['name'] for r in con.execute(
            'SELECT name FROM composite_sprites ORDER BY name').fetchall()]
    finally:
        con.close()


def fetch_animation_names() -> list[str]:
    con = get_con()
    try:
        return [r['name'] for r in con.execute('SELECT name FROM animations ORDER BY name').fetchall()]
    finally:
        con.close()


def fetch_species_names() -> list[str]:
    con = get_con()
    try:
        return [r['name'] for r in con.execute('SELECT name FROM species ORDER BY name').fetchall()]
    finally:
        con.close()
