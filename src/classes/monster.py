"""
Monster class — predators/antagonists in the world.

Monster is a top-level class (NOT a Creature subclass) that shares the
movement/combat/regen infrastructure with Creature via the same mixins.
What Monster deliberately does NOT inherit from the Creature mixin set:

  - SocialMixin       : no TALK, INTIMIDATE, DECEIVE, TRADE
  - RelationshipsMixin: no sentiment graph participation
  - ConversationMixin : no dialogue
  - ReproductionMixin : monsters reproduce via the Pack/egg system, not
                        creature-style partner selection
  - GoalMixin         : monsters take direction from their Pack, not from
                        a creature-style personal goal
  - UtilityMixin      : no JOB, SLEEP schedule, TRAPS, guard stance

Monster has its own NN (MonsterNet) with a restricted action space gated
by INT (instinct/feral/aware/cunning bands) and diet (carnivore/
herbivore/omnivore). Coordination is handled by the Pack class.

Stats carry a neutral CHR=10 purely so existing derived stat formulas
(HP_MAX, INTIMIDATION, etc.) remain well-defined. Monsters never use
the charisma-derived social stats.
"""
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
from classes.creature._movement import MovementMixin
from classes.creature._inventory import InventoryMixin
from classes.creature._regen import RegenMixin


# Default meat value by size when species doesn't override
_SIZE_MEAT = {'tiny': 0.05, 'small': 0.15, 'medium': 0.3,
              'large': 0.6, 'huge': 1.0, 'colossal': 1.5}


