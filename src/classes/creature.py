from __future__ import annotations
import random
from classes.maps import Map, MapKey, DIRECTION_BOUNDS
from classes.inventory import Inventory, Equippable, Consumable, Weapon, Slot
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
        sex: str = None,
        prudishness: float = None,
        age: int = 0,
    ):
        super().__init__(current_map=current_map, location=location)
        self.name = name
        self.species = species

        from data.db import SPECIES
        species_data = SPECIES.get(species, {}) if species else {}
        self.tile_scale     = species_data.get('tile_scale',     self.__class__.tile_scale)
        self.sprite_name    = species_data.get('sprite_name',    self.__class__.sprite_name)
        self.composite_name = species_data.get('composite_name', self.__class__.composite_name)

        # Sex: per-creature, randomly assigned if not specified
        self.sex = sex if sex is not None else random.choice(('male', 'female'))
        # Prudishness: species default with per-creature override
        self.prudishness = prudishness if prudishness is not None else species_data.get('prudishness', 0.5)
        # Age in game ticks (0 = newborn)
        self.age = age

        # Build Stats from species defaults + overrides
        species_stats = {k: v for k, v in species_data.items() if isinstance(k, Stat)}
        merged = {**species_stats, **(stats or {})}
        hd = merged.pop(Stat.HIT_DICE, 6)
        self.stats = Stats(base_stats=merged, hit_dice=hd)

        self.inventory = Inventory(items=items or [])
        self.equipment: dict[Slot, Equippable] = {}
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

    # -- Equipment ----------------------------------------------------------

    def equip(self, item: Equippable) -> bool:
        """Equip an item from inventory into the first available slot(s).

        Returns True if equipped, False if no valid slot is free or item
        is not in inventory.
        """
        if not isinstance(item, Equippable) or item not in self.inventory.items:
            return False
        if not item.slots:
            return False

        # Check stat requirements
        for stat, min_val in item.requirements.items():
            if self.stats.active[stat]() < min_val:
                return False

        # Find slot_count free slots from the item's allowed slots
        free = [s for s in item.slots if s not in self.equipment]
        if len(free) < item.slot_count:
            return False
        chosen = free[:item.slot_count]

        # Move from inventory to equipment
        self.inventory.items.remove(item)
        for slot in chosen:
            self.equipment[slot] = item

        # Apply buffs as stat mods
        source = f'equip_{item.uid}'
        for stat, amount in item.buffs.items():
            self.stats.add_mod(source, stat, amount)

        return True

    def unequip(self, slot: Slot) -> bool:
        """Unequip the item in the given slot back to inventory.

        Returns True if an item was removed, False if slot was empty.
        """
        item = self.equipment.get(slot)
        if item is None:
            return False

        # Remove from all slots this item occupies
        slots_to_clear = [s for s, i in self.equipment.items() if i is item]
        for s in slots_to_clear:
            del self.equipment[s]

        # Remove stat mods
        self.stats.remove_mods_by_source(f'equip_{item.uid}')

        # Return to inventory
        self.inventory.items.append(item)
        return True

    def equipped_in(self, slot: Slot) -> Equippable | None:
        """Return the item equipped in the given slot, or None."""
        return self.equipment.get(slot)

    # -- Inventory ----------------------------------------------------------

    @property
    def carried_weight(self) -> float:
        """Total weight of inventory + equipped items."""
        inv_weight = sum(getattr(i, 'weight', 0) for i in self.inventory.items)
        # Equipped items: use a set to avoid double-counting multi-slot items
        eq_weight = sum(getattr(i, 'weight', 0) for i in set(self.equipment.values()))
        return inv_weight + eq_weight

    def can_carry(self, item) -> bool:
        """Return True if picking up this item would not exceed CARRY_WEIGHT."""
        return self.carried_weight + getattr(item, 'weight', 0) <= self.stats.active[Stat.CARRY_WEIGHT]()

    def pickup(self, item) -> bool:
        """Pick up an item from the current tile's inventory.

        Checks: item is on the tile, item is inventoriable, weight fits.
        Returns True if picked up.
        """
        tile = self.current_map.tiles.get(self.location)
        if tile is None or item not in tile.inventory.items:
            return False
        if not getattr(item, 'inventoriable', True):
            return False
        if not self.can_carry(item):
            return False
        tile.inventory.items.remove(item)
        self.inventory.items.append(item)
        return True

    def drop(self, item) -> bool:
        """Drop an item from inventory onto the current tile.

        Returns True if dropped.
        """
        if item not in self.inventory.items:
            return False
        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            return False
        self.inventory.items.remove(item)
        tile.inventory.items.append(item)
        return True

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

    # -- Use / Consume ------------------------------------------------------

    def use_item(self, item: Consumable) -> bool:
        """Consume one charge of a consumable item.

        Applies buffs as timed stat mods (duration in seconds).
        Decrements quantity; removes from inventory when empty.
        Returns True if consumed.
        """
        if not isinstance(item, Consumable) or item not in self.inventory.items:
            return False
        if item.quantity <= 0:
            return False

        # Apply buffs as stat mods
        source = f'consumable_{item.uid}_{item.quantity}'
        for stat, amount in item.buffs.items():
            self.stats.add_mod(source, stat, amount)

        # Decrement stack
        item.quantity -= 1
        if item.quantity <= 0:
            self.inventory.items.remove(item)

        return True

    # -- Combat -------------------------------------------------------------

    def _sight_distance(self, other: 'Creature') -> int:
        """Manhattan distance between self and other."""
        return abs(self.location.x - other.location.x) + abs(self.location.y - other.location.y)

    def can_see(self, other: 'Creature') -> bool:
        """Return True if other is within effective sight range."""
        effective_range = self.stats.active[Stat.SIGHT_RANGE]() - other.stats.active[Stat.STEALTH]()
        return self._sight_distance(other) <= effective_range

    def melee_attack(self, target: 'Creature', now: int) -> dict:
        """Execute a melee attack against an adjacent creature.

        Returns a result dict with keys:
            hit: bool, damage: int, crit: bool, staggered: bool,
            reason: str (if miss/fail)
        """
        result = {'hit': False, 'damage': 0, 'crit': False,
                  'staggered': False, 'betrayal': False, 'reason': ''}

        # Must be adjacent (Manhattan distance 1)
        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        # Weapon check — get equipped weapon or use unarmed defaults
        weapon = self.equipment.get(Slot.HAND_R) or self.equipment.get(Slot.HAND_L)
        if weapon and isinstance(weapon, Weapon):
            weapon_dmg = weapon.damage
            weapon_dc = getattr(weapon, 'damage', 5)  # armor DC
            weapon_impact = weapon_dmg  # stagger force scales with damage
            stamina_cost = max(5, 10 - (self.stats.active[Stat.STR]() - 10) // 2)
        else:
            # Unarmed
            weapon_dmg = 0
            weapon_dc = 3
            weapon_impact = 2
            stamina_cost = 5

        # Stamina check
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stamina_cost:
            result['reason'] = 'no_stamina'
            return result
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stamina_cost

        # Betrayal check: the ACT of attacking someone with positive history
        # triggers regardless of whether the attack hits
        rel = self.get_relationship(target)
        if rel and rel[0] > 0:
            self.record_interaction(target, -10.0)
            target.record_interaction(self, -10.0)
            result['betrayal'] = True

        # Can defender see attacker? If not, auto-hit (ambush)
        ambush = not target.can_see(self)
        if not ambush:
            # Defender picks dodge (default active defense)
            hit_won, _ = self.stats.contest(target.stats, 'accuracy_vs_dodge')
            if not hit_won:
                result['reason'] = 'dodged'
                target.record_interaction(self, -1.0)
                return result

        # Hit lands — armor resist check
        armor_blocked = target.stats.resist_check(weapon_dc, Stat.ARMOR)
        if armor_blocked:
            result['reason'] = 'armor_absorbed'
            result['hit'] = True
            result['damage'] = 0
            target.on_hit(now)
            target.record_interaction(self, -2.0)
            return result

        # Damage calculation
        str_mod = (self.stats.active[Stat.STR]() - 10) // 2
        base_dmg = str_mod + weapon_dmg
        # Lucky STR bonus: (LCK+1)/(LCK+2) chance of adding STR mod again
        lck = self.stats.active[Stat.LCK]()
        lucky_chance = (lck + 1) / (lck + 2) if lck + 2 > 0 else 0
        if random.random() < lucky_chance:
            base_dmg += max(0, str_mod)

        # Crit check
        crit_chance = self.stats.active[Stat.CRIT_CHANCE]()
        crit = random.randint(1, 100) <= crit_chance
        if crit:
            result['crit'] = True
            base_dmg = base_dmg * 2 + str_mod

        damage = max(1, base_dmg)
        result['hit'] = True
        result['damage'] = damage

        # Apply damage
        hp = target.stats.active[Stat.HP_CURR]()
        target.stats.base[Stat.HP_CURR] = max(0, hp - damage)

        # Stagger check
        staggered = not target.stats.resist_check(weapon_impact, Stat.STAGGER_RESIST)
        result['staggered'] = staggered

        # Reset defender's HP regen
        target.on_hit(now)

        # Record combat interaction
        target.record_interaction(self, -5.0)

        return result

    # -- Social Actions -----------------------------------------------------

    def intimidate(self, target: 'Creature') -> dict:
        """Attempt to intimidate another creature.

        Uses d20 + INTIMIDATION vs d20 + FEAR_RESIST.
        Returns dict: success, margin, reason.
        """
        result = {'success': False, 'margin': 0, 'reason': ''}

        # Must be within sight range
        if not self.can_see(target):
            result['reason'] = 'out_of_range'
            return result

        won, margin = self.stats.contest(target.stats, 'intimidation_vs_fear')
        result['margin'] = margin
        if won:
            result['success'] = True
            # Target may accept dominance — slight positive for intimidator
            target.record_interaction(self, -3.0)
            self.record_interaction(target, 1.0)
        else:
            result['reason'] = 'resisted'
            # Both take a social hit
            self.record_interaction(target, -2.0)
            target.record_interaction(self, -1.0)

        return result

    def deceive(self, target: 'Creature') -> dict:
        """Attempt to deceive another creature.

        Uses d20 + DECEPTION vs d20 + DETECTION.
        Returns dict: success, margin, reason.
        """
        result = {'success': False, 'margin': 0, 'reason': ''}

        if not self.can_see(target):
            result['reason'] = 'out_of_range'
            return result

        won, margin = self.stats.contest(target.stats, 'deception_vs_detection')
        result['margin'] = margin
        if won:
            result['success'] = True
            # Victim doesn't know they've been deceived
        else:
            result['reason'] = 'detected'
            # Trust severely damaged
            target.record_interaction(self, -5.0)
            self.record_interaction(target, -1.0)

        return result


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
