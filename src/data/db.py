import sqlite3
import json
from pathlib import Path

from classes.creature import Stat
from classes.inventory import (
    Item, Stackable, Consumable, Ammunition,
    Equippable, Weapon, Wearable, Structure, Slot, CLASS_MAP
)

_DB_PATH = Path(__file__).parent / 'game.db'
_loaded  = False

SPECIES:     dict[str, dict] = {}
PLAYABLE:    dict[str, dict] = {}
NONPLAYABLE: dict[str, dict] = {}
ITEMS:       dict[str, Item] = {}
SPRITE_DATA: dict[str, dict] = {}
TILE_TEMPLATES: dict[str, dict] = {}
MAPS:  dict[str, object] = {}
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
    ]:
        try:
            con.execute(stmt)
        except sqlite3.OperationalError:
            pass

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
        _load_tile_templates(con)
        _load_maps(con)
        _load_animations(con)
        _load_composites(con)
    finally:
        con.close()
    _loaded = True


def _load_species(con: sqlite3.Connection) -> None:
    rows      = con.execute('SELECT name, playable, sprite_name, tile_scale, composite_name FROM species').fetchall()
    stat_rows = con.execute('SELECT species_name, stat, value FROM species_stats').fetchall()

    stats_by_species: dict[str, dict] = {r['name']: {} for r in rows}
    for r in stat_rows:
        stats_by_species[r['species_name']][Stat(r['stat'])] = r['value']

    for r in rows:
        name  = r['name']
        block = stats_by_species[name]
        if r['sprite_name'] is not None:
            block['sprite_name'] = r['sprite_name']
        if r['composite_name'] is not None:
            block['composite_name'] = r['composite_name']
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
