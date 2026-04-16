"""
Pack — monster coordination layer.

Every monster belongs to exactly one Pack (solitary species = pack of 1).
The Pack owns:
  - Territory (center + effective size, computed from species params)
  - Dominance hierarchy (separate M/F rankings)
  - Shared perception (creature sightings contributed by all members)
  - Pack NN signals (sleep, alert, cohesion, roles) broadcast to members

Pack runs event-driven: monsters push state changes (sighting, hp drop,
position move) into the shared dict; Pack NN fires on its own slow
cadence (~1-2s) to emit directives only when outputs actually change.

Full spec: memory/project_pack_class.md.
"""
from __future__ import annotations
import math
from classes.trackable import Trackable
from classes.maps import MapKey


class Pack(Trackable):
    """Coordination object for a group of monsters.

    A Pack is a Trackable so it survives save/load via the pickle sweep.
    """

    def __init__(self, species: str, territory_center: MapKey,
                 game_map=None):
        super().__init__()
        self.species = species
        self.territory_center: MapKey = territory_center
        self.game_map = game_map

        # Members split by sex for dominance tracking
        self.members_m: list[int] = []   # UIDs, ordered by rank (alpha first)
        self.members_f: list[int] = []

        # Shared perception — creature UIDs seen by any member, with
        # last-known position. Updated via event-driven calls.
        self.seen_creatures: dict[int, tuple[int, int, int]] = {}  # uid → (x, y, tick)

        # Event-driven state accumulator: keyed by monster UID, holds
        # latest values the Pack NN will consume when it fires.
        self.member_state: dict[int, dict] = {}

        # Pack NN output state (latched; broadcast only on change)
        self.sleep_signal: float = 0.0
        self.alert_level: float = 0.0
        self.cohesion: float = 0.5
        self.role_fractions: dict[str, float] = {'patrol': 1.0}

        # Split-triggered HP tracker (see split())
        self.split_start_hp_a: int = 0
        self.split_start_hp_b: int = 0

        # Phase 4 FSM: pack coordination state. Built lazily via
        # _ensure_state_fsm(). Transitions are heuristic (member
        # count, threat detection, resource scarcity). PackNet
        # reads the state as context and chooses actions within it.
        self._state_fsm = None
        self._pack_state_tick_at = 0   # last state-evaluation tick
        self._pack_formed_at = 0       # entry time for forming → territorial timer

    # ------------------------------------------------------------------
    # Species config access (cached from DB on first use)
    # ------------------------------------------------------------------

    @property
    def species_config(self) -> dict:
        from data.db import MONSTER_SPECIES
        return MONSTER_SPECIES.get(self.species, {})

    @property
    def split_size(self) -> int:
        return int(self.species_config.get('split_size', 4))

    @property
    def territory_size_max(self) -> float:
        return float(self.species_config.get('territory_size', 8.0))

    @property
    def territory_scales(self) -> bool:
        return bool(self.species_config.get('territory_scales', True))

    @property
    def dominance_type(self) -> str:
        return self.species_config.get('dominance_type', 'contest')

    @property
    def collapse_on_alpha_death(self) -> bool:
        return bool(self.species_config.get('collapse_on_alpha_death', False))

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self.members_m) + len(self.members_f)

    @property
    def members(self) -> list:
        """Return all living Monster instances in the pack."""
        from classes.monster import Monster
        result = []
        for uid in self.members_m + self.members_f:
            m = Monster.by_uid(uid)
            if m is not None:
                result.append(m)
        return result

    @property
    def alpha_male(self):
        from classes.monster import Monster
        if not self.members_m:
            return None
        return Monster.by_uid(self.members_m[0])

    @property
    def alpha_female(self):
        from classes.monster import Monster
        if not self.members_f:
            return None
        return Monster.by_uid(self.members_f[0])

    def add_member(self, monster):
        """Register a monster in this pack. Auto-rank by current stats."""
        if monster.sex == 'male':
            bucket = self.members_m
        else:
            bucket = self.members_f
        if monster.uid in bucket:
            return
        bucket.append(monster.uid)
        monster.pack = self
        self._rerank(bucket)
        self._update_alpha_flags()

    def remove_member(self, monster):
        """Unregister. Triggers alpha-death handling if applicable."""
        was_alpha = monster.is_alpha
        for bucket in (self.members_m, self.members_f):
            if monster.uid in bucket:
                bucket.remove(monster.uid)
        self.member_state.pop(monster.uid, None)
        monster.is_alpha = False

        if was_alpha and self.collapse_on_alpha_death:
            self._collapse()
            return

        # Rerank and update flags
        if monster.sex == 'male':
            self._rerank(self.members_m)
        else:
            self._rerank(self.members_f)
        self._update_alpha_flags()

    def _rerank(self, bucket: list[int]):
        """Sort bucket by dominance score (stat composite)."""
        from classes.monster import Monster
        from classes.stats import Stat

        def score(uid):
            m = Monster.by_uid(uid)
            if m is None:
                return -1
            return (m.stats.base.get(Stat.STR, 10) +
                    m.stats.base.get(Stat.VIT, 10) +
                    m.stats.base.get(Stat.AGL, 10))

        bucket.sort(key=score, reverse=True)

    def _update_alpha_flags(self):
        from classes.monster import Monster
        # Reset all
        for uid in self.members_m + self.members_f:
            m = Monster.by_uid(uid)
            if m is not None:
                m.is_alpha = False
        # Set top of each sex as alpha
        if self.members_m:
            alpha = Monster.by_uid(self.members_m[0])
            if alpha is not None:
                alpha.is_alpha = True
        if self.members_f:
            alpha = Monster.by_uid(self.members_f[0])
            if alpha is not None:
                alpha.is_alpha = True
        # Sync rank numbers onto monsters
        for rank, uid in enumerate(self.members_m):
            m = Monster.by_uid(uid)
            if m is not None:
                m.rank = rank
        for rank, uid in enumerate(self.members_f):
            m = Monster.by_uid(uid)
            if m is not None:
                m.rank = rank

    def _collapse(self):
        """Alpha died on a collapse_on_alpha_death species → disband pack."""
        from classes.monster import Monster
        survivors = []
        for uid in self.members_m + self.members_f:
            m = Monster.by_uid(uid)
            if m is not None:
                survivors.append(m)
        self.members_m.clear()
        self.members_f.clear()
        self.member_state.clear()
        # Each survivor becomes solitary
        for m in survivors:
            m.pack = Pack(self.species, m.location, self.game_map)
            m.pack.add_member(m)

    # ------------------------------------------------------------------
    # Territory
    # ------------------------------------------------------------------

    def effective_territory_size(self) -> float:
        """Compute the current std_dev for monster roaming sampling.

        Scales with pack.size if species.territory_scales, clamped to
        10% of max as a floor so solo members still have some range.
        Further modulated by cohesion signal (tighter cluster when alert).
        """
        base = self.territory_size_max
        if self.territory_scales:
            divisor = max(1, self.split_size - 1)
            factor = max(0.1, self.size / divisor)
            base = base * factor
        # Cohesion tightens the spread (cohesion 1.0 → 20% of normal)
        base = base * (1.0 - self.cohesion * 0.8)
        return max(0.5, base)

    def sample_target_position(self) -> MapKey:
        """Sample a roaming target from N(center, effective_territory_size)."""
        import random as _rng
        std = self.effective_territory_size()
        dx = _rng.gauss(0, std)
        dy = _rng.gauss(0, std)
        tx = int(round(self.territory_center.x + dx))
        ty = int(round(self.territory_center.y + dy))
        return MapKey(tx, ty, self.territory_center.z)

    def territory_radius(self) -> float:
        """3-sigma practical radius for territory overlap checks."""
        return self.effective_territory_size() * 3.0

    def territories_overlap(self, other: 'Pack') -> bool:
        """True if this pack's territory circle intersects another's."""
        if self.game_map is not other.game_map:
            return False
        dx = self.territory_center.x - other.territory_center.x
        dy = self.territory_center.y - other.territory_center.y
        dist = math.sqrt(dx * dx + dy * dy)
        return dist < (self.territory_radius() + other.territory_radius())

    # ------------------------------------------------------------------
    # Shared perception — event-driven
    # ------------------------------------------------------------------

    def on_creature_spotted(self, creature_uid: int, x: int, y: int, tick: int):
        self.seen_creatures[creature_uid] = (x, y, tick)

    def on_creature_lost(self, creature_uid: int):
        self.seen_creatures.pop(creature_uid, None)

    def on_member_state(self, monster_uid: int, **kwargs):
        """Monster reports a state change. Only updated fields are merged."""
        entry = self.member_state.setdefault(monster_uid, {})
        entry.update(kwargs)

    # ------------------------------------------------------------------
    # Signal broadcast (change-detected)
    # ------------------------------------------------------------------

    _SIGNAL_EPS = 0.05  # only re-broadcast if change exceeds this

    def broadcast_signals(self, sleep: float, alert: float, cohesion: float,
                          role_fractions: dict):
        """Update signals; broadcast to members only on material change."""
        if abs(sleep - self.sleep_signal) > self._SIGNAL_EPS:
            self.sleep_signal = sleep
            for m in self.members:
                m.on_pack_signal('sleep', sleep)
        if abs(alert - self.alert_level) > self._SIGNAL_EPS:
            self.alert_level = alert
            for m in self.members:
                m.on_pack_signal('alert', alert)
        if abs(cohesion - self.cohesion) > self._SIGNAL_EPS:
            self.cohesion = cohesion
            for m in self.members:
                m.on_pack_signal('cohesion', cohesion)
        # Role fractions: update always, broadcast per-monster (Phase 7/8 wires
        # individual role assignment; for now just store)
        self.role_fractions = dict(role_fractions)

    # ------------------------------------------------------------------
    # Pack-vs-Pack interactions
    # ------------------------------------------------------------------

    def can_merge_with(self, other: 'Pack') -> bool:
        """Merge allowed when same species and combined size <= split_size/2."""
        if self.species != other.species:
            return False
        combined = self.size + other.size
        return combined <= self.split_size / 2

    def is_hostile_to(self, other: 'Pack') -> bool:
        """Hostile only when territories intersect."""
        if self is other:
            return False
        if self.species == other.species and self.can_merge_with(other):
            return False  # small enough to prefer merging
        return self.territories_overlap(other)

    # ------------------------------------------------------------------
    # Phase 4: Pack state FSM (heuristic transitions)
    # ------------------------------------------------------------------
    def _ensure_state_fsm(self):
        """Lazy-init the pack-state FSM on first use.

        States per Phase 4 design: forming, territorial, defending,
        hunting, fleeing, merging, dispersed (terminal).
        """
        if self._state_fsm is not None:
            return self._state_fsm
        from classes.fsm import StateMachine, Transition
        self._state_fsm = StateMachine(
            owner=self,
            initial='forming',
            states=['forming', 'territorial', 'defending', 'hunting',
                    'fleeing', 'merging', 'dispersed'],
            transitions=[
                # Forming stabilizes into territorial after the timer.
                Transition('forming',     'stabilize', 'territorial'),
                # Territorial → situational states
                Transition('territorial', 'threat',    'defending'),
                Transition('territorial', 'hunt',      'hunting'),
                Transition('territorial', 'overwhelm', 'fleeing'),
                Transition('territorial', 'join',      'merging'),
                # Return paths
                Transition('defending',   'safe',       'territorial'),
                Transition('defending',   'overwhelm',  'fleeing'),
                Transition('hunting',     'satiated',   'territorial'),
                Transition('hunting',     'overwhelm',  'fleeing'),
                Transition('fleeing',     'safe',       'territorial'),
                Transition('fleeing',     'shatter',    'dispersed'),
                Transition('merging',     'complete',   'territorial'),
                # Disperse from any state when size hits 0
                Transition('*',           'disperse',   'dispersed'),
            ],
        )
        return self._state_fsm

    @property
    def pack_state(self) -> str:
        fsm = self._state_fsm
        return fsm.current if fsm is not None else 'forming'

    def evaluate_pack_state(self, sim=None) -> None:
        """Re-evaluate heuristic transitions. Safe to call each tick.

        Rules:
          - forming → territorial after FORMING_DAYS (3 game days)
          - any → dispersed when size == 0
          - territorial → defending when any seen creature is a threat
            in the territory
          - defending → territorial when threats cleared
          - territorial → fleeing when size dropped > 50% from peak
            (simplified: size <= 1)
          - Merging/hunting left for PackNet signals to trigger
        """
        fsm = self._ensure_state_fsm()
        now = getattr(sim, 'now', 0)

        # Disperse on empty
        if self.size == 0 and fsm.current != 'dispersed':
            fsm.trigger('disperse', now=now)
            return

        # Forming window: stabilize once the initial period is past.
        # In the absence of explicit calendar integration here we
        # treat 3000 game-ticks (~25 min real time) as the stabilization.
        FORMING_WINDOW_MS = 3000
        if fsm.current == 'forming':
            if now - self._pack_formed_at >= FORMING_WINDOW_MS:
                fsm.trigger('stabilize', now=now)
            return

        # Threat detection via seen_creatures
        # NOTE: this is a heuristic — real PackNet sees individual
        # threats and may emit explicit pack signals. We only fire
        # the coarse transition here; fine-grained flee/press is
        # the Pack NN's job.
        has_threat = bool(self.seen_creatures)
        if fsm.current == 'territorial' and has_threat:
            fsm.trigger('threat', now=now)
        elif fsm.current == 'defending' and not has_threat:
            fsm.trigger('safe', now=now)

        # Overwhelm check: small pack + threats = flee
        if fsm.current in ('territorial', 'defending') and has_threat and self.size <= 1:
            fsm.trigger('overwhelm', now=now)

    def pack_centroid(self) -> tuple[float, float]:
        """Average (x, y) of all members. (0,0) if empty."""
        members = self.members
        if not members:
            return (0.0, 0.0)
        x = sum(m.location.x for m in members) / len(members)
        y = sum(m.location.y for m in members) / len(members)
        return (x, y)
