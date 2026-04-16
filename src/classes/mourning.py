"""
Mourning / grief system.

When a creature dies, survivors with a positive relationship experience
grief. Grief applies temporary stat debuffs (reduced CHR, STR, PER)
scaled by the strength of the bond, and fires a reward signal that
teaches the NN to protect allies instead of just accumulating kills.

Entry point: `notify_death(dead_creature)` — called from Creature.die()
before the relationship graph is torn down.

Spec: memory/project_mourning_system.md.
"""
from __future__ import annotations
import math
from classes.stats import Stat
from classes.relationship_graph import GRAPH


# Grief magnitude thresholds that gate stat-mod tiers.
# Magnitude = sentiment * ln(count + 1) across the edge the GRIEVER holds
# for the dead creature. Positive sentiment only (no grief over enemies).

GRIEF_TIERS = [
    # (magnitude_floor, duration_game_days, str_mod, chr_mod, per_mod, agl_mod)
    (2.0,   1, 0, -1, 0, 0),   # mild — brief sadness
    (8.0,   2, -1, -2, -1, 0), # notable — noticeable distraction
    (20.0,  4, -2, -3, -1, -1),# deep — full bereavement
    (50.0,  7, -3, -5, -2, -1),# profound — loss of a partner/kin
]

# Ticks per game day (1 tick = 500ms = 1 game minute -> 1440 ticks/day)
GAME_DAY_TICKS = 1440


def _grief_magnitude(griever, dead_uid: int) -> float:
    """Compute how much grief the griever feels for a death.

    Uses the griever's forward edge toward the dead creature:
      magnitude = sentiment * ln(count + 1)
    Only positive relationships produce grief. Enemies produce zero.
    """
    rel = GRAPH.get_edge(griever.uid, dead_uid)
    if rel is None:
        return 0.0
    sentiment = rel[0]
    count = rel[1]
    if sentiment <= 0:
        return 0.0
    return sentiment * math.log(count + 1)


def _pick_tier(magnitude: float) -> tuple | None:
    """Return (duration_days, str_mod, chr_mod, per_mod, agl_mod) or None."""
    chosen = None
    for tier in GRIEF_TIERS:
        if magnitude >= tier[0]:
            chosen = tier
    if chosen is None:
        return None
    return chosen[1:]


def apply_grief(griever, dead_creature, magnitude: float, now: int):
    """Apply grief stat mods + schedule expiry."""
    tier = _pick_tier(magnitude)
    if tier is None:
        return False
    duration_days, str_mod, chr_mod, per_mod, agl_mod = tier

    source = f'grief_{dead_creature.uid}'
    # Replace any prior grief for this specific death with the new tier
    griever.stats.remove_mods_by_source(source)

    if str_mod:
        griever.stats.add_mod(source, Stat.STR, str_mod)
    if chr_mod:
        griever.stats.add_mod(source, Stat.CHR, chr_mod)
    if per_mod:
        griever.stats.add_mod(source, Stat.PER, per_mod)
    if agl_mod:
        griever.stats.add_mod(source, Stat.AGL, agl_mod)

    # Spatial echo: remember where this loved one died so goal systems
    # / future funeral behavior can return here
    gl = getattr(griever, '_grief_death_locations', None)
    if gl is None:
        gl = []
        griever._grief_death_locations = gl
    if dead_creature.current_map is not None:
        map_name = getattr(dead_creature.current_map, 'name', '') or ''
        gl.append((map_name,
                   dead_creature.location.x,
                   dead_creature.location.y,
                   now, magnitude))
        # Cap list size
        while len(gl) > 10:
            gl.pop(0)

    # Reward/counter for NN: increment once per new grief event
    griever._grief_events_total = getattr(griever, '_grief_events_total', 0) + 1
    griever._grief_magnitude_sum = getattr(griever, '_grief_magnitude_sum',
                                           0.0) + magnitude

    # Schedule one-shot expiry tick to remove the stat mods
    duration_ms = int(duration_days * GAME_DAY_TICKS * 500)  # 500 ms/tick
    tick_name = f'grief_expire_{dead_creature.uid}'

    def _expire(_now, src=source, tn=tick_name, cr=griever):
        cr.stats.remove_mods_by_source(src)
        cr.unregister_tick(tn)

    # Trackable.register_tick fires every `interval_ms`; make the first
    # firing happen after duration_ms and have the callback unregister.
    griever.register_tick(tick_name, duration_ms, _expire)
    return True


def notify_death(dead_creature, now: int = 0):
    """Broadcast death to everyone with a sentiment edge toward the deceased.

    Walks the RelationshipGraph's incoming edges (i.e. creatures who
    have an opinion about the dead creature) and applies grief for
    each positive relationship. Negative-sentiment edges are ignored
    (dying enemies produce no grief).

    Must be called BEFORE `GRAPH.remove_creature(dead_uid)` if the
    graph is being cleaned up on death — otherwise the walk finds
    nothing.
    """
    from classes.creature import Creature
    dead_uid = dead_creature.uid
    affected = 0
    for griever_uid, rel in GRAPH.edges_to(dead_uid):
        if rel is None or rel[0] <= 0:
            continue
        griever = Creature.by_uid(griever_uid)
        if griever is None or not griever.is_alive:
            continue
        magnitude = _grief_magnitude(griever, dead_uid)
        if magnitude <= 0:
            continue
        if apply_grief(griever, dead_creature, magnitude, now):
            affected += 1
    return affected


def make_grief_snapshot(creature) -> dict:
    """Capture grief state for reward-delta computation."""
    return {
        'grief_events_total': getattr(creature, '_grief_events_total', 0),
        'grief_magnitude_sum': getattr(creature, '_grief_magnitude_sum', 0.0),
    }


def clear_grief(creature):
    """Clean up all active grief mods + schedules. Used on load / teardown."""
    for tick_name in list(creature._timed_events.keys()):
        if tick_name.startswith('grief_expire_'):
            creature.unregister_tick(tick_name)
    for mod in list(creature.stats.mods):
        if mod['source'].startswith('grief_'):
            creature.stats.remove_mods_by_source(mod['source'])
