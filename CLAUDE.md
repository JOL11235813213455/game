# Project: Tile-Based RPG

Python/pygame tile-based RPG with a tkinter database editor. Unknown genre, though
leaning towards apocalyptic

## Architecture

- **Game runtime**: `src/` — pygame, runs via `src/main.py`
- **Editor**: `editor/` — tkinter, runs via `editor.py`, no pygame dependency
- **Database**: `src/data/game.db` — single SQLite file, shared by both
- **Migrations**: `src/data/db.py` (`_migrate`) and `editor/db.py` (`migrate_db`) — must stay in sync
- **Seed schema**: `src/data/seed.py` — canonical CREATE TABLE definitions for fresh DBs

## Key Conventions

- MapKey is a namedtuple `(x, y, z)` — hashable, used as dict keys for tile lookups. DB stores x/y/z as separate columns; classes assemble them into MapKey immediately on load.
- 3/4 perspective: tile height = block_size * 0.75
- Sprites are character grids + palette dicts, NOT image files
- Composite sprites: hierarchical layers with connections, keyframe animations
- All editor tooltips via `add_tooltip(widget, text)` from `editor/tooltip.py`
- Editor uses `editor/db.py` helpers (fetch_*, get_con); game uses `src/data/db.py` loader
- PIL/Pillow for editor image rendering (sprite_to_photoimage.py)
- Trackable is the root class to all other game classes, and is used to make
    objects trackable. It is a very powerful feature because we can get
    _all_instances()/all() for every class.
- tile sets are dictionaries of Tiles with MapKey keys

## Critical Architectural Knowledge

### Save System (src/main/save_ui.py, src/save.py)
- Uses **pickle** serialization — `Trackable.all_instances()` captures every live object
- On load, `_held = objects` keeps a strong reference to unpickled objects — without this, WeakSets GC them instantly and the game is empty
- `WorldObject._by_map` must be cleared and rebuilt on load
- Map stack (`creature.map_stack`) must survive serialization or the player is stranded in nested maps
- Pickle is NOT safe for untrusted data — only load save files you trust

### Sprite Cache Invalidation (src/main/sprite_cache.py)
- All sprites are cached at specific pixel dimensions tied to zoom level
- When zoom changes, scaled + composite caches are flushed, native cache is kept
- Composite animations are **pre-rendered** into flat frame lists on first access — NOT animated live. This is a performance requirement, not a preference
- Flip (mirror) is applied at `WorldObject` level AFTER cache lookup — cached frames serve both directions

### SDL Audio (src/main.py lines 4-13)
*NOTE FROM HUMAN - SOUND HAD NOT YET BEEN DEMONSTRATED - THAT IS OK*
- Audio driver is auto-detected before pygame.init() by trying pipewire → pulse → alsa → default
- Without this, the game hangs or crashes on Linux systems where the default driver is wrong

### Rendering Pipeline
- 3/4 perspective: always use `get_tile_height()` for Y positioning, `get_block_size()` for X
- Camera clamps to map bounds — never shows beyond edges
- Tile animations use `time_ms % total_duration` for frame selection (time-based, not frame-count-based)
- Top lighting gradients are bucketed by elevation to limit cache entries

### Collision System
- Structures have BOTH `footprint` (visual extent) and `collision_mask` (movement blocking) — they're different
- Movement bounds check BOTH the exit direction of the current tile AND entry direction of the target tile
- `entry_points` on structures use string keys like `'1,0'` for the offset, NOT tuples

## Feature Implementation Checklist

Every new feature must touch ALL of these layers. Do not skip any.

### 1. Data Model (classes)
- [ ] Add/modify fields on relevant class(es) in `src/classes/`
- [ ] Update `__init__` parameters and defaults
- [ ] Update any enums (e.g. `Stat` in creature.py)
- [ ] Verify namedtuples if coordinates/keys change

### 2. Database Schema
- [ ] Add column/table in `src/data/db.py` `_migrate()` — CREATE TABLE or ALTER TABLE
- [ ] Mirror the EXACT same change in `editor/db.py` `migrate_db()`
- [ ] Update `src/data/seed.py` canonical schema
- [ ] If renaming/dropping: add migration (ALTER TABLE RENAME/DROP) in both db.py files
- [ ] If new table: add to `_CLUSTERS` and `_SOFT_FKS` in `editor/sql_tab.py` ERD

### 3. Data Loader (src/data/db.py)
- [ ] Update the relevant `_load_*()` function to read new columns
- [ ] Pass loaded data to class constructor or set on instance
- [ ] Update any global dicts (TILE_TEMPLATES, SPECIES, ITEMS, etc.)

### 4. Game Logic (src/)
- [ ] Implement the runtime behavior (methods, checks, interactions)
- [ ] Wire into existing systems (move, enter, render, update loop, etc.)
- [ ] Handle edge cases (None values, missing data, defaults)

### 5. Editor UI
- [ ] Add input widgets to the correct editor tab in `editor/`
- [ ] Add `add_tooltip(widget, 'description')` to EVERY new widget
- [ ] Wire save: read from widget → include in INSERT/UPDATE SQL
- [ ] Wire load: read from DB row → populate widget
- [ ] Wire clear: reset widget to default
- [ ] Add to refresh_dropdown methods if it's a foreign key reference
- [ ] Update `editor/db.py` if new fetch helper is needed

### 6. Editor — Map Editor (if tile/map related)
- [ ] Update `map_editor_tab.py` save/load to include new fields
- [ ] Update `map_canvas.py` if it affects visual rendering
- [ ] Update `tile_palette.py` if it affects template display

### 7. Documentation
- [ ] Update `editor/sql_tab.py` `desc_map` with descriptions for new columns
- [ ] Update `editor/sql_tab.py` `_SOFT_FKS` if new cross-table references
- [ ] Update `editor/sql_tab.py` `_CLUSTERS` if new table
- [ ] Update `docs/incomplete_features.txt` — add if incomplete, move to completed
- [ ] update `CLAUDE.md` to reflect any critical architectural knowledge incremented

### 8. Verification
- [ ] `py_compile` all modified files
- [ ] Smoke test: editor constructs without error
- [ ] Smoke test: game launches without error (if runtime changes)
- [ ] Verify DB migration works on existing database
- [ ] Verify DB creates correctly from scratch (fresh file)

## File Quick Reference

| Purpose | File(s) |
|---|---|
| Game entry | `src/main.py` |
| Editor entry | `editor.py` → `editor/app.py` |
| Map/Tile classes | `src/classes/maps.py` |
| Creature/NPC/Stats | `src/classes/creature.py` |
| Items/Inventory | `src/classes/inventory.py` |
| WorldObject base | `src/classes/world_object.py` |
| Instance tracking | `src/classes/trackable.py` |
| Game DB + loader | `src/data/db.py` |
| Editor DB + helpers | `editor/db.py` |
| Seed schema | `src/data/seed.py` |
| Sprite cache | `src/main/sprite_cache.py` |
| Rendering | `src/main/rendering.py` |
| Config | `src/main/config.py` |
| Editor tab wiring | `editor/app.py` |
| SQL/ERD/Dictionary | `editor/sql_tab.py` |
| Incomplete features | `docs/incomplete_features.txt` |
| Stat system design | `docs/stat_system.md` |
