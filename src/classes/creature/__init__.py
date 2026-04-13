from __future__ import annotations
import random
from classes.maps import Map, MapKey
from classes.inventory import Inventory, Equippable, Slot
from classes.world_object import WorldObject
from classes.stats import Stat, Stats

from classes.creature._constants import (
    SIZE_CATEGORIES, SIZE_UNITS, SIZE_FOOTPRINT, TILE_CAPACITY,
)
from classes.creature._combat import CombatMixin
from classes.creature._social import SocialMixin
from classes.creature._movement import MovementMixin
from classes.creature._inventory import InventoryMixin
from classes.creature._reproduction import ReproductionMixin
from classes.creature._relationships import RelationshipsMixin
from classes.creature._conversation import ConversationMixin
from classes.creature._utility import UtilityMixin
from classes.creature._goals import GoalMixin
from classes.creature._regen import RegenMixin
from classes.creature._behaviors import (
    RandomWanderBehavior, PairedBehavior, NeuralBehavior, StatWeightedBehavior,
)


class Creature(
    CombatMixin,
    SocialMixin,
    MovementMixin,
    InventoryMixin,
    ReproductionMixin,
    RelationshipsMixin,
    ConversationMixin,
    UtilityMixin,
    GoalMixin,
    RegenMixin,
    WorldObject,
):
    """Single creature class for players, NPCs, and monsters.

    There are no subclasses. All behavioral differences are driven by
    behavior modules assigned to ``self.behavior``.
    """
    sprite_name = 'player'
    z_index     = 3
    collision   = True

    def __init__(
        self,
        current_map: Map,
        location: MapKey = MapKey(),
        name: str = None,
        species: str = None,
        stats: dict = None,
        items: list = None,
        behavior: object = None,
        move_interval: int = 1000,
        sex: str = None,
        prudishness: float = None,
        age: int = 0,
        chromosomes: tuple = None,
        mother_uid: int = None,
        father_uid: int = None,
        is_abomination: bool = False,
        size: str = None,
    ):
        super().__init__(current_map=current_map, location=location)
        self.name = name
        self.species = species

        from data.db import SPECIES
        species_data = SPECIES.get(species, {}) if species else {}

        # Sex first — sprite selection depends on it
        self.sex = sex if sex is not None else random.choice(('male', 'female'))

        # Sprite: pick sex-appropriate version, fall back to default
        if self.sex == 'female' and species_data.get('sprite_name_f'):
            self.sprite_name = species_data['sprite_name_f']
        else:
            self.sprite_name = species_data.get('sprite_name', self.__class__.sprite_name)

        if self.sex == 'female' and species_data.get('composite_name_f'):
            self.composite_name = species_data['composite_name_f']
        else:
            self.composite_name = species_data.get('composite_name', self.__class__.composite_name)

        self.tile_scale = species_data.get('tile_scale', self.__class__.tile_scale)

        # Size: from species default or override
        self.size = size or species_data.get('size', 'medium')
        # Sentience: from species (non-sentient = crickets, deer, fish)
        self.sentient: bool = bool(species_data.get('sentient', True))
        # Prudishness: species default with per-creature override
        self.prudishness = prudishness if prudishness is not None else species_data.get('prudishness', 0.5)
        # Age in game days (0 = newborn)
        self.age = age

        # Genetics and lineage
        self.chromosomes = chromosomes
        self.mother_uid = mother_uid
        self.father_uid = father_uid
        self.is_abomination = is_abomination
        self.inbred = False
        self.is_pregnant = False
        self._pair_cooldown = 0  # timestamp when next pairing is allowed
        self.partner_uid: int | None = None  # UID of amorous partner (None = single)

        # Religion
        self.deity: str | None = None   # god name or None
        self.piety: float = 0.0        # 0.0–1.0

        # Quest log
        from classes.quest import QuestLog
        self.quest_log = QuestLog()

        # Economy
        self.gold: int = 0
        # Loans: {lender_uid: {'principal': float, 'rate': float, 'originated': int}}
        # rate = daily interest rate (e.g. 0.05 = 5% per day)
        # originated = game tick when loan was made
        self.loans: dict[int, dict] = {}
        # Loans given: {borrower_uid: same structure}
        self.loans_given: dict[int, dict] = {}

        # Observation mask: preset name or None. Zeros out sections of NN input.
        # See observation.py PRESET_MASKS for options (socially_deaf, blind, feral, etc.)
        self.observation_mask: str | None = None

        # History buffer for temporal transforms (ring buffer, max 100 snapshots)
        from collections import deque
        self._history: deque = deque(maxlen=100)
        self._event_ticks: dict[str, int] = {}  # event_name -> last tick it happened

        # RL tracking counters
        self.life_goal_attainment: int = 0  # pairing, hatch, child milestones
        self.failed_actions: int = 0        # actions failed due to resources
        self._kills: int = 0
        self._damage_dealt: int = 0
        self._social_wins: int = 0
        self._tiles_explored: int = 0
        self._quests_completed: int = 0
        self._quest_steps_completed: int = 0
        self._max_hit_taken: int = 0        # worst single hit for survival anchor
        self._item_prices: dict = {}        # item id -> gold paid
        self._pickups: int = 0              # successful PICKUP actions (RL counter)
        self._stolen_value: float = 0.0     # cumulative value of stolen items/gold (RL counter)
        self._active_social_target = None   # creature currently in TALK/TRADE with (for DECEIVE gate)

        # Hunger: 1.0 = full, 0.0 = neutral, -1.0 = starving
        # Full bar (1.0 to -1.0) depletes in 1 game day (24 min real time)
        # 1440 ticks/day, 2.0 range → ~0.00139/tick
        self.hunger: float = 1.0  # start full — gives a full game day before hunger pressure
        self._hunger_drain: float = 2.0 / 1440.0  # per hunger tick

        # Spatial memory: {purpose_str: [(map_name, x, y, tick_discovered), ...]}
        # Populated when creature visits a purpose zone or purpose tile
        self.known_locations: dict[str, list[tuple]] = {}

        # Goal state (hierarchical RL)
        self.current_goal: str | None = None      # purpose string e.g. 'trading'
        self.goal_target: tuple | None = None      # (map_name, x, y) destination
        self.goal_started_tick: int = 0
        self.goal_prev_distance: float = 0.0       # for progress reward

        # Job / schedule. Assigned by arena generator or runtime logic.
        # None = wanderer (no work obligations, still has a sleep schedule).
        from classes.jobs import Schedule, WANDERER
        self.job = None
        self.schedule: Schedule = WANDERER   # default; overridden when job is set
        self._wage_accumulated: float = 0.0  # total wages earned this session
        self._trade_surplus_accumulated: float = 0.0  # summed bargain surplus from trades

        # Per-tick perception cache. The `_perception_cache_tick` is
        # compared against the simulation step counter; when stale, the
        # cached visible/heard lists are rebuilt from the spatial grid.
        # Invalidated by the location setter above so a creature moving
        # always gets a fresh scan next time it's queried.
        self._perception_cache_tick: int = -1
        self._cached_visible: list = []   # list of (distance, creature)
        self._cached_heard: list = []     # list of (distance, creature)
        # Persistent perception slots: a fixed-size list of creature
        # uids that the NN sees as "the creatures I'm tracking right
        # now." Stable across ticks — when someone leaves visibility
        # their slot clears and the next new visible creature takes
        # the empty slot. This gives the NN stable per-creature
        # signals that don't scramble on every tick.
        self._perception_slots: list = [None] * 10  # 10 slots
        # Cache of (uid -> last-seen position) used to compute
        # approaching/fleeing flags in the next perception pass.
        self._last_seen_positions: dict = {}

        # Build Stats from species defaults + overrides
        species_stats = {k: v for k, v in species_data.items() if isinstance(k, Stat)}
        merged = {**species_stats, **(stats or {})}
        hd = merged.pop(Stat.HIT_DICE, 6)
        self.stats = Stats(base_stats=merged, hit_dice=hd)

        self.inventory = Inventory(items=items or [])
        self.equipment: dict[Slot, Equippable] = {}
        self.map_stack: list[tuple[Map, MapKey]] = []

        # Active conversation state: {target_uid, conversation, current_node_id}
        self.dialogue = None  # None = not in conversation

        # Relationships and rumors live in the centralized
        # RelationshipGraph (src/classes/relationship_graph.py).
        # Access via GRAPH.edges_from(self.uid), GRAPH.rumors_of(self.uid),
        # etc. — no per-creature dicts.

        # Behavior module for non-player creatures (NPC AI, monster AI, etc.)
        self.behavior = behavior
        self._cols = 0
        self._rows = 0
        if behavior is not None:
            self.register_tick('behavior', move_interval, self._do_behavior)

        # Skills
        self.can_swim: bool = False  # learned skill — prevents drowning
        self.is_drowning: bool = False  # currently drowning (in liquid, no swim, submerged)
        self._drown_ticks: int = 0  # consecutive ticks spent drowning

        # Movement mode: 'walk' (default) or 'sneak' (toggled by SET_SNEAK).
        # Walk vs run is auto-selected by the dispatcher based on threat context.
        self.movement_mode: str = 'walk'

        # Sleep deprivation
        self.sleep_debt: int = 0  # days without sleep
        self._fatigue_level: int = 0  # current debuff tier (0-4)

        # Hunger tick — drain over time
        self.register_tick('hunger', 1000, self._do_hunger_tick)

        # HP regen state
        self._regen_start = float('inf')  # timestamp when regen kicks in
        self._regen_fib = (1, 1)
        self.register_tick('hp_regen', 1000, self._do_hp_regen)

        # Stamina regen
        self.register_tick('stamina_regen', 1000, self._do_stamina_regen)

        # Mana regen
        self.register_tick('mana_regen', 1000, self._do_mana_regen)

        # Water/flow tick — checks drowning and applies current
        # 100ms for up to 10 TPS flow speed
        self.register_tick('water', 100, self._do_water_tick)

        # Spatial memory: learn locations of purpose zones each tick
        self.register_tick('spatial_memory', 500, lambda now: self.update_spatial_memory(now))

    # -- Pickle migration for centralized relationship graph ---------------
    # Saves created before the graph refactor have ``relationships`` and
    # ``rumors`` dicts directly in the creature's ``__dict__``. We
    # intercept ``__setstate__`` (called by pickle) and migrate those
    # dicts into the central GRAPH so the creature can unpickle cleanly.

    def __setstate__(self, state):
        legacy_rels = state.pop('relationships', None)
        legacy_rumors = state.pop('rumors', None)
        self.__dict__.update(state)
        if legacy_rels:
            from classes.relationship_graph import GRAPH
            GRAPH.set_edges_from(self.uid, legacy_rels)
        if legacy_rumors:
            from classes.relationship_graph import GRAPH
            GRAPH.set_rumors_of(self.uid, legacy_rumors)

    # -- Location property override (spatial grid registration) -----------
    #
    # Creature overrides WorldObject.location so every position change
    # automatically updates the Map's spatial grid. This is the single
    # chokepoint the grid depends on — every code path that moves a
    # creature MUST go through this setter, which it does as long as
    # it writes to ``self.location`` rather than poking ``_location``
    # directly.

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, new_loc):
        old = getattr(self, '_location', None)
        # Unregister from old cell if we had one on the current map
        cm = getattr(self, '_current_map', None)
        if (old is not None and cm is not None
                and hasattr(cm, 'unregister_creature_at')):
            cm.unregister_creature_at(self, old.x, old.y, old.z)
        self._location = new_loc
        # Register at new cell if we're on a map
        if (new_loc is not None and cm is not None
                and hasattr(cm, 'register_creature_at')):
            cm.register_creature_at(self, new_loc.x, new_loc.y, new_loc.z)
        # Invalidate the cached visibility snapshot — position changed.
        # Use setattr so this works even before __init__ has set the attr.
        self._perception_cache_tick = -1

    # -- Perception cache ---------------------------------------------------
    #
    # Computed once per simulation step and reused across observation,
    # dispatch, and reward consumers. Rebuilt only when the cache tick
    # doesn't match the caller-supplied tick (or when self.location
    # changes, which invalidates the cache via the setter above).
    #
    # Returns two lists:
    #   visible: (distance, other_creature) sorted by ascending distance
    #   heard:   (distance, other_creature) creatures within hearing
    #            range but NOT within sight range

    def _threat_score_against(self, other) -> float:
        """Estimate how much damage ``other`` could do to self in a fight.

        Compact formula: their effective attack power minus my armor,
        scaled by how many hits they could land before I regen.
        Returns a float in roughly 0..20 range where 0 is "harmless"
        and 20 is "could kill me this turn."
        """
        from classes.stats import Stat
        their_melee = other.stats.active[Stat.MELEE_DMG]()
        their_weapon = 0
        try:
            from classes.inventory import Weapon, Slot
            w = other.equipment.get(Slot.HAND_R) or other.equipment.get(Slot.HAND_L)
            if w and isinstance(w, Weapon):
                their_weapon = getattr(w, 'damage', 0)
        except Exception:
            pass
        my_armor = self.stats.active[Stat.ARMOR]()
        per_hit = max(0, their_melee + their_weapon - my_armor)
        # Rough approximation: ~5 hits before I can act defensively
        return float(per_hit * 5)

    def update_perception_slots(self, visible: list) -> list:
        """Update the 10 persistent perception slots from a visible list.

        ``visible`` is [(distance, creature), ...] as returned by
        ``get_perception``. Slots are updated as follows:

          1. Any slot whose creature is no longer in ``visible`` is
             cleared to None. The slot index is NOT reused by another
             creature this tick — leaving it empty is a signal to the
             NN that that specific creature vanished.
          2. Creatures already in slots keep their slot index.
          3. New visible creatures (not in any slot) take the first
             empty slot, in closest-first order.
          4. If every slot is full and a new creature appears that's
             closer than the currently-slotted farthest, we do NOT
             evict. Slots are earned by arriving first. This keeps
             signals stable — a new-but-closer arrival is captured
             by the "rest of crowd" summary, not by kicking out a
             known creature.

        Returns a list of (slot_index, creature_or_None, distance)
        triples where distance is None for empty slots. Length == 10.
        """
        visible_uids = {c.uid for _, c in visible}
        visible_by_uid = {c.uid: (d, c) for d, c in visible}

        # Pass 1: clear slots for creatures no longer visible
        for i, uid in enumerate(self._perception_slots):
            if uid is not None and uid not in visible_uids:
                self._perception_slots[i] = None

        # Pass 2: assign new visible creatures to empty slots in
        # closest-first order. Creatures already slotted keep their
        # position automatically.
        slotted = {uid for uid in self._perception_slots if uid is not None}
        new_arrivals = [(d, c) for d, c in visible if c.uid not in slotted]
        for d, c in new_arrivals:
            # Find first empty slot
            for i, uid in enumerate(self._perception_slots):
                if uid is None:
                    self._perception_slots[i] = c.uid
                    break
            # If no empty slot, skip — creature goes to "rest of crowd"

        # Pass 3: build the return list
        result = []
        for i, uid in enumerate(self._perception_slots):
            if uid is None:
                result.append((i, None, None))
            else:
                entry = visible_by_uid.get(uid)
                if entry is None:
                    # Shouldn't happen but be defensive
                    result.append((i, None, None))
                else:
                    d, c = entry
                    result.append((i, c, d))
        return result

    def get_perception(self, tick: int) -> tuple[list, list]:
        """Return (visible, heard_only) lists for this creature at ``tick``.

        Uses the Map's spatial grid when available (cheap O(cell_neighborhood)),
        falls back to WorldObject.on_map iteration otherwise. Cached per
        tick on the creature.
        """
        if self._perception_cache_tick == tick:
            return self._cached_visible, self._cached_heard

        from classes.stats import Stat
        from classes.world_object import WorldObject
        from classes.creature import Creature as _C

        game_map = self._current_map
        sight = max(1, self.stats.active[Stat.SIGHT_RANGE]())
        hearing = max(1, self.stats.active[Stat.HEARING_RANGE]())
        query_range = max(sight, hearing)

        # Prefer the spatial grid broad-phase when the map supports it
        if game_map is not None and hasattr(game_map, 'creatures_in_range'):
            candidates = game_map.creatures_in_range(
                self.location.x, self.location.y, self.location.z, query_range)
        else:
            candidates = [o for o in WorldObject.on_map(game_map)
                          if isinstance(o, _C)]

        cx = self.location.x
        cy = self.location.y
        visible = []
        heard = []
        for obj in candidates:
            if obj is self or not obj.is_alive:
                continue
            dist = abs(cx - obj.location.x) + abs(cy - obj.location.y)
            stealth = obj.stats.active[Stat.STEALTH]()
            eff_sight = sight - stealth
            if dist <= eff_sight:
                visible.append((dist, obj))
            elif dist <= hearing:
                heard.append((dist, obj))

        visible.sort(key=lambda x: x[0])
        heard.sort(key=lambda x: x[0])

        self._cached_visible = visible
        self._cached_heard = heard
        self._perception_cache_tick = tick
        return visible, heard

    # -- Age ----------------------------------------------------------------

    # Age thresholds in days — will move to species config later
    YOUNG_MAX = 30    # 0–30 days = young
    OLD_MIN   = 365   # 365+ days = old

    @property
    def age_class(self) -> str:
        """Return 'young', 'adult', or 'old' based on age in days."""
        if self.age <= self.YOUNG_MAX:
            return 'young'
        if self.age >= self.OLD_MIN:
            return 'old'
        return 'adult'

    # -- Experience ---------------------------------------------------------

    def gain_exp(self, amount: int):
        self.stats.gain_exp(amount)

    # -- Timed behaviors ----------------------------------------------------

    def update(self, now: int, cols: int, rows: int):
        """Called each frame for non-player creatures."""
        self._last_update_time = now
        self._cols = cols
        self._rows = rows
        self.process_ticks(now)

    def _do_behavior(self, _now: int):
        """Behavior think tick."""
        if self.behavior is not None:
            self.behavior.think(self, self._cols, self._rows)
        else:
            self.play_animation('idle')


__all__ = [
    'Creature',
    'SIZE_CATEGORIES', 'SIZE_UNITS', 'SIZE_FOOTPRINT', 'TILE_CAPACITY',
    'RandomWanderBehavior', 'PairedBehavior', 'NeuralBehavior', 'StatWeightedBehavior',
]
