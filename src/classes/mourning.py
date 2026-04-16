"""
Mourning / grief system.

When a creature dies, survivors with a positive relationship can
experience grief. Awareness is gated:

  1. SIGHT WITNESSES — creatures who can_see the death tile at the
     moment it happens. They acquire the death knowledge instantly.
  2. RUMOR LISTENERS — creatures told about the death by a witness
     (or rumor-carrier) via TALK. Magnitude attenuated by the carried
     confidence (confidence * 0.6 per hop, same as territory rumors).
  3. FALLBACK REACH — after FALLBACK_REACH_DAYS game days, any
     still-ignorant bonded survivor finally finds out at reduced
     confidence (0.3). Keeps the training signal non-sparse for
     isolated creatures.

Once knowledge is acquired, the actual stat debuffs fire after a
FINISH_FIGHT_DELAY_MS grace window (default 2 game hours). This lets
a survivor complete the fight that killed their loved one before the
bereavement effects kick in. The reward signal fires on knowledge
acquisition (not on debuff application) so the NN sees the penalty
immediately — we're just sparing the creature's stats for the duration
of the fight.

Grief magnitude (shared across all acquisition paths):

  base_magnitude = sentiment * ln(count + 1)
  effective      = base_magnitude * confidence

Confidence defaults:
  sight witness:   1.0
  rumor listener:  varies (0.6 per hop)
  fallback reach:  0.3

Spec: memory/project_mourning_system.md
"""
from __future__ import annotations
import math
from classes.stats import Stat
from classes.relationship_graph import GRAPH


# Grief magnitude thresholds that gate stat-mod tiers.
# (magnitude_floor, duration_game_days, str_mod, chr_mod, per_mod, agl_mod)
GRIEF_TIERS = [
    (2.0,   1, 0, -1, 0, 0),
    (8.0,   2, -1, -2, -1, 0),
    (20.0,  4, -2, -3, -1, -1),
    (50.0,  7, -3, -5, -2, -1),
]

GAME_DAY_TICKS = 1440            # 1 tick = 500ms = 1 game minute → 1440 min/day
GAME_HOUR_TICKS = 60             # 60 game minutes per game hour
FINISH_FIGHT_DELAY_MS = 2 * GAME_HOUR_TICKS * 500  # 2 game hours = 60_000 ms

# Fallback: a bonded survivor who never sees the death or hears a
# rumor will still grieve after this many game days — at reduced
# confidence so the grief is muted.
FALLBACK_REACH_DAYS = 3
FALLBACK_REACH_MS = FALLBACK_REACH_DAYS * GAME_DAY_TICKS * 500
FALLBACK_CONFIDENCE = 0.3


# -----------------------------------------------------------------------
# Magnitude + tier math
# -----------------------------------------------------------------------

def _base_magnitude(griever, dead_uid: int) -> float:
    rel = GRAPH.get_edge(griever.uid, dead_uid)
    if rel is None:
        return 0.0
    sentiment = rel[0]
    count = rel[1]
    if sentiment <= 0:
        return 0.0
    return sentiment * math.log(count + 1)


def _pick_tier(magnitude: float) -> tuple | None:
    chosen = None
    for tier in GRIEF_TIERS:
        if magnitude >= tier[0]:
            chosen = tier
    if chosen is None:
        return None
    return chosen[1:]


def _effective_magnitude(griever, dead_uid: int, confidence: float) -> float:
    return _base_magnitude(griever, dead_uid) * max(0.0, min(1.0, confidence))


# -----------------------------------------------------------------------
# Awareness tracking
# -----------------------------------------------------------------------

def _mark_aware(griever, dead_uid: int, source: str, confidence: float,
                now: int):
    """Record that griever knows about dead_uid's death. Idempotent on
    (griever, dead_uid). Higher-confidence knowledge wins.
    """
    known = getattr(griever, '_known_deaths', None)
    if known is None:
        known = {}
        griever._known_deaths = known
    prev = known.get(dead_uid)
    if prev is not None and prev['confidence'] >= confidence:
        return False
    known[dead_uid] = {
        'source': source,
        'confidence': confidence,
        'learned_at': now,
    }
    return True


