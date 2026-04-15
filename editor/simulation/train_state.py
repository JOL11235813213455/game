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

    # Sentiment matrix: capped to first 10 alive creatures (10x10 = 100 entries)
    from classes.relationship_graph import GRAPH
    alive_creatures = [c for c in sim.creatures if c.is_alive][:10]
    alive_uids = [c.uid for c in alive_creatures]
    sentiments = []
    sentiment_names = []
    for from_uid in alive_uids:
        row = []
        for to_uid in alive_uids:
            if from_uid == to_uid:
                row.append(0.0)
            else:
                edge = GRAPH.get_edge(from_uid, to_uid)
                row.append(round(edge[0], 1) if edge else 0.0)
        sentiments.append(row)
    for c in alive_creatures:
        sentiment_names.append((c.name or '')[:6])

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
        'sentiments': sentiments,
        'sentiment_names': sentiment_names,
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
