"""
Shared state between training process and viewer.

Training writes creature positions/stats to a JSON file each tick.
Viewer reads and renders. File-based IPC — simple and robust.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / 'models' / '_live_state.json'


def write_state(sim, phase: str = '', step: int = 0, info: dict = None):
    """Write current simulation state for the viewer to read."""
    from classes.stats import Stat

    creatures = []
    for c in sim.creatures:
        creatures.append({
            'uid': c.uid,
            'name': c.name or '',
            'species': c.species or '',
            'sex': c.sex,
            'x': c.location.x,
            'y': c.location.y,
            'alive': c.is_alive,
            'hp': c.stats.active[Stat.HP_CURR](),
            'hp_max': c.stats.active[Stat.HP_MAX](),
            'gold': c.gold,
            'items': len(c.inventory.items),
            'equip': len(c.equipment),
            'size': getattr(c, 'size', 'medium'),
            'deity': c.deity,
            'mask': c.observation_mask,
        })

    # Tile info: anything non-default goes in. The replay viewer uses
    # this to overlay liquid, purpose districts, resource tiles, and
    # loot indicators on top of the default grass fill.
    tile_info = []
    for key, tile in sim.game_map.tiles.items():
        tmpl = tile.tile_template or 'grass'
        liquid = getattr(tile, 'liquid', False)
        purpose = getattr(tile, 'purpose', None)
        resource_type = getattr(tile, 'resource_type', None)
        resource_amount = getattr(tile, 'resource_amount', 0) if resource_type else 0
        resource_max = getattr(tile, 'resource_max', 0) if resource_type else 0
        buried = getattr(tile, 'buried_gold', 0)
        has_stuff = (tile.gold > 0 or tile.inventory.items or liquid
                     or purpose or resource_type or buried > 20)
        if tmpl != 'grass' or has_stuff:
            tile_info.append({
                'x': key.x, 'y': key.y,
                'gold': tile.gold,
                'items': len(tile.inventory.items),
                'template': tmpl,
                'liquid': bool(liquid),
                'depth': int(getattr(tile, 'depth', 0) or 0),
                'purpose': purpose,
                'resource_type': resource_type,
                'resource_amount': int(resource_amount),
                'resource_max': int(resource_max),
                'buried_gold': int(buried),
            })

    _day = int(sim.game_clock.day)
    _hr = int(sim.game_clock.hour)
    _mn = int((sim.game_clock.hour % 1) * 60)

    state = {
        'timestamp': time.time(),
        'phase': phase,
        'step': step,
        'tick': sim.step_count,
        'clock': f'{_day:02d}:{_hr:02d}:{_mn:02d}',
        'cols': sim.cols,
        'rows': sim.rows,
        'alive': sim.alive_count,
        'total': len(sim.creatures),
        'creatures': creatures,
        'tile_info': tile_info,
        'info': info or {},
    }

    try:
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass  # non-critical — viewer just shows stale data


def write_parallel_state(worker_stats: list[dict], phase: str = '',
                         step: int = 0, info: dict = None):
    """Write parallel training state — per-worker stats, no tile grid.

    worker_stats: list of dicts, one per worker, with keys like
        avg_reward, alive, total, samples, worker_id
    """
    state = {
        'timestamp': time.time(),
        'phase': phase,
        'step': step,
        'tick': 0,
        'clock': '',
        'cols': 0, 'rows': 0,
        'alive': sum(w.get('alive', 0) for w in worker_stats),
        'total': sum(w.get('total', 0) for w in worker_stats),
        'creatures': [],
        'tile_info': [],
        'info': info or {},
        'parallel': True,
        'workers': worker_stats,
    }
    try:
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def read_worker_states() -> list[dict]:
    """Read per-worker live stat files."""
    import glob
    results = []
    for path in sorted(glob.glob(str(STATE_FILE.parent / '_live_worker_*.json'))):
        try:
            data = json.loads(Path(path).read_text())
            if time.time() - data.get('timestamp', 0) < 120:
                results.append(data)
        except Exception:
            pass
    return results


def read_state() -> dict | None:
    """Read the latest state from the training process."""
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            # Stale check — parallel mode takes longer between updates
            stale_limit = 120 if data.get('parallel') else 5
            if time.time() - data.get('timestamp', 0) > stale_limit:
                data['stale'] = True
            return data
    except Exception:
        pass
    return None


def write_es_state(generation: int, total_generations: int,
                   variant: int, total_variants: int,
                   best_reward: float = 0.0, avg_reward: float = 0.0,
                   info: dict = None):
    """Write ES phase progress for the viewer (no sim needed)."""
    state = {
        'timestamp': time.time(),
        'phase': 'ES',
        'step': generation * total_variants + variant,
        'tick': 0,
        'cols': 0,
        'rows': 0,
        'alive': 0,
        'total': 0,
        'creatures': [],
        'tile_info': [],
        'info': {
            'generation': generation + 1,
            'total_generations': total_generations,
            'variant': variant + 1,
            'total_variants': total_variants,
            'best_reward': round(best_reward, 2),
            'avg_reward': round(avg_reward, 2),
            **(info or {}),
        },
    }
    try:
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def clear_state():
    """Remove the state file."""
    try:
        STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
