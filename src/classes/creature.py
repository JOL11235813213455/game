from __future__ import annotations
import random
from classes.maps import Map, MapKey, DIRECTION_BOUNDS
from classes.inventory import Inventory
from classes.world_object import WorldObject
from classes.stats import Stat, Stats


class Creature(WorldObject):
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
    ):
        super().__init__(current_map=current_map, location=location)
        self.name = name
        self.species = species

        from data.db import SPECIES
        species_data = SPECIES.get(species, {}) if species else {}
        self.tile_scale     = species_data.get('tile_scale',     self.__class__.tile_scale)
        self.sprite_name    = species_data.get('sprite_name',    self.__class__.sprite_name)
        self.composite_name = species_data.get('composite_name', self.__class__.composite_name)

        # Build Stats from species defaults + overrides
        species_stats = {k: v for k, v in species_data.items() if isinstance(k, Stat)}
        merged = {**species_stats, **(stats or {})}
        hd = merged.pop(Stat.HIT_DICE, 6)
        self.stats = Stats(base_stats=merged, hit_dice=hd)

        self.inventory = Inventory(items=items or [])
        self.map_stack: list[tuple[Map, MapKey]] = []

        # Dialogue tree placeholder — will hold dialogue data when fleshed out
        self.dialogue = None

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

        # HP regen state
        self._regen_start = float('inf')  # timestamp when regen kicks in
        self._regen_fib = (1, 1)
        self.register_tick('hp_regen', 1000, self._do_hp_regen)

        # Stamina regen
        self.register_tick('stamina_regen', 1000, self._do_stamina_regen)

        # Mana regen
        self.register_tick('mana_regen', 1000, self._do_mana_regen)

    # -- Relationships ------------------------------------------------------

    def record_interaction(self, other: 'Creature', score: float):
        """Record an interaction with another creature.

        Args:
            other: the creature interacted with
            score: positive = good, negative = bad
        """
        uid = other.uid
        if uid in self.relationships:
            rel = self.relationships[uid]
            rel[0] += score       # sentiment
            rel[1] += 1           # count
            if score < rel[2]:
                rel[2] = score    # min_score
            if score > rel[3]:
                rel[3] = score    # max_score
        else:
            self.relationships[uid] = [score, 1, score, score]

    def get_relationship(self, other: 'Creature'):
        """Return (sentiment, count, min_score, max_score) or None."""
        return self.relationships.get(other.uid)

    def relationship_confidence(self, other: 'Creature') -> float:
        """Return 0.0–1.0 confidence based on interaction count."""
        rel = self.relationships.get(other.uid)
        if rel is None:
            return 0.0
        return rel[1] / (rel[1] + 5)

    def curiosity_toward(self, other: 'Creature') -> float:
        """Return curiosity score (high for strangers, decays with familiarity)."""
        rel = self.relationships.get(other.uid)
        if rel is None:
            return 1.0
        return 1 / (1 + rel[1])

    # -- Rumors -------------------------------------------------------------

    def receive_rumor(self, source: 'Creature', subject_uid: int,
                      sentiment: float, confidence: float, tick: int):
        """Receive a rumor about a third party from a source creature."""
        entry = (source.uid, sentiment, confidence, tick)
        if subject_uid in self.rumors:
            self.rumors[subject_uid].append(entry)
        else:
            self.rumors[subject_uid] = [entry]

    def rumor_opinion(self, subject_uid: int, current_tick: int,
                      decay_rate: float = 0.001) -> float:
        """Compute weighted opinion of a creature based on rumors.

        Weights: source_trust * confidence * time_decay.
        Returns 0.0 if no rumors exist.
        """
        rumors = self.rumors.get(subject_uid)
        if not rumors:
            return 0.0
        total_weight = 0.0
        weighted_sentiment = 0.0
        for source_uid, sentiment, confidence, tick in rumors:
            source_rel = self.relationships.get(source_uid)
            if source_rel is not None:
                # Trust the source based on our relationship with them
                source_trust = max(0.0, source_rel[0] / (abs(source_rel[0]) + 5))
            else:
                source_trust = 0.1  # slight trust for strangers
            age = current_tick - tick
            time_decay = 1 / (1 + decay_rate * age)
            weight = source_trust * confidence * time_decay
            weighted_sentiment += sentiment * weight
            total_weight += abs(weight)
        if total_weight == 0:
            return 0.0
        return weighted_sentiment / total_weight

    # -- Experience ---------------------------------------------------------

    def gain_exp(self, amount: int):
        self.stats.gain_exp(amount)

    # -- Timed behaviors ----------------------------------------------------

    def update(self, now: int, cols: int, rows: int):
        """Called each frame for non-player creatures."""
        self._cols = cols
        self._rows = rows
        self.process_ticks(now)

    def _do_behavior(self, _now: int):
        """Behavior think tick."""
        if self.behavior is not None:
            self.behavior.think(self, self._cols, self._rows)
        else:
            self.play_animation('idle')

    def on_hit(self, now: int):
        """Call when this creature takes damage. Resets HP regen timer."""
        delay_s = self.stats.active[Stat.HP_REGEN_DELAY]()
        self._regen_start = now + delay_s * 1000
        self._regen_fib = (1, 1)

    def _do_hp_regen(self, now: int):
        """Fibonacci HP regen, capped at 15% of HP_MAX per second."""
        if now < self._regen_start:
            return
        hp_curr = self.stats.active[Stat.HP_CURR]()
        hp_max = self.stats.active[Stat.HP_MAX]()
        if hp_curr >= hp_max:
            return
        cap = max(1, int(hp_max * 0.15))
        heal = min(self._regen_fib[0], cap)
        self.stats.base[Stat.HP_CURR] = min(hp_max, hp_curr + heal)
        self._regen_fib = (self._regen_fib[1], self._regen_fib[0] + self._regen_fib[1])

    def _do_stamina_regen(self, _now: int):
        """Restore stamina per second based on STAM_REGEN."""
        cur = self.stats.active[Stat.CUR_STAMINA]()
        mx = self.stats.active[Stat.MAX_STAMINA]()
        if cur >= mx:
            return
        regen = self.stats.active[Stat.STAM_REGEN]()
        self.stats.base[Stat.CUR_STAMINA] = min(mx, cur + regen)

    def _do_mana_regen(self, _now: int):
        """Restore mana per second based on MANA_REGEN."""
        cur = self.stats.active[Stat.CUR_MANA]()
        mx = self.stats.active[Stat.MAX_MANA]()
        if cur >= mx:
            return
        regen = self.stats.active[Stat.MANA_REGEN]()
        self.stats.base[Stat.CUR_MANA] = min(mx, cur + regen)

    # -- Movement -----------------------------------------------------------

    _DIR_BEHAVIORS = {
        (0, -1): 'walk_north', (0, 1): 'walk_south',
        (-1, 0): 'walk_west',  (1, 0): 'walk_east',
        (-1, -1): 'walk_north', (1, -1): 'walk_north',
        (-1,  1): 'walk_south', (1,  1): 'walk_south',
    }

    @staticmethod
    def _tile_blocked(game_map, x: int, y: int) -> bool:
        """Return True if any WorldObject with collision=True occupies (x, y)."""
        from classes.world_object import WorldObject
        from classes.inventory import Structure
        for obj in WorldObject.colliders_on_map(game_map):
            if isinstance(obj, Structure):
                ox, oy = obj.location.x, obj.location.y
                if (x - ox, y - oy) in obj.collision_mask:
                    return True
            elif obj.location.x == x and obj.location.y == y:
                return True
        return False

    def move(self, dx: int, dy: int, cols: int, rows: int):
        nx = max(0, min(cols - 1, self.location.x + dx))
        ny = max(0, min(rows - 1, self.location.y + dy))
        current_tile = self.current_map.tiles.get(self.location)
        target = self.current_map.tiles.get(MapKey(nx, ny, self.location.z))
        if not (target and target.walkable):
            return
        if current_tile and (dx, dy) in DIRECTION_BOUNDS:
            exit_attr, entry_attr = DIRECTION_BOUNDS[(dx, dy)]
            if not getattr(current_tile.bounds, exit_attr) or not getattr(target.bounds, entry_attr):
                return
        if self._tile_blocked(self.current_map, nx, ny):
            return
        self.location = self.location._replace(x=nx, y=ny)
        behavior = self._DIR_BEHAVIORS.get((dx, dy), 'walk_south')
        self.play_animation(behavior)
        # Auto-link: if the new tile has link_auto, teleport immediately
        landed = self.current_map.tiles.get(self.location)
        if landed and landed.link_auto and landed.linked_map:
            self._do_link(landed)

    # -- Map transitions ----------------------------------------------------

    def _do_link(self, tile):
        """Teleport to another map/location based on tile link fields."""
        from data.db import MAPS
        target_map = MAPS.get(tile.linked_map)
        if target_map is None:
            return False
        self.map_stack.append((self.current_map, self.location))
        self.current_map = target_map
        if tile.linked_location is not None:
            self.location = tile.linked_location
        else:
            self.location = MapKey(*target_map.entrance, 0)
        return True

    def enter(self):
        # Check tile link (enter-key triggered) first
        tile = self.current_map.tiles.get(self.location)
        if tile and tile.linked_map and not tile.link_auto:
            if self._do_link(tile):
                return True
        # Check tile nested maps
        if tile and tile.nested_map is not None:
            self.map_stack.append((self.current_map, self.location))
            self.current_map = tile.nested_map
            self.location = MapKey(*self.current_map.entrance, 0)
            return True
        # Check structure entry points
        from classes.inventory import Structure
        from data.db import MAPS
        px, py = self.location.x, self.location.y
        for s in WorldObject.on_map(self.current_map):
            if not isinstance(s, Structure) or not s.nested_map_name:
                continue
            offset = (px - s.location.x, py - s.location.y)
            offset_key = f'{offset[0]},{offset[1]}'
            if offset_key in s.entry_points or offset in s.footprint:
                nested = MAPS.get(s.nested_map_name)
                if nested is None:
                    continue
                self.map_stack.append((self.current_map, self.location))
                self.current_map = nested
                ep = s.entry_points.get(offset_key)
                if ep:
                    self.location = MapKey(ep[0], ep[1], 0)
                else:
                    self.location = MapKey(*self.current_map.entrance, 0)
                return True
        return False

    def exit(self):
        entrance = MapKey(*self.current_map.entrance, 0)
        if self.location == entrance:
            if self.map_stack:
                self.current_map, self.location = self.map_stack.pop()
                return True
        return False

    # -- Inventory ----------------------------------------------------------

    def transfer_item(self, item, source, target):
        tile = self.current_map.tiles.get(self.location)
        accessible = [self.inventory]
        if tile:
            accessible.append(tile.inventory)
            for creature in WorldObject.on_map(self.current_map):
                if isinstance(creature, Creature) and creature is not self and creature.location == self.location:
                    accessible.append(creature.inventory)
        if source not in accessible or target not in accessible:
            return False
        if item not in source.items:
            return False
        source.items.remove(item)
        target.items.append(item)
        return True


# ---------------------------------------------------------------------------
# Built-in behavior modules
# ---------------------------------------------------------------------------

class RandomWanderBehavior:
    """Simple behavior: move in a random direction each think tick."""

    def think(self, creature: Creature, cols: int, rows: int):
        dx, dy = random.choice([
            (-1, -1), (0, -1), (1, -1),
            (-1,  0),          (1,  0),
            (-1,  1), (0,  1), (1,  1),
        ])
        creature.move(dx, dy, cols, rows)