def is_aware(griever, dead_uid: int) -> bool:
    known = getattr(griever, '_known_deaths', None)
    return known is not None and dead_uid in known


# -----------------------------------------------------------------------
# Core grief application (acquisition path)
# -----------------------------------------------------------------------

def _apply_grief_knowledge(griever, dead_creature, confidence: float,
                            now: int, source: str) -> bool:
    """Acquire knowledge of a death and schedule debuffs to fire after
    a grace window. The reward signal fires immediately via updated
    counters; the stat debuffs apply after FINISH_FIGHT_DELAY_MS.
    """
    if not _mark_aware(griever, dead_creature.uid, source, confidence, now):
        return False

    magnitude = _effective_magnitude(griever, dead_creature.uid, confidence)
    if magnitude <= 0:
        return False

    tier = _pick_tier(magnitude)
    if tier is None:
        return False

    # Record reward-facing counters immediately. The NN sees the grief
    # penalty the tick the death is learned — we just spare the
    # creature's physical stats for the fight.
    griever._grief_events_total = getattr(griever, '_grief_events_total', 0) + 1
    griever._grief_magnitude_sum = getattr(griever, '_grief_magnitude_sum',
                                           0.0) + magnitude

    # Remember death location if known
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
        while len(gl) > 10:
            gl.pop(0)

    # Schedule delayed application of stat mods after the finish-fight
    # grace window. _apply_grief_debuffs handles replacing any prior
    # debuff for this death (in case a higher-confidence learning
    # arrives before the delay expires).
    tick_name = f'grief_apply_{dead_creature.uid}'
    mod_source = f'grief_{dead_creature.uid}'

    def _apply_then_schedule_expire(_now,
                                     cr=griever,
                                     dc=dead_creature,
                                     tier_info=tier,
                                     src=mod_source,
                                     tname=tick_name):
        _install_debuffs(cr, tier_info, src)
        cr.unregister_tick(tname)
        # Schedule auto-expiry after duration_days
        duration_days = tier_info[0]
        duration_ms = int(duration_days * GAME_DAY_TICKS * 500)
        expire_name = f'grief_expire_{dc.uid}'

        def _expire(_n, c=cr, s=src, en=expire_name):
            c.stats.remove_mods_by_source(s)
            c.unregister_tick(en)

        cr.register_tick(expire_name, duration_ms, _expire)

    griever.register_tick(tick_name, FINISH_FIGHT_DELAY_MS,
                           _apply_then_schedule_expire)
    return True


def _install_debuffs(griever, tier: tuple, source: str):
    """Actually install the stat mods for a grief event."""
    duration_days, str_mod, chr_mod, per_mod, agl_mod = tier
    griever.stats.remove_mods_by_source(source)
    if str_mod:
        griever.stats.add_mod(source, Stat.STR, str_mod)
    if chr_mod:
        griever.stats.add_mod(source, Stat.CHR, chr_mod)
    if per_mod:
        griever.stats.add_mod(source, Stat.PER, per_mod)
    if agl_mod:
        griever.stats.add_mod(source, Stat.AGL, agl_mod)


# -----------------------------------------------------------------------
# Death event entry point
# -----------------------------------------------------------------------

def notify_death(dead_creature, now: int = 0):
    """Fire a death event. Only sight witnesses learn immediately.

    Non-witnesses get a pending-death rumor entry that can be spread
    via TALK (share_death_news) or eventually closed by the fallback
    reach tick.

    Must be called BEFORE Creature.die() tears down the graph.

    Idempotent: second call for the same creature is a no-op via the
    ``_mourning_fired`` flag. This lets both the lifecycle.dead event
    handler AND the direct die() path call it safely — whichever
    arrives first wins; the other is a silent no-op.
    """
    from classes.creature import Creature

    if getattr(dead_creature, '_mourning_fired', False):
        return
    dead_creature._mourning_fired = True

    dead_uid = dead_creature.uid
    death_map = getattr(dead_creature.current_map, 'name', '') or ''
    death_loc = (death_map, dead_creature.location.x, dead_creature.location.y)

    # Record a global death event that rumor-carriers can propagate.
    # Tracked under the RelationshipGraph so save/load persists it.
    event = _record_death_event(dead_creature, now)

    witnesses = 0
    bonded_listeners = []

    for griever_uid, rel in GRAPH.edges_to(dead_uid):
        if rel is None or rel[0] <= 0:
            continue
        griever = Creature.by_uid(griever_uid)
        if griever is None or not griever.is_alive:
            continue
        bonded_listeners.append(griever)

        # Sight witness?
        if _can_witness(griever, dead_creature):
            # Sight witness — learn immediately at full confidence
            if _apply_grief_knowledge(griever, dead_creature,
                                       confidence=1.0, now=now,
                                       source='witness'):
                witnesses += 1
                # Witnesses automatically carry the rumor at full fidelity
                _carry_rumor(griever, dead_uid, event, confidence=1.0,
                             tick=now)

    # Schedule fallback reach for any bonded listener who hasn't learned
    # yet after FALLBACK_REACH_DAYS.
    for griever in bonded_listeners:
        if not is_aware(griever, dead_uid):
            _schedule_fallback_reach(griever, dead_creature, event, now)

    return witnesses


