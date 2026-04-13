import pickle
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from platformdirs import user_data_dir
from classes.trackable import Trackable

_save_dir = Path(user_data_dir("game", appauthor=False))
_save_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = _save_dir / "saves.db"

_held = None  # strong reference keeping loaded objects alive in WeakSets


def _get_con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    con.execute('''
        CREATE TABLE IF NOT EXISTS save_files (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT    NOT NULL
        )
    ''')
    con.execute('''
        CREATE TABLE IF NOT EXISTS saves (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            save_file_id  INTEGER NOT NULL DEFAULT 1,
            name          TEXT    NOT NULL,
            saved_at      TEXT    NOT NULL,
            data          BLOB    NOT NULL
        )
    ''')

    # Migration: add save_file_id column to saves if it predates this schema
    cols = [row[1] for row in con.execute('PRAGMA table_info(saves)')]
    if 'save_file_id' not in cols:
        con.execute('ALTER TABLE saves ADD COLUMN save_file_id INTEGER NOT NULL DEFAULT 1')

    # Always ensure at least one save file exists
    if not con.execute('SELECT id FROM save_files LIMIT 1').fetchone():
        con.execute("INSERT INTO save_files (name) VALUES ('Default')")

    con.commit()
    return con


def _serialise(player) -> bytes:
    return pickle.dumps({
        'player':  player,
        'objects': tuple(Trackable.all_instances()),
    })


def _deserialise(blob: bytes):
    global _held
    from classes.world_object import WorldObject
    from classes.relationship_graph import _rebind_after_load
    # Clear stale map index before loading
    WorldObject._by_map.clear()
    data = pickle.loads(blob)
    objects = data['objects']
    _held = objects
    for obj in objects:
        type(obj)._instances.add(obj)
        if isinstance(obj, WorldObject) and obj._current_map is not None:
            WorldObject._by_map[id(obj._current_map)].add(obj)
    # Point the module-level GRAPH at the unpickled instance
    _rebind_after_load()
    # Legacy saves without a RelationshipGraph Trackable: the creature
    # __setstate__ already migrated per-creature dicts into whatever
    # GRAPH existed at unpickle time, so nothing extra needed.
    Trackable.reset_uid_counter()
    return data['player']


# ---- save files -------------------------------------------------------------

def list_save_files() -> list:
    """Return all save files as rows (id, name)."""
    con = _get_con()
    try:
        return con.execute('SELECT id, name FROM save_files ORDER BY id').fetchall()
    finally:
        con.close()


def create_save_file(name: str) -> int:
    """Create a new save file and return its id."""
    con = _get_con()
    try:
        cur = con.execute('INSERT INTO save_files (name) VALUES (?)', (name,))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def delete_save_file(save_file_id: int) -> bool:
    """Delete a save file and all saves within it."""
    con = _get_con()
    try:
        con.execute('DELETE FROM saves WHERE save_file_id = ?', (save_file_id,))
        cur = con.execute('DELETE FROM save_files WHERE id = ?', (save_file_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


# ---- saves ------------------------------------------------------------------

def list_saves(save_file_id: int) -> list:
    """Return saves for a save file, newest first."""
    con = _get_con()
    try:
        return con.execute(
            'SELECT id, name, saved_at FROM saves'
            ' WHERE save_file_id = ? ORDER BY saved_at DESC',
            (save_file_id,)
        ).fetchall()
    finally:
        con.close()


def create_save(player, name: str, save_file_id: int) -> int:
    """Insert a new save row and return its id."""
    blob = _serialise(player)
    now  = datetime.now(timezone.utc).isoformat()
    con  = _get_con()
    try:
        cur = con.execute(
            'INSERT INTO saves (save_file_id, name, saved_at, data) VALUES (?, ?, ?, ?)',
            (save_file_id, name, now, blob),
        )
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def overwrite_save(player, save_id: int) -> bool:
    """Overwrite an existing save by id."""
    blob = _serialise(player)
    now  = datetime.now(timezone.utc).isoformat()
    con  = _get_con()
    try:
        cur = con.execute(
            'UPDATE saves SET data=?, saved_at=? WHERE id=?',
            (blob, now, save_id),
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def load_save(save_id: int):
    """Load a save by id. Returns player object, or None if not found."""
    con = _get_con()
    try:
        row = con.execute('SELECT data FROM saves WHERE id=?', (save_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return _deserialise(row['data'])


def delete_save(save_id: int) -> bool:
    """Delete a save by id."""
    con = _get_con()
    try:
        cur = con.execute('DELETE FROM saves WHERE id=?', (save_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()
