"""
Training analytics database — separate from game.db.

Stores granular training data for analysis:
- Run summaries (Tier 1)
- Phase snapshots (Tier 2)
- Episode summaries (Tier 3)
- Per-creature episode stats (Tier 4)
- Observation/action schemas for named remapping

Lives at editor/training.db. Never shipped to users.
Can be ATTACHed to game.db for cross-queries.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'training.db'


def get_con() -> sqlite3.Connection:
    """Get a connection to the training DB, creating tables if needed."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')  # fast concurrent reads
    _ensure_schema(con)
    return con


def _ensure_schema(con: sqlite3.Connection):
    """Create tables if they don't exist."""
    con.executescript("""
    -- Observation/action layout schemas (deduped by hash)
    CREATE TABLE IF NOT EXISTS observation_schemas (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        version_hash TEXT UNIQUE NOT NULL,
        size         INTEGER NOT NULL,
        created_at   TEXT NOT NULL,
        layout       TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS action_schemas (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        version_hash TEXT UNIQUE NOT NULL,
        size         INTEGER NOT NULL,
        created_at   TEXT NOT NULL,
        layout       TEXT NOT NULL
    );

    -- Tier 1: Per-run summary
    CREATE TABLE IF NOT EXISTS training_runs (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        model_name       TEXT NOT NULL,
        model_version    INTEGER NOT NULL,
        parent_version   INTEGER,
        obs_schema_id    INTEGER REFERENCES observation_schemas(id),
        act_schema_id    INTEGER REFERENCES action_schemas(id),
        started_at       TEXT NOT NULL,
        finished_at      TEXT,
        total_seconds    REAL NOT NULL DEFAULT 0,
        training_params  TEXT NOT NULL DEFAULT '{}',
        -- Aggregate stats
        final_avg_reward   REAL,
        best_episode_reward REAL,
        worst_episode_reward REAL,
        total_episodes     INTEGER NOT NULL DEFAULT 0,
        total_steps        INTEGER NOT NULL DEFAULT 0,
        -- Entropy/loss at start vs end
        entropy_start    REAL,
        entropy_end      REAL,
        policy_loss_end  REAL,
        value_loss_end   REAL,
        notes            TEXT NOT NULL DEFAULT ''
    );

    -- Tier 2: Per-phase snapshot
    CREATE TABLE IF NOT EXISTS phase_snapshots (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id         INTEGER NOT NULL REFERENCES training_runs(id),
        phase          TEXT NOT NULL,
        cycle          INTEGER NOT NULL,
        step_start     INTEGER NOT NULL,
        step_end       INTEGER NOT NULL,
        duration_secs  REAL NOT NULL DEFAULT 0,
        -- Reward distribution
        reward_mean    REAL,
        reward_median  REAL,
        reward_std     REAL,
        reward_min     REAL,
        reward_max     REAL,
        reward_p10     REAL,
        reward_p90     REAL,
        -- Action usage
        action_distribution TEXT NOT NULL DEFAULT '{}',
        -- Training health
        entropy_mean   REAL,
        entropy_final  REAL,
        value_loss_mean REAL,
        explained_variance REAL,
        -- Population stats
        death_rate       REAL,
        avg_survival_steps REAL,
        episodes         INTEGER NOT NULL DEFAULT 0
    );

    -- Tier 3: Per-episode summary
    CREATE TABLE IF NOT EXISTS episode_summaries (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          INTEGER NOT NULL REFERENCES training_runs(id),
        phase           TEXT NOT NULL,
        cycle           INTEGER NOT NULL,
        episode_num     INTEGER NOT NULL,
        step_start      INTEGER NOT NULL,
        step_end        INTEGER NOT NULL,
        total_reward    REAL NOT NULL DEFAULT 0,
        alive_at_end    INTEGER NOT NULL DEFAULT 0,
        total_creatures INTEGER NOT NULL DEFAULT 0,
        arena_cols      INTEGER,
        arena_rows      INTEGER,
        -- Per-signal reward breakdown (JSON: signal_name -> total)
        reward_breakdown TEXT NOT NULL DEFAULT '{}'
    );

    -- Tier 4: Per-creature per-episode
    CREATE TABLE IF NOT EXISTS creature_episodes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id      INTEGER NOT NULL REFERENCES episode_summaries(id),
        creature_uid    INTEGER NOT NULL,
        creature_name   TEXT,
        species         TEXT,
        sex             TEXT,
        profile         TEXT,
        observation_mask TEXT,
        -- Outcomes
        survived        INTEGER NOT NULL DEFAULT 1,
        survival_steps  INTEGER NOT NULL DEFAULT 0,
        total_reward    REAL NOT NULL DEFAULT 0,
        -- Reward by signal (JSON: signal_name -> total)
        reward_breakdown TEXT NOT NULL DEFAULT '{}',
        -- Action histogram (JSON: action_name -> count)
        action_counts   TEXT NOT NULL DEFAULT '{}',
        -- Final state
        final_hp_ratio  REAL,
        final_gold      INTEGER,
        final_items     INTEGER,
        final_equipment INTEGER,
        final_allies    INTEGER,
        final_enemies   INTEGER,
        kills           INTEGER NOT NULL DEFAULT 0,
        tiles_explored  INTEGER NOT NULL DEFAULT 0,
        creatures_met   INTEGER NOT NULL DEFAULT 0,
        trades_made     INTEGER NOT NULL DEFAULT 0,
        gold_earned     REAL NOT NULL DEFAULT 0,
        gold_spent      REAL NOT NULL DEFAULT 0,
        -- Stats profile
        base_stats      TEXT NOT NULL DEFAULT '{}'
    );

    -- Tier 5: Sampled time-series (periodic, not every tick)
    CREATE TABLE IF NOT EXISTS step_samples (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       INTEGER NOT NULL REFERENCES training_runs(id),
        phase        TEXT NOT NULL,
        global_step  INTEGER NOT NULL,
        creature_uid INTEGER,
        action       INTEGER,
        reward       REAL,
        -- Top action probs (JSON: action -> probability)
        top_probs    TEXT,
        value_estimate REAL,
        entropy      REAL
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_runs_model ON training_runs(model_name, model_version);
    CREATE INDEX IF NOT EXISTS idx_phases_run ON phase_snapshots(run_id);
    CREATE INDEX IF NOT EXISTS idx_episodes_run ON episode_summaries(run_id, phase);
    CREATE INDEX IF NOT EXISTS idx_creatures_episode ON creature_episodes(episode_id);
    CREATE INDEX IF NOT EXISTS idx_samples_run ON step_samples(run_id, global_step);
    """)
    con.commit()


