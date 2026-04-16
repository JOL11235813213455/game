commit with comments frequentlys

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

- **Speed is tiles-per-second (TPS).** Default base speed is 4 TPS. Movement speed formula: `base_TPS = max(0, 4 + agl_mod)`. After base TPS, two types of external modifiers apply (from a future `Modifiers` class — consumables, equippables; environment TBD): **percent mods** scale the stat-derived base, then **unit mods** add flat TPS on top unscaled. `final_TPS = base_TPS * (1 + pct_mods) + unit_mods`. Final TPS → interval: `interval = 1 / final_TPS`.
- **D&D-style stat modifiers.** All derived stats use `(base_stat - 10) // 2` as the modifier, not the raw stat value. 10 is neutral (±0), 20 is +5, 1 is -5. This applies across all derived stat formulas.
- **All stat bonuses stack additively, NEVER multiplicatively.** Two 25% bonuses = 50% total, not 56.25%. This applies everywhere: speed, damage, resistance, all modifiers.
- MapKey is a namedtuple `(x, y, z)` — hashable, used as dict keys for tile lookups. DB stores x/y/z as separate columns; classes assemble them into MapKey immediately on load.
- 3/4 perspective: tile height = block_size * 0.75
- Sprites are character grids + palette dicts, NOT image files
- **Sprite naming convention** — rigid prefix-based naming:
  - `t_` = tile (t_grass, t_water_01, t_dirt)
  - `c_` = creature (c_human_m_idle, c_human_f_walk_south)
  - `i_` = item/equippable (i_sword_short, i_helm_iron, i_shirt_cotton)
  - `a_` = ammunition (a_arrow, a_arrow_poison)
  - `s_` = structure (s_house_wood, s_wall_stone)
  - `m_` = misc/stackable (m_gold_piece, m_potion_health)
  - `e_` = egg (e_human, e_orc)
  - Format: `{type}_{species/material}_{variant}_{detail}`
  - Examples: c_human_f_head_down, i_boots_leather, t_water_anim_02
- Composite sprites: hierarchical layers with connections, keyframe animations
- All editor tooltips via `add_tooltip(widget, text)` from `editor/tooltip.py`
- Editor uses `editor/db.py` helpers (fetch_*, get_con); game uses `src/data/db.py` loader
- PIL/Pillow for editor image rendering (sprite_to_photoimage.py)
- Trackable is the root class to all other game classes, and is used to make
    objects trackable. It is a very powerful feature because we can get
    _all_instances()/all() for every class.
- tile sets are dictionaries of Tiles with MapKey keys

## Performance Guidelines