class Monster(
    CombatMixin,
    MovementMixin,
    InventoryMixin,
    RegenMixin,
    WorldObject,
):
    """Predator/antagonist entity with its own NN and pack coordination.

    Attack semantics reuse Creature mixins so both sides of creature-vs-
    monster combat run through the same damage formulas.
    """
    sprite_name = 'c_human_m'      # overridden by species
    z_index = 3
    _uid_registry: dict[int, 'Monster'] = {}

    @classmethod
    def by_uid(cls, uid: int) -> 'Monster | None':
        ref = cls._uid_registry.get(uid)
        return ref if ref is not None and ref.is_alive else None

    @classmethod
    def on_same_map(cls, game_map) -> list['Monster']:
        from classes.world_object import WorldObject
        return [o for o in WorldObject._by_map.get(id(game_map), [])
                if isinstance(o, cls) and o.is_alive]

    collision = True

    def __init__(
        self,
        current_map: Map,
        location: MapKey = MapKey(),
        name: str = None,
        species: str = None,
        stats: dict = None,
        pack: object = None,
        sex: str = None,
        age: int = 0,
    ):
        super().__init__(current_map=current_map, location=location)
        Monster._uid_registry[self.uid] = self
        self.name = name or f'{species or "monster"}_{self.uid}'
        self.species = species

        from data.db import MONSTER_SPECIES
        species_data = MONSTER_SPECIES.get(species, {}) if species else {}

        # Basic identity + rendering
        self.sprite_name = species_data.get('sprite_name', self.__class__.sprite_name)
        self.composite_name = species_data.get('composite_name')
        self.tile_scale = species_data.get('tile_scale', 1.0)
        self.size = species_data.get('size', 'medium')
        self.sex = sex if sex is not None else random.choice(('male', 'female'))
        self.age = age

        # Meat-on-death value
        self.meat_value = species_data.get('meat_value',
                                           _SIZE_MEAT.get(self.size, 0.3))

        # Diet and grazing
        self.diet = species_data.get('diet', 'carnivore')
        self.compatible_tile = species_data.get('compatible_tile')

        # Pack behavior (species-level config mirrored onto instance for
        # convenience; Pack reads species for the canonical values)
        self.split_size = species_data.get('split_size', 4)
        self.territory_size_max = species_data.get('territory_size', 8.0)
        self.territory_scales = species_data.get('territory_scales', True)
        self.dominance_type = species_data.get('dominance_type', 'contest')
        self.collapse_on_alpha_death = species_data.get(
            'collapse_on_alpha_death', False)
        self.active_hours = species_data.get('active_hours', 'diurnal')
        self.ambush_tactics = species_data.get('ambush_tactics', False)
        self.protect_young = species_data.get('protect_young', True)

        # Swimming (behaves like Creature.can_swim for movement mixin)
        self.can_swim = species_data.get('swimming', False)

        # Natural weapon — attached to inventory/equipment if the species
        # defines one. DB loading happens in the game runtime, not here;
        # Phase 6 will wire this up.
        self.natural_weapon_key = species_data.get('natural_weapon_key')

        # Pack membership (set by Pack.add_member)
        self.pack = pack

        # Dominance rank (set by Pack when joining). Separate M/F.
        self.rank: int = 0
        self.is_alpha: bool = False

        # Build Stats from species defaults + overrides
        species_stats = {k: v for k, v in species_data.items()
                         if isinstance(k, Stat)}
        merged = {**species_stats, **(stats or {})}
        # Guarantee CHR present so derived stat formulas stay defined.
        merged.setdefault(Stat.CHR, 10)
        hd = merged.pop(Stat.HIT_DICE, 6)
        self.stats = Stats(base_stats=merged, hit_dice=hd)

        self.inventory = Inventory(items=[])
        self.equipment: dict[Slot, Equippable] = {}

        # Ghost/sleep state placeholders (regen mixin reads these)
        self.is_ghost = False
        self.hunger: float = 1.0
        self._hunger_drain: float = 2.0 / 1440.0
        self._regen_start = float('inf')
        self._regen_fib = (1, 1)
        self._max_hit_taken: int = 0
        self._kills: int = 0
        self._damage_dealt: int = 0
        self._tiles_explored: int = 0
        self.is_drowning = False
        self._drown_ticks = 0
        self._visited_tiles: set = set()

        # Perception cache (same shape as Creature for mixin compatibility)
        self._perception_cache_tick: int = -1
        self._cached_visible: list = []
        self._cached_heard: list = []

        # Event-driven signals from Pack (latched; updated by Pack events)
        self._pack_sleep_signal: float = 0.0
        self._pack_alert_level: float = 0.0
        self._pack_cohesion: float = 0.5
        self._pack_role: str = 'patrol'
        self._pack_target_position: MapKey | None = None

        # Hunger + HP + water ticks (mirror Creature's set so existing
        # mixin code fires correctly)
        self.register_tick('hunger', 1000, self._do_hunger_tick)
        self.register_tick('hp_regen', 1000, self._do_hp_regen)
        self.register_tick('stamina_regen', 1000, self._do_stamina_regen)
        self.register_tick('mana_regen', 1000, self._do_mana_regen)
        # Water tick is registered lazily by location setter.
        self._water_tick_active = False
        self._last_spatial_scan_loc = None

        # Dialogue placeholder so any shared code that checks for it
        # doesn't crash. Monsters never engage in dialogue.
        self.dialogue = None

    # ------------------------------------------------------------------
    # Location setter — matches Creature pattern for spatial grid + water
    # ------------------------------------------------------------------

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, new_loc):
        old = getattr(self, '_location', None)
        cm = getattr(self, '_current_map', None)
        if (old is not None and cm is not None
                and hasattr(cm, 'unregister_creature_at')):
            cm.unregister_creature_at(self, old.x, old.y, old.z)
        self._location = new_loc
        if (new_loc is not None and cm is not None
                and hasattr(cm, 'register_creature_at')):
            cm.register_creature_at(self, new_loc.x, new_loc.y, new_loc.z)
        self._perception_cache_tick = -1

        # Water tick: register only on liquid tiles
        if (new_loc is not None and cm is not None
                and hasattr(self, '_water_tick_active')):
            tile = cm.tiles.get(new_loc)
            in_liquid = tile is not None and getattr(tile, 'liquid', False)
            if in_liquid and not self._water_tick_active:
                self.register_tick('water', 100, self._do_water_tick)
                self._water_tick_active = True
            elif not in_liquid and self._water_tick_active:
                self.unregister_tick('water')
                self._water_tick_active = False
                self.is_drowning = False
                self._drown_ticks = 0

    # ------------------------------------------------------------------
    # Death — drop Meat item on the tile
    # ------------------------------------------------------------------

    def die(self):
        """Death: drop meat on tile, clear ticks, deregister.

        Overrides the default combat mixin death path to drop Meat
        instead of dropping the full inventory.
        """
        if not self.is_alive:
            return
        self.stats.base[Stat.HP_CURR] = 0
        self.play_animation('death')
        self._timed_events.clear()

        # Drop meat
        if self.current_map is not None and self.meat_value > 0:
            from classes.inventory import Meat
            # Very rough: 48hr spoil window from a 1000ms-tick clock
            # (48 * 60 * 60 = 172800 seconds -> 172800 ticks at 1 TPS)
            now = getattr(self, '_last_update_time', 0)
            meat = Meat(
                name=f'{self.species or "monster"}_meat',
                description=f'Fresh meat from a {self.species}.',
                weight=max(0.1, self.meat_value * 2.0),
                value=self.meat_value * 5.0,
                species=self.species,
                meat_value=self.meat_value,
                spoil_tick=now + 172_800,
                is_monster_meat=True,
            )
            tile = self.current_map.tiles.get(self.location)
            if tile is not None:
                tile.inventory.items.append(meat)

        # Pack cleanup
        if self.pack is not None:
            try:
                self.pack.remove_member(self)
            except Exception:
                pass
            self.pack = None

        # Deregister from spatial grid
        cm = getattr(self, '_current_map', None)
        loc = getattr(self, '_location', None)
        if cm is not None and loc is not None and hasattr(cm, 'unregister_creature_at'):
            cm.unregister_creature_at(self, loc.x, loc.y, loc.z)

    @property
    def is_alive(self) -> bool:
        return self.stats.active[Stat.HP_CURR]() > 0

    # ------------------------------------------------------------------
    # Pack-signal event handlers (called by Pack when state changes)
    # ------------------------------------------------------------------

    def on_pack_signal(self, signal_name: str, value):
        """Receive an event-driven signal from the Pack."""
        if signal_name == 'sleep':
            self._pack_sleep_signal = float(value)
        elif signal_name == 'alert':
            self._pack_alert_level = float(value)
        elif signal_name == 'cohesion':
            self._pack_cohesion = float(value)
        elif signal_name == 'role':
            self._pack_role = str(value)
        elif signal_name == 'target_position':
            self._pack_target_position = value

    # ------------------------------------------------------------------
    # Grazing — passive hunger recovery for low-INT herbivores/omnivores
    # ------------------------------------------------------------------

    def _can_graze(self) -> bool:
        """True if this monster is standing on a tile matching its diet."""
        if self.diet == 'carnivore':
            return False
        if self.compatible_tile is None or self.current_map is None:
            return False
        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            return False
        tile_purpose = getattr(tile, 'purpose', None) or getattr(tile, 'resource_type', None)
        return tile_purpose == self.compatible_tile


# Helper for stat lookups used by mixins expecting creature-style access
Monster._hot_array = None  # set by Simulation to CreatureHotArray if needed
Monster._tile_grid = None