# ---------------------------------------------------------------------------
# Schema generation — auto-generates from live code
# ---------------------------------------------------------------------------

def generate_observation_schema() -> list[dict]:
    """Generate the current observation layout from SECTION_RANGES.

    Each entry: {pos, name, section, transform}
    This is a section-level schema, not per-float — sections are the
    unit of remapping since individual floats within a section are
    tightly coupled.
    """
    from classes.observation import SECTION_RANGES, OBSERVATION_SIZE

    layout = []
    for section_name, (start, end) in sorted(SECTION_RANGES.items(), key=lambda x: x[1][0]):
        layout.append({
            'section': section_name,
            'start': start,
            'end': end,
            'size': end - start,
        })

    return layout


def generate_action_schema() -> list[dict]:
    """Generate the current action layout from the Action enum."""
    from classes.actions import Action

    layout = []
    # Group actions by prefix
    groups = {
        'movement': range(0, 8),
        'run': range(8, 16),
        'sneak': range(16, 24),
        'combat': [24, 25, 26, 27],
        'social': [28, 29, 30, 31, 32, 33, 34],
        'utility': [35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45],
        'stances': [46, 47, 48],
    }

    # Invert: action_idx -> group
    idx_to_group = {}
    for group, indices in groups.items():
        for idx in indices:
            idx_to_group[idx] = group

    for act in Action:
        layout.append({
            'index': act.value,
            'name': act.name.lower(),
            'group': idx_to_group.get(act.value, 'unknown'),
        })

    return layout


def save_schema(schema_type: str, layout: list[dict], size: int) -> int:
    """Save a schema to the DB, deduplicating by content hash.

    Args:
        schema_type: 'observation' or 'action'
        layout: the schema layout list
        size: total vector size

    Returns:
        schema ID
    """
    layout_json = json.dumps(layout, sort_keys=True)
    version_hash = hashlib.sha256(layout_json.encode()).hexdigest()[:16]

    table = f'{schema_type}_schemas'
    con = get_con()
    row = con.execute(f'SELECT id FROM {table} WHERE version_hash = ?',
                      (version_hash,)).fetchone()
    if row:
        con.close()
        return row['id']

    from datetime import datetime
    con.execute(f'INSERT INTO {table} (version_hash, size, created_at, layout) '
                f'VALUES (?, ?, ?, ?)',
                (version_hash, size, datetime.utcnow().isoformat(sep=' ', timespec='seconds'),
                 layout_json))
    con.commit()
    schema_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    con.close()
    return schema_id


def get_schema(schema_type: str, schema_id: int) -> tuple[list[dict], int]:
    """Load a schema by ID. Returns (layout, size)."""
    table = f'{schema_type}_schemas'
    con = get_con()
    row = con.execute(f'SELECT layout, size FROM {table} WHERE id = ?',
                      (schema_id,)).fetchone()
    con.close()
    if row is None:
        raise ValueError(f'{schema_type} schema {schema_id} not found')
    return json.loads(row['layout']), row['size']


def diff_schemas(old_layout: list[dict], new_layout: list[dict],
                 key: str = 'section') -> dict:
    """Compare two schemas and return mapping info.

    Returns:
        {
            'added': [entries in new but not old],
            'removed': [entries in old but not new],
            'moved': {name: (old_start, new_start)},
            'unchanged': [names present in both at same position],
        }
    """
    old_by_name = {e[key]: e for e in old_layout}
    new_by_name = {e[key]: e for e in new_layout}

    old_names = set(old_by_name.keys())
    new_names = set(new_by_name.keys())

    added = [new_by_name[n] for n in new_names - old_names]
    removed = [old_by_name[n] for n in old_names - new_names]

    moved = {}
    unchanged = []
    for name in old_names & new_names:
        old_start = old_by_name[name]['start']
        new_start = new_by_name[name]['start']
        if old_start != new_start:
            moved[name] = (old_start, new_start)
        else:
            unchanged.append(name)

    return {
        'added': added,
        'removed': removed,
        'moved': moved,
        'unchanged': unchanged,
    }
