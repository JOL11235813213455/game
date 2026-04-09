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

    # Tile gold/items summary (just non-empty tiles)
    tile_info = []
    for key, tile in sim.game_map.tiles.items():
        if tile.gold > 0 or tile.inventory.items:
            tile_info.append({
                'x': key.x, 'y': key.y,
                'gold': tile.gold,
                'items': len(tile.inventory.items),
                'template': tile.tile_template or 'grass',
            })

    state = {
        'timestamp': time.time(),
        'phase': phase,
        'step': step,
        'tick': sim.step_count,
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


def read_state() -> dict | None:
    """Read the latest state from the training process."""
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            # Stale check — if older than 5 seconds, training may have stopped
            if time.time() - data.get('timestamp', 0) > 5:
                data['stale'] = True
            return data
    except Exception:
        pass
    return None


def clear_state():
    """Remove the state file."""
    try:
        STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
