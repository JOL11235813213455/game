from __future__ import annotations
import random
from classes.maps import Map, MapKey, DIRECTION_BOUNDS
from classes.inventory import (
    Inventory, Equippable, Consumable, Weapon, Ammunition, Slot,
)
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

        # Sleep deprivation
        self.sleep_debt: int = 0  # days without sleep
        self._fatigue_level: int = 0  # current debuff tier (0-4)

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

        # Trap check on the landed tile
        landed = self.current_map.tiles.get(self.location)
        if landed:
            self._check_trap(landed)

        # Auto-link: if the new tile has link_auto, teleport immediately
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

    _next_consumable_id = 0

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

        # Apply buffs as stat mods with unique source key
        Creature._next_consumable_id += 1
        source = f'consumable_{Creature._next_consumable_id}'
        for stat, amount in item.buffs.items():
            self.stats.add_mod(source, stat, amount)

        # Schedule expiry if duration > 0
        if item.duration > 0:
            tick_name = f'expire_{source}'
            interval_ms = int(item.duration * 1000)
            def _expire(_now, s=source, tn=tick_name):
                self.stats.remove_mods_by_source(s)
                self.unregister_tick(tn)
            self.register_tick(tick_name, interval_ms, _expire)

        # Decrement stack
        item.quantity -= 1
        if item.quantity <= 0:
            self.inventory.items.remove(item)

        return True

    # -- Death / Alive ------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self.stats.active[Stat.HP_CURR]() > 0

    def die(self):
        """Handle creature death: drop inventory on tile, remove from map."""
        # Drop all inventory items on current tile
        tile = self.current_map.tiles.get(self.location)
        if tile:
            for item in list(self.inventory.items):
                tile.inventory.items.append(item)
            self.inventory.items.clear()

            # Drop equipped items too
            for item in set(self.equipment.values()):
                tile.inventory.items.append(item)
                # Remove stat mods
                self.stats.remove_mods_by_source(f'equip_{item.uid}')
            self.equipment.clear()

        self.play_animation('death')

    def _check_trap(self, tile):
        """Check if a tile has a trap and resolve it against this creature."""
        trap_dc = tile.stat_mods.get('trap_dc')
        if trap_dc is None:
            return

        # Detection check: d20 + DETECTION vs trap_dc
        detection = self.stats.active[Stat.DETECTION]()
        roll = random.randint(1, 20) + detection
        if roll >= trap_dc:
            # Detected — trap is revealed but not triggered
            return

        # Trap triggered — find trap item on tile
        trap_name = tile.stat_mods.get('trap_item', '')
        trap_item = None
        for item in tile.inventory.items:
            if item.name == trap_name:
                trap_item = item
                break

        # Apply trap damage (trap_dc as rough damage proxy)
        damage = max(1, trap_dc // 2)
        hp = self.stats.active[Stat.HP_CURR]()
        self.stats.base[Stat.HP_CURR] = max(0, hp - damage)
        self.on_hit(0)

        # Remove trap after triggering
        if trap_item:
            tile.inventory.items.remove(trap_item)
        tile.stat_mods.pop('trap_dc', None)
        tile.stat_mods.pop('trap_item', None)

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

    def ranged_attack(self, target: 'Creature', now: int) -> dict:
        """Execute a ranged attack against a creature within weapon range.

        Requires a ranged weapon equipped and matching ammunition in inventory.
        Returns result dict: hit, damage, crit, reason.
        """
        result = {'hit': False, 'damage': 0, 'crit': False, 'reason': ''}

        # Weapon check — need a ranged weapon (range > 1)
        weapon = self.equipment.get(Slot.HAND_R) or self.equipment.get(Slot.HAND_L)
        if not weapon or not isinstance(weapon, Weapon) or weapon.range <= 1:
            result['reason'] = 'no_ranged_weapon'
            return result

        # Range check
        dist = self._sight_distance(target)
        if dist > weapon.range:
            result['reason'] = 'out_of_range'
            return result
        if dist < 1:
            result['reason'] = 'too_close'
            return result

        # Ammo check
        ammo = None
        if weapon.ammunition_type:
            for item in self.inventory.items:
                if isinstance(item, Ammunition) and item.name == weapon.ammunition_type and item.quantity > 0:
                    ammo = item
                    break
            if ammo is None:
                result['reason'] = 'no_ammo'
                return result

        # Stamina cost
        stamina_cost = max(3, 8 - (self.stats.active[Stat.STR]() - 10) // 2)
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stamina_cost:
            result['reason'] = 'no_stamina'
            return result
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stamina_cost

        # Betrayal check
        rel = self.get_relationship(target)
        if rel and rel[0] > 0:
            self.record_interaction(target, -10.0)
            target.record_interaction(self, -10.0)
            result['betrayal'] = True

        # Consume one ammo unit up front
        ammo_dmg = 0
        if ammo:
            ammo_dmg = ammo.damage
            ammo.quantity -= 1
            if ammo.quantity <= 0:
                self.inventory.items.remove(ammo)

        def _drop_ammo_on_tile():
            """Recoverable ammo lands on the target's tile on miss."""
            if ammo and ammo.recoverable:
                tile = target.current_map.tiles.get(target.location)
                if tile is not None:
                    # Create a single recovered projectile on the tile
                    recovered = Ammunition(
                        name=ammo.name, weight=ammo.weight, quantity=1,
                        damage=ammo.damage,
                        destroy_on_use_probability=ammo.destroy_on_use_probability,
                        recoverable=ammo.recoverable,
                    )
                    tile.inventory.items.append(recovered)

        # Accuracy at distance
        hit_prob = self.stats.accuracy_at_distance(dist)
        if random.random() > hit_prob:
            result['reason'] = 'missed'
            _drop_ammo_on_tile()
            if target.can_see(self):
                target.record_interaction(self, -1.0)
            return result

        # Dodge contest if defender can see attacker
        if target.can_see(self):
            hit_won, _ = self.stats.contest(target.stats, 'accuracy_vs_dodge')
            if not hit_won:
                result['reason'] = 'dodged'
                _drop_ammo_on_tile()
                target.record_interaction(self, -1.0)
                return result

        # Armor resist
        weapon_dc = weapon.damage
        armor_blocked = target.stats.resist_check(weapon_dc, Stat.ARMOR)
        if armor_blocked:
            result['hit'] = True
            result['damage'] = 0
            result['reason'] = 'armor_absorbed'
            target.on_hit(now)
            target.record_interaction(self, -2.0)
            return result

        # Damage: weapon + ammo + STR if weapon requires it (bows)
        base_dmg = weapon.damage + ammo_dmg

        # Crit check
        crit_chance = self.stats.active[Stat.CRIT_CHANCE]()
        crit = random.randint(1, 100) <= crit_chance
        if crit:
            result['crit'] = True
            base_dmg *= 2

        damage = max(1, base_dmg)
        result['hit'] = True
        result['damage'] = damage

        # Apply damage
        hp = target.stats.active[Stat.HP_CURR]()
        target.stats.base[Stat.HP_CURR] = max(0, hp - damage)
        target.on_hit(now)

        # Record interaction
        if target.can_see(self):
            target.record_interaction(self, -5.0)

        return result

    def grapple(self, target: 'Creature') -> dict:
        """Initiate a grapple with an adjacent creature.

        Contest: d20 + max(STR, AGL) vs d20 + max(STR, AGL-1).
        High stamina cost. Loser takes social/dominance hit.
        Returns dict: success, margin, reason.
        """
        result = {'success': False, 'margin': 0, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        # High stamina cost
        stamina_cost = 15
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stamina_cost:
            result['reason'] = 'no_stamina'
            return result
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stamina_cost

        # Attacker: max(STR, AGL)
        atk_str = self.stats.active[Stat.STR]()
        atk_agl = self.stats.active[Stat.AGL]()
        atk_val = max(atk_str, atk_agl) + random.randint(1, 20)

        # Defender: max(STR, AGL-1) — slight agility disadvantage
        def_str = target.stats.active[Stat.STR]()
        def_agl = target.stats.active[Stat.AGL]() - 1
        def_val = max(def_str, def_agl) + random.randint(1, 20)

        margin = atk_val - def_val
        result['margin'] = margin

        if margin > 0:
            result['success'] = True
            # Winner dominance: positive for self, negative for loser
            self.record_interaction(target, 2.0)
            target.record_interaction(self, -5.0)
        else:
            result['reason'] = 'escaped'
            # Loser takes social hit, both negative
            self.record_interaction(target, -3.0)
            target.record_interaction(self, -2.0)

        return result

    # -- Conversation -------------------------------------------------------

    def start_conversation(self, target: 'Creature', conversation: str = None) -> list:
        """Start a conversation with another creature.

        Finds matching root dialogue nodes filtered by species/creature/conditions.
        Returns list of available root node dicts, or empty if none match.
        """
        from data.db import DIALOGUE, DIALOGUE_ROOTS

        if not self.can_see(target):
            return []

        # Determine which conversation trees to search
        if conversation:
            candidates = DIALOGUE_ROOTS.get(conversation, [])
        else:
            # Search all conversation trees for matching roots
            candidates = []
            for conv_roots in DIALOGUE_ROOTS.values():
                candidates.extend(conv_roots)

        available = []
        for node_id in candidates:
            node = DIALOGUE.get(node_id)
            if node is None:
                continue
            if not self._dialogue_matches(node, target):
                continue
            available.append(node)

        if available:
            self.dialogue = {
                'target_uid': target.uid,
                'conversation': conversation or available[0]['conversation'],
                'current_node_id': None,
            }
            # Record social interaction for starting a conversation
            self.record_interaction(target, 1.0)
            target.record_interaction(self, 1.0)

        return available

    def advance_dialogue(self, node_id: int, target: 'Creature') -> list:
        """Select a dialogue node and get its children (next options).

        Applies any effects/behavior from the selected node.
        Returns list of available child node dicts.
        """
        from data.db import DIALOGUE

        node = DIALOGUE.get(node_id)
        if node is None:
            return []

        # Update conversation state
        if self.dialogue:
            self.dialogue['current_node_id'] = node_id

        # Apply effects
        self._apply_dialogue_effects(node, target)

        # Get filtered children
        children = []
        for child_id in node['children']:
            child = DIALOGUE.get(child_id)
            if child and self._dialogue_matches(child, target):
                children.append(child)

        # No children = end of conversation
        if not children:
            self.end_conversation()

        return children

    def end_conversation(self):
        """End the current conversation."""
        self.dialogue = None

    def _dialogue_matches(self, node: dict, target: 'Creature') -> bool:
        """Check if a dialogue node matches the current context.

        Filters on species, creature_key, and JSON conditions.
        """
        # Species filter
        if node['species'] and node['species'] != (target.species or ''):
            return False

        # Creature key filter (specific NPC)
        if node['creature_key'] and node['creature_key'] != target.name:
            return False

        # Character conditions (checked against the initiator/player)
        for key, val in node['char_conditions'].items():
            if key == 'level_min':
                if self.stats.base.get(Stat.LVL, 0) < val:
                    return False
            elif key == 'sex':
                if self.sex != val:
                    return False
            elif key == 'species':
                if self.species != val:
                    return False

        # World/quest conditions are checked against a global state dict
        # that doesn't exist yet — pass through for now
        # (These will be wired when quest/world state systems are built)

        return True

    def _apply_dialogue_effects(self, node: dict, target: 'Creature'):
        """Apply effects from a selected dialogue node."""
        effects = node.get('effects', {})
        if not effects:
            return

        # Give item to player
        if 'give_item' in effects:
            from data.db import ITEMS
            item_template = ITEMS.get(effects['give_item'])
            if item_template:
                # Clone the item (simple approach: same type, same args)
                import copy
                new_item = copy.copy(item_template)
                self.inventory.items.append(new_item)

        # Take item from player
        if 'take_item' in effects:
            item_name = effects['take_item']
            for item in list(self.inventory.items):
                if item.name == item_name:
                    self.inventory.items.remove(item)
                    break

        # Sentiment shift
        if 'sentiment' in effects:
            self.record_interaction(target, effects['sentiment'])
            target.record_interaction(self, effects['sentiment'])

        # Behavior trigger
        behavior = node.get('behavior')
        if behavior == 'trade':
            pass  # Caller handles opening trade UI
        elif behavior == 'attack':
            pass  # Caller handles initiating combat
        elif behavior == 'flee':
            pass  # Caller handles flee logic

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

    @staticmethod
    def _item_utility(items: list, creature: 'Creature') -> float:
        """Compute total utility of a bundle of items to a creature.

        Base = sum of item values. Adjusted by creature needs:
        - Weapons are worth more if creature has none equipped
        - Consumables worth more if HP is low
        """
        total = 0.0
        for item in items:
            base = getattr(item, 'value', 0)
            # Need-based adjustments
            if isinstance(item, Weapon):
                has_weapon = any(isinstance(e, Weapon) for e in creature.equipment.values())
                if not has_weapon:
                    base *= 1.5
            if isinstance(item, Consumable):
                hp_ratio = creature.stats.active[Stat.HP_CURR]() / max(1, creature.stats.active[Stat.HP_MAX]())
                if hp_ratio < 0.5:
                    base *= 1.5
            total += base
        return total

    def propose_trade(self, target: 'Creature',
                      offered: list, requested: list) -> dict:
        """Propose a trade: self offers items, requests items from target.

        Both sides evaluate utility. Sentiment shifts willingness.
        Persuasion bonus for initiator.
        Returns dict: accepted, counter_offer (list or None), reason.
        """
        result = {'accepted': False, 'counter_offer': None, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        # Validate items exist in inventories
        for item in offered:
            if item not in self.inventory.items:
                result['reason'] = 'missing_offered_item'
                return result
        for item in requested:
            if item not in target.inventory.items:
                result['reason'] = 'missing_requested_item'
                return result

        # Compute utility for both sides
        # Target gains offered items, loses requested items
        target_gain = self._item_utility(offered, target)
        target_loss = self._item_utility(requested, target)

        # Self gains requested items, loses offered items
        self_gain = self._item_utility(requested, self)
        self_loss = self._item_utility(offered, self)

        # Sentiment modifier: positive relationship = more generous
        rel = target.get_relationship(self)
        sentiment_bonus = 0.0
        if rel:
            # Normalize sentiment to a small bonus/penalty
            sentiment_bonus = rel[0] / (abs(rel[0]) + 10)  # -1 to +1 range

        # Persuasion bonus for initiator
        persuasion = (self.stats.active[Stat.PERSUASION]() * 0.05)

        # Target's net utility including social factors
        target_net = (target_gain - target_loss) + sentiment_bonus + persuasion

        if target_net >= 0:
            # Accept trade
            result['accepted'] = True
            # Execute the swap
            for item in offered:
                self.inventory.items.remove(item)
                target.inventory.items.append(item)
            for item in requested:
                target.inventory.items.remove(item)
                self.inventory.items.append(item)

            # Fair or exploitative?
            self_net = self_gain - self_loss
            if abs(self_net - target_net) < 2.0:
                # Fair trade
                self.record_interaction(target, 3.0)
                target.record_interaction(self, 3.0)
            else:
                # One side got a better deal
                winner_sentiment = 3.0
                loser_sentiment = -1.0
                if self_net > target_net:
                    self.record_interaction(target, winner_sentiment)
                    target.record_interaction(self, loser_sentiment)
                else:
                    self.record_interaction(target, loser_sentiment)
                    target.record_interaction(self, winner_sentiment)
        else:
            result['reason'] = 'rejected'
            # Walk-away
            self.record_interaction(target, -1.0)
            target.record_interaction(self, -1.0)

        return result

    def bribe(self, target: 'Creature', items: list) -> dict:
        """Offer items as a bribe to shift target's behavior/sentiment.

        Target evaluates bribe value against current disposition.
        Returns dict: accepted, reason.
        """
        result = {'accepted': False, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        for item in items:
            if item not in self.inventory.items:
                result['reason'] = 'missing_item'
                return result

        bribe_value = self._item_utility(items, target)

        # Threshold based on target's current sentiment toward self
        rel = target.get_relationship(self)
        threshold = 5.0  # base threshold
        if rel:
            # More negative sentiment = higher bribe needed
            threshold = max(1.0, 5.0 - rel[0] * 0.5)

        if bribe_value >= threshold:
            result['accepted'] = True
            # Transfer items
            for item in items:
                self.inventory.items.remove(item)
                target.inventory.items.append(item)
            # Positive sentiment shift
            target.record_interaction(self, bribe_value * 0.5)
            self.record_interaction(target, 1.0)
        else:
            result['reason'] = 'insufficient_value'
            # Minor negative
            self.record_interaction(target, -0.5)
            target.record_interaction(self, -0.5)

        return result

    def steal(self, target: 'Creature', item) -> dict:
        """Attempt to steal an item from another creature's inventory.

        Uses stealth vs detection if unseen, deception vs detection if seen.
        Returns dict: success, reason.
        """
        result = {'success': False, 'reason': ''}

        if self._sight_distance(target) > 1:
            result['reason'] = 'not_adjacent'
            return result

        if item not in target.inventory.items:
            result['reason'] = 'item_not_found'
            return result

        if not self.can_carry(item):
            result['reason'] = 'too_heavy'
            return result

        # If target can see us, use deception; otherwise stealth
        if target.can_see(self):
            won, _ = self.stats.contest(target.stats, 'deception_vs_detection')
        else:
            won, _ = self.stats.contest(target.stats, 'stealth_vs_detection')

        if won:
            result['success'] = True
            target.inventory.items.remove(item)
            self.inventory.items.append(item)
            # Victim doesn't know (unless detected later)
        else:
            result['reason'] = 'caught'
            # Caught stealing — severe trust damage
            target.record_interaction(self, -8.0)
            self.record_interaction(target, -2.0)

        return result

    def share_rumor(self, target: 'Creature', subject_uid: int,
                    sentiment: float, tick: int) -> bool:
        """Share a rumor about a third party with another creature.

        CHR scales gossip success. Returns True if rumor was shared.
        """
        if not self.can_see(target):
            return False

        # CHR check: higher CHR = more convincing gossip
        chr_mod = (self.stats.active[Stat.CHR]() - 10) // 2
        # Base 60% chance + 5% per CHR mod
        chance = min(0.95, max(0.1, 0.6 + chr_mod * 0.05))
        if random.random() > chance:
            return False

        confidence = self.relationship_confidence(
            type('_', (), {'uid': subject_uid})()  # dummy for lookup
        ) if subject_uid in self.relationships else 0.1

        target.receive_rumor(self, subject_uid, sentiment, confidence, tick)

        # Sharing is a social interaction
        self.record_interaction(target, 1.0)
        target.record_interaction(self, 1.0)
        return True

    # -- Utility Actions ----------------------------------------------------

    def flee(self, threat: 'Creature', cols: int, rows: int) -> bool:
        """Move one tile away from the threat creature.

        Picks the direction that maximizes distance. Costs stamina (run cost).
        Returns True if moved.
        """
        # Stamina cost for fleeing (running)
        stam_cost = 3
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stam_cost:
            return False
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stam_cost

        # Pick direction away from threat
        dx = self.location.x - threat.location.x
        dy = self.location.y - threat.location.y
        # Normalize to -1/0/1
        mdx = (1 if dx > 0 else (-1 if dx < 0 else 0))
        mdy = (1 if dy > 0 else (-1 if dy < 0 else 0))

        if mdx == 0 and mdy == 0:
            # On same tile — pick random direction
            mdx, mdy = random.choice([(1,0),(-1,0),(0,1),(0,-1)])

        old_loc = self.location
        self.move(mdx, mdy, cols, rows)
        return self.location != old_loc

    def search_tile(self) -> dict:
        """Search the current tile for items.

        Reveals tile inventory. Hidden items require DETECTION check.
        Returns dict: items_found (list), hidden_found (list).
        """
        result = {'items_found': [], 'hidden_found': []}

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            return result

        # Visible items are always found
        result['items_found'] = list(tile.inventory.items)

        # Hidden items: check tile stat_mods for 'hidden_dc'
        hidden_dc = tile.stat_mods.get('hidden_dc', 0)
        if hidden_dc > 0:
            detection = self.stats.active[Stat.DETECTION]()
            roll = random.randint(1, 20) + detection
            if roll >= hidden_dc:
                result['hidden_found'] = True
            else:
                result['hidden_found'] = False

        return result

    def guard(self, cols: int, rows: int) -> bool:
        """Enter guard stance on current tile.

        Drains stamina over time. While guarding, creature doesn't move
        and gets a bonus to detection.
        Returns True if guard stance entered (has enough stamina).
        """
        stam_cost = 2
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stam_cost:
            return False
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stam_cost

        # Add guard detection bonus if not already guarding
        if not hasattr(self, '_guarding') or not self._guarding:
            self._guarding = True
            self._guard_mod = self.stats.add_mod('guard_stance', Stat.DETECTION, 3)
        return True

    def stop_guard(self):
        """Exit guard stance, remove detection bonus."""
        if getattr(self, '_guarding', False):
            self._guarding = False
            if hasattr(self, '_guard_mod'):
                self.stats.remove_mod(self._guard_mod)

    def wait(self) -> bool:
        """Skip turn and recover a small amount of stamina.

        Returns True always (waiting always succeeds).
        """
        regen = max(1, self.stats.active[Stat.STAM_REGEN]())
        cur = self.stats.active[Stat.CUR_STAMINA]()
        mx = self.stats.active[Stat.MAX_STAMINA]()
        self.stats.base[Stat.CUR_STAMINA] = min(mx, cur + regen)
        return True

    def follow(self, target: 'Creature', cols: int, rows: int) -> bool:
        """Move one tile toward the target creature.

        Returns True if moved.
        """
        dx = target.location.x - self.location.x
        dy = target.location.y - self.location.y
        mdx = (1 if dx > 0 else (-1 if dx < 0 else 0))
        mdy = (1 if dy > 0 else (-1 if dy < 0 else 0))

        if mdx == 0 and mdy == 0:
            return False  # Already at target

        old_loc = self.location
        self.move(mdx, mdy, cols, rows)
        return self.location != old_loc

    def call_backup(self) -> list['Creature']:
        """Broadcast a call for help within hearing range.

        Returns list of creatures that could potentially respond
        (within their HEARING_RANGE of the caller, with positive sentiment).
        """
        responders = []
        for obj in WorldObject.on_map(self.current_map):
            if not isinstance(obj, Creature) or obj is self:
                continue
            dist = self._sight_distance(obj)
            # Responder must be within THEIR hearing range of the caller
            hearing = obj.stats.active[Stat.HEARING_RANGE]()
            if dist > hearing:
                continue
            # Check relationship: only allies respond
            rel = obj.get_relationship(self)
            if rel is None or rel[0] <= 0:
                continue
            responders.append(obj)
            # Calling for help is a positive interaction
            self.record_interaction(obj, 1.0)
        return responders

    def sleep(self, now: int) -> bool:
        """Enter sleep state. Vulnerable but restores resources.

        Fully restores stamina and mana. Clears sleep debt.
        Sets a flag for vulnerability (reduced detection, no dodge/block).
        Returns True if entered sleep.
        """
        if getattr(self, '_sleeping', False):
            return False  # Already sleeping

        self._sleeping = True
        # Full stamina and mana restore
        self.stats.base[Stat.CUR_STAMINA] = self.stats.active[Stat.MAX_STAMINA]()
        self.stats.base[Stat.CUR_MANA] = self.stats.active[Stat.MAX_MANA]()
        # Reduced detection while sleeping
        self._sleep_mod = self.stats.add_mod('sleep', Stat.DETECTION, -5)
        # Clear sleep debt and fatigue debuffs
        self.sleep_debt = 0
        self._update_fatigue()
        return True

    def wake(self):
        """Exit sleep state."""
        if getattr(self, '_sleeping', False):
            self._sleeping = False
            if hasattr(self, '_sleep_mod'):
                self.stats.remove_mod(self._sleep_mod)

    @property
    def is_sleeping(self) -> bool:
        return getattr(self, '_sleeping', False)

    def add_sleep_debt(self, days: int = 1):
        """Increment sleep debt (called once per day cycle).

        Fatigue debuffs stack at thresholds:
          1 day  → mild: -1 STR, -1 AGL, -1 PER
          2 days → exhaustion: -2 STR, -2 AGL, -2 PER, -1 STAM_REGEN
          3 days → severe: -3 all base stats, -2 DETECTION, -2 ACCURACY
          4 days → collapse: forced sleep (creature is vulnerable)
        """
        self.sleep_debt += days
        self._update_fatigue()

    def _update_fatigue(self):
        """Apply or remove fatigue debuffs based on current sleep debt."""
        # Remove old fatigue mods
        self.stats.remove_mods_by_source('fatigue')

        if self.sleep_debt <= 0:
            self._fatigue_level = 0
            return

        if self.sleep_debt >= 4:
            self._fatigue_level = 4
            # Collapse — forced sleep applied by caller
        elif self.sleep_debt >= 3:
            self._fatigue_level = 3
            for stat in (Stat.STR, Stat.AGL, Stat.PER, Stat.INT, Stat.CHR, Stat.VIT, Stat.LCK):
                self.stats.add_mod('fatigue', stat, -3)
            self.stats.add_mod('fatigue', Stat.DETECTION, -2)
            self.stats.add_mod('fatigue', Stat.ACCURACY, -2)
        elif self.sleep_debt >= 2:
            self._fatigue_level = 2
            for stat in (Stat.STR, Stat.AGL, Stat.PER):
                self.stats.add_mod('fatigue', stat, -2)
            self.stats.add_mod('fatigue', Stat.STAM_REGEN, -1)
        elif self.sleep_debt >= 1:
            self._fatigue_level = 1
            for stat in (Stat.STR, Stat.AGL, Stat.PER):
                self.stats.add_mod('fatigue', stat, -1)

    @property
    def fatigue_level(self) -> int:
        """0=rested, 1=mild, 2=exhaustion, 3=severe, 4=collapse."""
        return self._fatigue_level

    def set_trap(self, trap_item, dc: int = 10) -> bool:
        """Place a trap item on the current tile.

        The trap is removed from inventory and stored on the tile.
        dc = difficulty class for creatures to detect/avoid the trap.
        Returns True if trap was placed.
        """
        if trap_item not in self.inventory.items:
            return False

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            return False

        self.inventory.items.remove(trap_item)
        tile.inventory.items.append(trap_item)

        # Store trap DC on the tile for detection checks
        # Trap quality scales with CRAFT_QUALITY
        craft_bonus = self.stats.active[Stat.CRAFT_QUALITY]()
        tile.stat_mods['trap_dc'] = dc + craft_bonus
        tile.stat_mods['trap_item'] = trap_item.name

        return True

    # -- Movement Variants --------------------------------------------------

    def run(self, dx: int, dy: int, cols: int, rows: int) -> bool:
        """Move at 150% speed (immediate) with stamina cost.

        Returns True if moved.
        """
        stam_cost = 3
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stam_cost:
            return False
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stam_cost

        old_loc = self.location
        self.move(dx, dy, cols, rows)
        return self.location != old_loc

    def sneak(self, dx: int, dy: int, cols: int, rows: int) -> bool:
        """Move stealthily with a small stamina cost.

        Activates stealth bonus while sneaking.
        Returns True if moved.
        """
        stam_cost = 1
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        if cur_stam < stam_cost:
            return False
        self.stats.base[Stat.CUR_STAMINA] = cur_stam - stam_cost

        old_loc = self.location
        self.move(dx, dy, cols, rows)
        return self.location != old_loc

    # -- Stances ------------------------------------------------------------

    def enter_block_stance(self) -> bool:
        """Enter block stance. Enables block contest instead of dodge.

        Requires something in HAND_L or HAND_R (shield or weapon).
        Returns True if stance entered.
        """
        has_shield = (self.equipment.get(Slot.HAND_L) is not None or
                      self.equipment.get(Slot.HAND_R) is not None)
        if not has_shield:
            return False

        if not getattr(self, '_blocking', False):
            self._blocking = True
            self._block_mod = self.stats.add_mod('block_stance', Stat.BLOCK, 2)
        return True

    def exit_block_stance(self):
        """Exit block stance."""
        if getattr(self, '_blocking', False):
            self._blocking = False
            if hasattr(self, '_block_mod'):
                self.stats.remove_mod(self._block_mod)

    @property
    def is_blocking(self) -> bool:
        return getattr(self, '_blocking', False)

    @property
    def is_guarding(self) -> bool:
        return getattr(self, '_guarding', False)


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


class NeuralBehavior:
    """Neural net-driven behavior module.

    Uses a shared CreatureNet to select actions. The net takes the
    creature's observation vector and outputs action probabilities.
    A target selection heuristic picks the best target for targeted actions.
    """

    def __init__(self, net, temperature: float = 1.0):
        """Args:
            net: a simulation.net.CreatureNet instance (shared across all creatures)
            temperature: sampling temperature (0 = greedy, 1 = stochastic)
        """
        self.net = net
        self.temperature = temperature
        self._prev_snapshot = None

    def think(self, creature: Creature, cols: int, rows: int):
        from classes.observation import build_observation, make_snapshot
        from classes.actions import dispatch, Action
        from classes.world_object import WorldObject
        import numpy as np

        # Build observation
        obs = build_observation(creature, cols, rows, prev_snapshot=self._prev_snapshot)
        self._prev_snapshot = make_snapshot(creature)

        # Select action
        obs_arr = np.array(obs, dtype=np.float32)
        action_idx = self.net.select_action(obs_arr, self.temperature)

        # Build context — find nearest visible creature as target
        target = None
        nearest_dist = 999
        for obj in WorldObject.on_map(creature.current_map):
            if not isinstance(obj, Creature) or obj is creature or not obj.is_alive:
                continue
            dist = creature._sight_distance(obj)
            if dist < nearest_dist and creature.can_see(obj):
                nearest_dist = dist
                target = obj

        now = 0  # ticks managed by simulation loop
        context = {
            'cols': cols, 'rows': rows,
            'target': target, 'now': now,
        }

        dispatch(creature, action_idx, context)


class StatWeightedBehavior:
    """Stat-weighted decision table behavior (fallback/interim).

    Uses creature stats to weight action probabilities directly,
    without a neural net. Higher STR → prefer melee, higher INT →
    prefer social actions, higher AGL → prefer movement/flee, etc.

    Serves as immediate usable AI before training, and as a baseline
    for comparing against the neural net.
    """

    def think(self, creature: Creature, cols: int, rows: int):
        from classes.world_object import WorldObject
        from classes.actions import dispatch, Action

        # Compute stat-based weights
        str_mod = (creature.stats.active[Stat.STR]() - 10) // 2
        agl_mod = (creature.stats.active[Stat.AGL]() - 10) // 2
        int_mod = (creature.stats.active[Stat.INT]() - 10) // 2
        chr_mod = (creature.stats.active[Stat.CHR]() - 10) // 2
        per_mod = (creature.stats.active[Stat.PER]() - 10) // 2

        hp_ratio = creature.stats.active[Stat.HP_CURR]() / max(1, creature.stats.active[Stat.HP_MAX]())
        stam_ratio = creature.stats.active[Stat.CUR_STAMINA]() / max(1, creature.stats.active[Stat.MAX_STAMINA]())

        # Find nearest visible creature
        target = None
        nearest_dist = 999
        for obj in WorldObject.on_map(creature.current_map):
            if not isinstance(obj, Creature) or obj is creature or not obj.is_alive:
                continue
            dist = creature._sight_distance(obj)
            if dist < nearest_dist and creature.can_see(obj):
                nearest_dist = dist
                target = obj

        # Build weighted action candidates
        candidates = []

        # Always consider wandering
        wander_weight = 5 + agl_mod
        for d in range(8):
            candidates.append((d, wander_weight))

        if stam_ratio < 0.2:
            # Low stamina → strongly prefer waiting
            candidates.append((Action.WAIT, 20))
        else:
            candidates.append((Action.WAIT, 2))

        if target is not None:
            rel = creature.get_relationship(target)
            sentiment = rel[0] if rel else 0.0

            if nearest_dist <= 1:
                # Adjacent — combat or social
                if sentiment < -3 or hp_ratio > 0.5:
                    # Hostile or healthy → consider attack
                    candidates.append((Action.MELEE_ATTACK, 8 + str_mod * 2))
                    candidates.append((Action.GRAPPLE, 4 + str_mod))

                if sentiment >= 0:
                    # Neutral/positive → social
                    candidates.append((Action.TALK, 5 + chr_mod * 2))
                    candidates.append((Action.INTIMIDATE, 3 + str_mod + chr_mod))

                # Curiosity-driven approach for strangers
                if rel is None:
                    curiosity = creature.curiosity_toward(target)
                    candidates.append((Action.TALK, int(curiosity * 10 + int_mod * 2)))

            elif nearest_dist <= 8:
                # Medium range
                if sentiment < -3:
                    candidates.append((Action.RANGED_ATTACK, 5 + per_mod * 2))
                    candidates.append((Action.FLEE, 3 + agl_mod))

                # Follow interesting creatures
                if rel is None or sentiment > 0:
                    candidates.append((Action.FOLLOW, 5 + int_mod))

            # Low HP → flee or wait
            if hp_ratio < 0.3 and sentiment < 0:
                candidates.append((Action.FLEE, 15 + agl_mod * 2))

        # Search tiles occasionally (curiosity)
        candidates.append((Action.SEARCH, 2 + int_mod + per_mod))

        # Guard stance if guarding makes sense (territorial)
        candidates.append((Action.GUARD, 1 + str_mod))

        # Normalize weights and select
        weights = [max(1, w) for _, w in candidates]
        total = sum(weights)
        probs = [w / total for w in weights]
        idx = random.choices(range(len(candidates)), weights=probs, k=1)[0]
        chosen_action = candidates[idx][0]

        context = {
            'cols': cols, 'rows': rows,
            'target': target, 'now': 0,
        }

        dispatch(creature, chosen_action, context)