def _can_witness(griever, dead_creature) -> bool:
    """True if the griever is on the same map, within sight, and the
    sprite geometry is not blocked by cover differences. Uses the
    existing can_see implementation to keep semantics consistent.
    """
    if griever.current_map is not dead_creature.current_map:
        return False
    if griever.current_map is None:
        return False
    try:
        return griever.can_see(dead_creature)
    except Exception:
        # Fall back to a plain range check
        d = abs(griever.location.x - dead_creature.location.x) + \
            abs(griever.location.y - dead_creature.location.y)
        sight = griever.stats.active[Stat.SIGHT_RANGE]()
        return d <= sight


# -----------------------------------------------------------------------
# Death-event storage on the relationship graph
# -----------------------------------------------------------------------

def _record_death_event(dead_creature, now: int) -> dict:
    """Store a compact death event on the graph so rumor carriers can
    reference it. Keyed by dead_uid. Overwrites any prior entry.
    """
    events = getattr(GRAPH, '_death_events', None)
    if events is None:
        events = {}
        GRAPH._death_events = events
    entry = {
        'dead_uid': dead_creature.uid,
        'species': dead_creature.species,
        'name': dead_creature.name or f'#{dead_creature.uid}',
        'map_name': getattr(dead_creature.current_map, 'name', '') or '',
        'x': dead_creature.location.x,
        'y': dead_creature.location.y,
        'tick': now,
    }
    events[dead_creature.uid] = entry
    return entry


def get_death_event(dead_uid: int) -> dict | None:
    events = getattr(GRAPH, '_death_events', None)
    if events is None:
        return None
    return events.get(dead_uid)


def _carry_rumor(carrier, dead_uid: int, event: dict, confidence: float,
                 tick: int):
    """Mark that a creature carries a death rumor (to be shared later)."""
    carried = getattr(carrier, '_death_rumors_held', None)
    if carried is None:
        carried = {}
        carrier._death_rumors_held = carried
    prev = carried.get(dead_uid)
    if prev is not None and prev['confidence'] >= confidence:
        return
    carried[dead_uid] = {
        'event': event,
        'confidence': confidence,
        'tick': tick,
    }


# -----------------------------------------------------------------------
# Rumor propagation via TALK
# -----------------------------------------------------------------------

RUMOR_DECAY_PER_HOP = 0.6
RUMOR_MIN_CONFIDENCE = 0.05


