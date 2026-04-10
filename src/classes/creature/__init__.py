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
        self._tiles_explored: int = 0
        self._quests_completed: int = 0
        self._quest_steps_completed: int = 0
        self._max_hit_taken: int = 0        # worst single hit for survival anchor
        self._item_prices: dict = {}        # item id -> gold paid

        # Hunger: 1.0 = full, 0.0 = neutral, -1.0 = starving
        # Drains ~0.02 per tick (reaches starving in ~100 ticks / 50s)
        self.hunger: float = 0.5  # start half-full
        self._hunger_drain: float = 0.02  # per hunger tick

        # Spatial memory: {purpose_str: [(map_name, x, y, tick_discovered), ...]}
        # Populated when creature visits a purpose zone or purpose tile
        self.known_locations: dict[str, list[tuple]] = {}

        # Goal state (hierarchical RL)
        self.current_goal: str | None = None      # purpose string e.g. 'trading'
        self.goal_target: tuple | None = None      # (map_name, x, y) destination
        self.goal_started_tick: int = 0
        self.goal_prev_distance: float = 0.0       # for progress reward

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

        # Relationships: {uid: [sentiment, count, min_score, max_score]}
        # sentiment = raw cumulative score, count = number of interactions,
        # min/max = bounds of individual interaction scores
        self.relationships: dict[int, list] = {}

        # Rumors: {subject_uid: [(source_uid, sentiment, confidence, tick)]}
        # Inherited opinions from other creatures about third parties.
        # confidence = source's relationship confidence with the subject
        # tick = game tick when rumor was received (for decay)
        self.rumors: dict[int, list] = {}

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
