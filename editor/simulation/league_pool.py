"""
League training snapshot pool.

Maintains a rolling collection of past policy checkpoints (creature,
goal, monster, pack). Used during co-evolution stages (23-25) to sample
opponents from historical versions rather than training against the
currently-optimal opponent. This prevents strategy collapse where one
side learns a counter that beats the current opponent but fails against
older versions.

Interface is intentionally minimal — the training runner pulls snapshots
when building opponent pools for a rollout.
"""
from __future__ import annotations
from pathlib import Path
import json
import shutil
from datetime import datetime


class LeaguePool:
    """Rolling snapshot pool for league-style training."""

    def __init__(self, pool_dir: str = 'editor/models/league',
                 max_snapshots: int = 10):
        self.pool_dir = Path(pool_dir)
        self.pool_dir.mkdir(parents=True, exist_ok=True)
        self.max_snapshots = max_snapshots
        self.manifest_path = self.pool_dir / 'manifest.json'
        self._load_manifest()

    def _load_manifest(self):
        if self.manifest_path.exists():
            with open(self.manifest_path) as f:
                self.manifest = json.load(f)
        else:
            self.manifest = {'snapshots': []}

    def _save_manifest(self):
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)

    def add_snapshot(self, name: str, weights: dict[str, str],
                     stage: int = None, notes: str = ''):
        """Add a new snapshot entry.

        Args:
            name: human-readable snapshot identifier
            weights: {component: source_path} to copy into the pool
                (keys like 'creature', 'goal', 'monster', 'pack')
            stage: curriculum stage this snapshot represents
            notes: free-text notes
        """
        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        snap_id = f'{name}_{ts}'
        snap_dir = self.pool_dir / snap_id
        snap_dir.mkdir(exist_ok=True)

        copied: dict[str, str] = {}
        for component, src in weights.items():
            src_path = Path(src)
            if not src_path.exists():
                continue
            dst = snap_dir / f'{component}.npz'
            shutil.copy(src_path, dst)
            copied[component] = str(dst)

        entry = {
            'id': snap_id,
            'name': name,
            'stage': stage,
            'created_at': ts,
            'notes': notes,
            'weights': copied,
        }
        self.manifest['snapshots'].append(entry)

        # Trim to max_snapshots (FIFO)
        while len(self.manifest['snapshots']) > self.max_snapshots:
            old = self.manifest['snapshots'].pop(0)
            old_dir = self.pool_dir / old['id']
            if old_dir.exists():
                shutil.rmtree(old_dir)

        self._save_manifest()
        return entry

    def list_snapshots(self) -> list[dict]:
        return list(self.manifest.get('snapshots', []))

    def sample_snapshot(self, component: str = None,
                        rng=None) -> dict | None:
        """Randomly choose a snapshot. If component specified, restrict
        to snapshots that have weights for that component.
        """
        import random as _rng
        r = rng or _rng
        pool = self.manifest.get('snapshots', [])
        if component:
            pool = [s for s in pool if component in s.get('weights', {})]
        if not pool:
            return None
        return r.choice(pool)

    def latest_snapshot(self) -> dict | None:
        pool = self.manifest.get('snapshots', [])
        return pool[-1] if pool else None

    def clear(self):
        """Wipe the pool. Used for fresh starts."""
        for entry in self.manifest.get('snapshots', []):
            d = self.pool_dir / entry['id']
            if d.exists():
                shutil.rmtree(d)
        self.manifest = {'snapshots': []}
        self._save_manifest()