- **Spatial grid over full scans.** NEVER iterate `WorldObject.on_map()` or `Trackable.all_instances()` to find creatures. Use `creature.nearby(max_dist)` for spatial queries (O(cell) via the Map's grid), `Creature.by_uid(uid)` for direct lookups (O(1) via UID registry), or `Creature.on_same_map(map)` for all creatures on a map. The spatial grid lives in `Map._creature_cells` and is updated automatically by the Creature location setter.
- **Cython for numeric hotpaths.** Tight numeric loops (math transforms, neural network inference, raycasting, distance calculations) should have Cython implementations in `src/fast_native/`. Pattern: `try: from fast_native.fast_math import c_func; except ImportError: def c_func(...): # pure Python fallback`. Build with `cd src/fast_native && python setup.py build_ext --inplace`.
- **Staggered ticks.** Use `TickScheduler(max_per_frame=25)` to distribute creature updates across frames. Only ~25 creatures tick per frame; others just animate. Behavior intervals (500ms+) naturally spread across 60fps.
- **Batch NN inference.** When multiple creatures need decisions the same frame, stack observations into one matrix and run a single forward pass via `BatchBehavior`. 3-5x faster than per-creature inference.
- **Off-map reduced rate.** Creatures on non-active maps tick via `WorldManager` at reduced rate (once per 30 game-seconds) for hunger/fatigue only — no perception, no behavior.
- **Observation caching caveat.** Do NOT cache full observations — they include census data from other creatures' positions. The per-tick perception cache (`_perception_cache_tick`) is the safe caching boundary.
- **Event-driven over polling for inter-object communication.** Individual NN forward passes stay tick-driven (the NN must fire periodically — absence of events is itself information). But all data flow *between* objects — perception updates, pack signals, creature-to-creature sightings, damage notifications, relationship changes, inventory changes — should be event-driven. Objects emit events on state change; receivers latch the last value. Use dirty flags to invalidate cached computations (social topology, observation sub-vectors, spatial memory) so they only recompute when upstream state actually changed. Polling is reserved for things that genuinely need periodic re-evaluation (hunger drain, regen ticks). If you're scanning "did anything change?" every tick, it should be an event instead.

## Critical Architectural Knowledge

### Creature / Stat System (src/classes/creature.py, src/classes/stats.py)
- **There is exactly ONE creature class** — no subclasses, ever. Players, NPCs, and monsters are all `Creature`. Behavioral differences come from behavior modules assigned to `creature.behavior`.
- Base stats: STR, PER, VIT, INT, CHR, LCK, AGL (CON was renamed to VIT)
- `Stat` enum and all stat logic live in `src/classes/stats.py`, NOT in creature.py
- `creature.stats` is a `Stats` object with four layers: `base`, `derived`, `mods`, `active`
- `stats.active[Stat.X]()` — callable that returns the final evaluated value
- Derived stats (MHP, SIGHT_RANGE, etc.) are computed from base stats via formulas in `DERIVED_FORMULAS`
- Perception derives both `SIGHT_RANGE` and `HEARING_RANGE` (denominated in tiles)
- Opposing stat contests use `stats.contest(other_stats, contest_name)` with d20 rolls
- `creature.dialogue` exists as a placeholder for future dialogue system

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
- [ ] Update any enums (e.g. `Stat` in stats.py)
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

### 7.5 Neural Net / RL (if feature adds observable state or actions)
- [ ] Update `docs/nn_inputs.txt` if new variables should be visible to the creature model
- [ ] Update `src/classes/observation.py` `build_observation()` to include new inputs
- [ ] Update `OBSERVATION_SIZE` constant and net input dimensions if size changed
- [ ] Update `src/classes/actions.py` if new actions added (renumber, update NUM_ACTIONS)
- [ ] Update `src/classes/reward.py` if new reward signals or snapshot fields needed
- [ ] Update `src/simulation/net.py` layer sizes if input/output dimensions changed
- [ ] Retrain model after significant observation/action changes

### 7.6 Curriculum (REQUIRED for any RL-affecting feature)
The training pipeline runs in 7 staged curriculum stages stored in
the `curriculum_stages` table. When you add or change a mechanic that
affects training, you MUST decide which stage(s) it belongs to and
update the seed accordingly:
- [ ] Identify which stage first introduces this feature (Wander,
      Forage, Eat, Harvest & Process, Trade, Combat & Social, Lifecycle)
- [ ] If the feature adds a new reward signal, add it to that stage's
      `signal_scales` dict in `src/data/seed_content.py` AND every
      later stage at full or fade strength (soft fade preserves the
      previous signals at ~0.3-0.5 to prevent catastrophic forgetting)
- [ ] If the feature adds a new environment toggle, add a column to
      `curriculum_stages` and gate it in `editor/simulation/headless.py`
      `Simulation.__init__` and the runner in `editor/simulation/train.py`
- [ ] If the feature changes the action space, evaluate which stage
      should first reward use of the new action — add it to that
      stage's `signal_scales` for the relevant proxy signal
- [ ] Add a form field to `editor/training_curriculum_tab.py` if a
      new stage column was added
- [ ] Re-run `python data/seed_content.py` from `src/` after editing
      seed_content.py so the DB stages match

### 7.7 Review for loose ends again - incomplete features, features implied but not existing

### 8. Headless Tests
- [ ] Add or extend tests in `src/tests/test_mechanics.py` for the new feature
- [ ] Each new mechanic needs at least: happy path, rejection/failure case, edge case
- [ ] Run: `cd src && python -m tests.test_mechanics` — ALL tests must pass
- [ ] Tests must be pure Python (no pygame) — use Map, Tile, Creature, Item directly

### 9. Verification
- [ ] `py_compile` all modified files
- [ ] Run `src/tests/test_mechanics.py` — 0 failures
- [ ] Smoke test: editor constructs without error
- [ ] Smoke test: game launches without error (if runtime changes)
- [ ] Verify DB migration works on existing database
- [ ] Verify DB creates correctly from scratch (fresh file)

### 10. Commit
- [ ] commit code changes to current branch with a summary/comment of changes

## File Quick Reference

| Purpose | File(s) |
|---|---|
| Game entry | `src/main.py` |
| Editor entry | `editor.py` → `editor/app.py` |
| Map/Tile classes | `src/classes/maps.py` |
| Creature class | `src/classes/creature.py` |
| Stat enum + Stats class | `src/classes/stats.py` |
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
| ERDs (architecture diagrams) | `src/ERDs/` — see `master.md` for index |

## ERD Maintenance

Architecture diagrams live in `src/ERDs/` as Mermaid-in-Markdown files:

| ERD | Scope |
|---|---|
| `master.md` | High-level module map + links to all other ERDs |
| `class_hierarchy.md` | Inheritance tree, composition, behavior interface |
| `import_dependencies.md` | Top-level and deferred imports, circular dep chains |
| `data_flow.md` | Startup, game loop, save/load, sprite rendering pipeline |
| `stats_system.md` | Stat layers, derived formulas, opposing contests, leveling |

**When to update ERDs:**
- Adding a new class or changing inheritance → update `class_hierarchy.md`
- Adding a new module or changing imports → update `import_dependencies.md`
- Changing the game loop, save system, or rendering pipeline → update `data_flow.md`
- Changing stats, derived formulas, or contest mechanics → update `stats_system.md`
- Adding a new ERD scope → add the file and update `master.md` index

commit with comments frequently