def share_death_news(teller, listener, tick: int) -> bool:
    """Teller shares a death rumor with listener.

    Picks the teller's most-confident death rumor the listener doesn't
    already know with equal-or-better fidelity. Applies confidence
    decay. If the listener has positive sentiment toward the deceased,
    triggers grief acquisition.

    Returns True if a rumor was transmitted.
    """
    carried = getattr(teller, '_death_rumors_held', None)
    if not carried:
        return False

    # Best candidate: highest confidence we can actually give the listener
    best = None
    best_conf = -1.0
    for dead_uid, entry in carried.items():
        new_conf = entry['confidence'] * RUMOR_DECAY_PER_HOP
        if new_conf < RUMOR_MIN_CONFIDENCE:
            continue
        listener_known = getattr(listener, '_known_deaths', {}) or {}
        if dead_uid in listener_known:
            if listener_known[dead_uid]['confidence'] >= new_conf:
                continue
        if new_conf > best_conf:
            best_conf = new_conf
            best = (dead_uid, entry, new_conf)

    if best is None:
        return False

    dead_uid, entry, new_conf = best
    # Acquire knowledge on the listener. Use a synthetic "ghost" dead
    # creature reference: we fetch the event dict for map/loc.
    dead_event = entry['event']

    # Build a minimal stand-in that _apply_grief_knowledge can use
    class _DeadRef:
        pass

    _ref = _DeadRef()
    _ref.uid = dead_uid
    _ref.species = dead_event.get('species')
    _ref.name = dead_event.get('name')
    _ref.current_map = teller.current_map  # best guess — for location recording

    class _Loc:
        pass
    loc = _Loc()
    loc.x = dead_event.get('x', 0)
    loc.y = dead_event.get('y', 0)
    _ref.location = loc

    transmitted = _apply_grief_knowledge(listener, _ref,
                                          confidence=new_conf,
                                          now=tick,
                                          source=f'rumor_from_{teller.uid}')

    # Listener now carries the rumor at the new (decayed) confidence
    _carry_rumor(listener, dead_uid, entry['event'], new_conf, tick)
    return transmitted


# -----------------------------------------------------------------------
# Fallback reach — isolated survivors eventually find out
# -----------------------------------------------------------------------

def _schedule_fallback_reach(griever, dead_creature, event, now: int):
    """Schedule an eventual 'word gets around' event for this griever."""
    tick_name = f'grief_fallback_{dead_creature.uid}'

    def _fallback(_now, cr=griever, dc=dead_creature, ev=event,
                  tn=tick_name):
        # Skip if the griever already learned by sight or rumor
        if not is_aware(cr, dc.uid):
            _apply_grief_knowledge(cr, dc,
                                    confidence=FALLBACK_CONFIDENCE,
                                    now=_now,
                                    source='fallback_reach')
        cr.unregister_tick(tn)

    griever.register_tick(tick_name, FALLBACK_REACH_MS, _fallback)


# -----------------------------------------------------------------------
# Snapshot + cleanup helpers
# -----------------------------------------------------------------------

def make_grief_snapshot(creature) -> dict:
    return {
        'grief_events_total': getattr(creature, '_grief_events_total', 0),
        'grief_magnitude_sum': getattr(creature, '_grief_magnitude_sum', 0.0),
    }


def clear_grief(creature):
    """Clean up all active grief mods + schedules. Used on load/teardown."""
    for tick_name in list(creature._timed_events.keys()):
        if (tick_name.startswith('grief_expire_')
                or tick_name.startswith('grief_apply_')
                or tick_name.startswith('grief_fallback_')):
            creature.unregister_tick(tick_name)
    for mod in list(creature.stats.mods):
        if mod['source'].startswith('grief_'):
            creature.stats.remove_mods_by_source(mod['source'])


# -----------------------------------------------------------------------
# Lifecycle event integration (Phase 2 FSM wire-up)
# -----------------------------------------------------------------------

def register_mourning_handlers(sim):
    """Subscribe mourning to lifecycle events on the given Simulation.

    After this, ``lifecycle.dead`` events automatically route through
    ``notify_death``. The direct die() call path still calls
    notify_death as a fallback for creatures that bypass the dying
    window — notify_death is idempotent via ``_mourning_fired``.

    Called once per Simulation construction (see Simulation.__init__).
    """
    def _on_lifecycle_dead(payload):
        # Payload: (uid, old_state, new_state, creature_ref)
        if len(payload) < 4:
            return
        _uid, _old, _new, creature = payload
        now = getattr(sim, 'now', 0)
        try:
            notify_death(creature, now=now)
        except Exception:
            pass

    def _on_lifecycle_dying(payload):
        # Optional hook for "allies react to imminent death" behavior.
        # Currently no-op — the 3-second window already lets allies
        # heal via their normal policy, no special distress state yet.
        # Subscribers wanting early-warning grief can plug in here.
        return

    sim.subscribe_event('lifecycle.dead', _on_lifecycle_dead)
    sim.subscribe_event('lifecycle.dying', _on_lifecycle_dying)
