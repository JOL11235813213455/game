"""
Benchmark: measure creature tick and observation costs at 10 and 100 creatures.
Run from project root:  cd src && python -m tests.bench_event_driven
"""
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent))

from classes.maps import Map, MapKey, Tile
from classes.creature import Creature
from classes.stats import Stat
from classes.relationship_graph import GRAPH
from classes.trackable import Trackable


def make_map(cols=50, rows=50):
    tiles = {}
    for x in range(cols):
        for y in range(rows):
            t = Tile(walkable=True)
            tiles[MapKey(x, y, 0)] = t
    return Map(tile_set=tiles, entrance=(0, 0), x_max=cols, y_max=rows)


def spawn_creatures(n, game_map):
    creatures = []
    for i in range(n):
        x = random.randint(0, game_map.x_max - 1)
        y = random.randint(0, game_map.y_max - 1)
        c = Creature(
            current_map=game_map,
            location=MapKey(x, y, 0),
            name=f'bench_{i}',
            species='human',
            stats={Stat.STR: 14, Stat.VIT: 12, Stat.AGL: 10,
                   Stat.PER: 12, Stat.INT: 10, Stat.CHR: 10, Stat.LCK: 10},
        )
        # Unregister behavior tick — we're not benchmarking NN inference
        c.unregister_tick('behavior')
        creatures.append(c)
    # Add some relationships between creatures
    for i, c in enumerate(creatures):
        for j in range(min(8, n)):
            if i != j:
                GRAPH.record_interaction(c.uid, creatures[j].uid,
                                         random.uniform(-15, 15))
    return creatures


def bench_process_ticks(creatures, steps=500):
    """Benchmark process_ticks (hunger, regen, water, spatial memory)."""
    start = time.perf_counter()
    for step in range(steps):
        now = step * 100
        for c in creatures:
            c.process_ticks(now)
    elapsed = time.perf_counter() - start
    return elapsed


def bench_observations(creatures, cols, rows, steps=100):
    """Benchmark full observation building."""
    from classes.observation import build_observation
    start = time.perf_counter()
    for step in range(steps):
        now = step * 500
        for c in creatures:
            c._perception_cache_tick = -1  # force fresh perception
            build_observation(c, cols, rows, observation_tick=now)
    elapsed = time.perf_counter() - start
    return elapsed


def bench_social_topology(creatures, steps=200):
    """Benchmark social topology computation in isolation."""
    from classes.social_topology import compute_social_topology
    start = time.perf_counter()
    for step in range(steps):
        for c in creatures:
            visible = [(abs(c.location.x - o.location.x) + abs(c.location.y - o.location.y), o)
                       for o in creatures if o is not c and o.is_alive]
            visible.sort(key=lambda x: x[0])
            visible = visible[:15]
            slots = [o for _, o in visible[:10]]
            compute_social_topology(c, visible, slots)
    elapsed = time.perf_counter() - start
    return elapsed


def bench_spatial_memory(creatures, steps=500):
    """Benchmark spatial memory scanning."""
    start = time.perf_counter()
    for step in range(steps):
        for c in creatures:
            c.update_spatial_memory(step)
    elapsed = time.perf_counter() - start
    return elapsed


def run_suite(n_creatures):
    random.seed(42)
    GRAPH.clear()
    # Clear any existing creatures
    Creature._uid_registry.clear()
    Trackable._next_uid = 1

    game_map = make_map(50, 50)
    creatures = spawn_creatures(n_creatures, game_map)

    print(f"\n{'='*60}")
    print(f"  Benchmark: {n_creatures} creatures on 50x50 map")
    print(f"{'='*60}")

    # Warm up
    for c in creatures:
        c.process_ticks(0)

    t = bench_process_ticks(creatures, steps=500)
    print(f"  process_ticks  (500 steps): {t:8.3f}s  ({t/500*1000:.1f}ms/step)")

    t = bench_spatial_memory(creatures, steps=500)
    print(f"  spatial_memory (500 steps): {t:8.3f}s  ({t/500*1000:.1f}ms/step)")

    t = bench_social_topology(creatures, steps=200)
    print(f"  social_topology(200 steps): {t:8.3f}s  ({t/200*1000:.1f}ms/step)")

    try:
        t = bench_observations(creatures, 50, 50, steps=50)
        print(f"  observations   ( 50 steps): {t:8.3f}s  ({t/50*1000:.1f}ms/step)")
    except Exception as e:
        print(f"  observations: SKIPPED ({e})")

    print()


if __name__ == '__main__':
    run_suite(10)
    run_suite(100)
