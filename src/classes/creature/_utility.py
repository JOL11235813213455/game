from __future__ import annotations
import random
from classes.stats import Stat
from classes.inventory import Slot
from classes.world_object import WorldObject


def _current_hour(now_ms: int) -> float:
    """Derive a 0-24 game hour from a simulation time in milliseconds.

    Convention: 1 tick = 500ms = 1 game minute, matching the hunger drain
    calibration (2.0 / 1440 ticks = full depletion per day). If a
    :class:`GameClock` exists in Trackable, prefer it for runtime
    consistency. Training start time defaults to 8:00 so first day covers
    morning-work-evening-sleep rather than starting mid-night.
    """
    try:
        from main.game_clock import GameClock
        from classes.trackable import Trackable
        for obj in Trackable.all_instances():
            if isinstance(obj, GameClock):
                return obj.hour
    except Exception:
        pass
    # Fallback: derive from sim.now. 1 tick (500ms) = 1 game minute.
    # Start offset 8h so wake/work/sleep cycle aligns with training windows.
    minutes = now_ms / 500.0
    return (8.0 + minutes / 60.0) % 24.0


class UtilityMixin:
    """Utility actions: search, guard, wait, sleep, traps, stances."""

    def search_tile(self) -> dict:
        """Search the current tile for items and resources.

        Reveals tile inventory. Hidden items require DETECTION check.
        Returns dict: items_found (list), hidden_found (list/bool),
                      resource_type (str|None), resource_amount (int).
        """
        result = {'items_found': [], 'hidden_found': [], 'resource_type': None, 'resource_amount': 0}

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

        # Resource on tile
        if getattr(tile, 'resource_type', None):
            result['resource_type'] = tile.resource_type
            result['resource_amount'] = int(tile.resource_amount)

        return result

    def harvest(self) -> dict:
        """Harvest the resource from the current tile.

        Looks up the tile's resource item in the DB catalog (``ITEMS``)
        using ``tile.resource_type`` as the key, clones it with the
        current ``resource_amount`` as quantity, and adds it to
        inventory. The tile drops to zero and regrows via
        ``Map.grow_resources``.

        Falls back to a runtime-constructed Stackable when the catalog
        lookup fails — keeps tests running without a full DB load, and
        keeps tile templates that use short names (e.g. ``'wheat'``)
        functional before arenas are updated.

        Returns dict: success (bool), item (Stackable|None), amount (int).
        """
        from classes.inventory import Stackable

        result = {'success': False, 'item': None, 'amount': 0}

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            result['reason'] = 'no_tile'
            return result

        if not getattr(tile, 'resource_type', None):
            result['reason'] = 'no_resource'
            return result

        amount = int(tile.resource_amount)
        if amount <= 0:
            result['reason'] = 'depleted'
            return result

        # Take the resource
        tile.resource_amount = 0

        # Prefer DB catalog template
        from data.db import ITEMS
        template = ITEMS.get(tile.resource_type)

        if template is not None:
            import copy as _copy
            # Check for an existing matching stack in inventory to merge into
            for inv_item in self.inventory.items:
                if isinstance(inv_item, Stackable) and inv_item.name == template.name:
                    overflow = inv_item.add(amount, self.inventory)
                    result['success'] = True
                    result['item'] = inv_item
                    result['amount'] = amount - overflow
                    self.gain_exp(2)
                    return result
            clone = _copy.copy(template)
            clone.quantity = amount
            self.inventory.items.append(clone)
            result['success'] = True
            result['item'] = clone
            result['amount'] = amount
            self.gain_exp(2)
            return result

        # Fallback (no DB catalog): use the legacy runtime construction
        resource_name = tile.resource_type.capitalize()
        for inv_item in self.inventory.items:
            if isinstance(inv_item, Stackable) and inv_item.name == resource_name:
                overflow = inv_item.add(amount, self.inventory)
                result['success'] = True
                result['item'] = inv_item
                result['amount'] = amount - overflow
                self.gain_exp(2)
                return result
        harvested = Stackable(
            name=resource_name,
            description=f'Harvested {resource_name.lower()}.',
            weight=0.1 * amount,
            value=float(amount),
            quantity=amount,
        )
        harvested.is_food = tile.resource_type in (
            'wheat', 'berries', 'fish', 'mushrooms', 'corn', 'game')
        self.inventory.items.append(harvested)

        result['success'] = True
        result['item'] = harvested
        result['amount'] = amount
        self.gain_exp(2)
        return result

    def farm(self) -> dict:
        """Tend a farming tile — boost its resource growth.

        FARM is the stewardship action, distinct from HARVEST. It does
        not produce inventory; instead it boosts the tile's resource
        amount by a multiple of its growth rate, scaled by INT. Requires
        a tile with a resource and growth_rate > 0. Costs a small amount
        of stamina.

        Returns dict: success, boost (amount added), reason on failure.
        """
        result = {'success': False}

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            result['reason'] = 'no_tile'
            return result
        if not getattr(tile, 'resource_type', None):
            result['reason'] = 'no_resource'
            return result
        if tile.growth_rate <= 0:
            result['reason'] = 'not_farmable'
            return result
        if tile.resource_amount >= tile.resource_max:
            result['reason'] = 'already_full'
            return result

        # Stamina cost
        stam_cost = 2
        if self.stats.active[Stat.CUR_STAMINA]() < stam_cost:
            result['reason'] = 'exhausted'
            return result
        self.stats.base[Stat.CUR_STAMINA] = max(
            0, self.stats.base.get(Stat.CUR_STAMINA, 0) - stam_cost)

        # Boost scales with INT modifier: neutral = 2x growth, +5 INT = 4.5x
        int_mod = (self.stats.active[Stat.INT]() - 10) // 2
        multiplier = 2.0 + max(0, int_mod) * 0.5
        boost = tile.growth_rate * multiplier
        old_amt = tile.resource_amount
        tile.resource_amount = min(tile.resource_max, tile.resource_amount + boost)

        result['success'] = True
        result['boost'] = tile.resource_amount - old_amt
        return result

    def process(self, category: str = None) -> dict:
        """Transform raw materials in inventory into a finished good.

        Must be performed on a ``crafting`` purpose tile. The method
        scans inventory for the first recipe whose ingredients are all
        present (optionally filtered to ``'food'`` or ``'material'``),
        consumes the inputs, and adds the output item to the inventory.

        Returns dict: success, recipe, output, or failure reason.
        """
        from classes.recipes import find_matching_recipe, consume_inputs

        result = {'success': False}

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            result['reason'] = 'no_tile'
            return result
        if getattr(tile, 'purpose', None) != 'crafting':
            result['reason'] = 'wrong_tile'
            return result

        # Stamina cost — processing is lighter than mining/farming
        stam_cost = 1
        if self.stats.active[Stat.CUR_STAMINA]() < stam_cost:
            result['reason'] = 'exhausted'
            return result

        recipe = find_matching_recipe(self.inventory.items, category=category)
        if recipe is None:
            result['reason'] = 'no_recipe_match'
            return result

        if not consume_inputs(self.inventory, recipe):
            result['reason'] = 'consume_failed'
            return result

        self.stats.base[Stat.CUR_STAMINA] = max(
            0, self.stats.base.get(Stat.CUR_STAMINA, 0) - stam_cost)

        output = recipe.output_factory()
        # Merge into an existing matching stack if possible so repeated
        # PROCESS calls don't fill inventory with single-unit duplicates.
        from classes.inventory import Stackable
        merged = False
        if isinstance(output, Stackable):
            for inv_item in self.inventory.items:
                if (isinstance(inv_item, Stackable)
                        and inv_item.name == output.name
                        and type(inv_item) is type(output)):
                    inv_item.quantity = getattr(inv_item, 'quantity', 1) + getattr(output, 'quantity', 1)
                    output = inv_item
                    merged = True
                    break
        if not merged:
            self.inventory.items.append(output)

        result['success'] = True
        result['recipe'] = recipe.name
        result['output'] = output
        self.gain_exp(3)
        return result

    def do_job(self, now: int = 0) -> dict:
        """Begin a 1-game-hour work shift (60 ticks) as a sustained occupation.

        On entry, validates workplace and hours, then sets the creature
        as occupied. While occupied, ``_tick_work`` handles per-tick
        wages and purpose effects. The creature can break from work
        if a hostile appears in sight (flee/fight interrupt).

        Fails cleanly for wanderers and off-hours attempts.
        """
        result = {'success': False}

        if self.job is None:
            result['reason'] = 'no_job'
            return result

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            result['reason'] = 'no_tile'
            return result

        tile_purpose = getattr(tile, 'purpose', None)
        if tile_purpose not in self.job.workplace_purposes:
            result['reason'] = 'not_at_workplace'
            return result

        hour = _current_hour(now)
        if not self.schedule.in_work_hours(hour):
            result['reason'] = 'off_hours'
            return result

        self._occupation = 'work'
        self._occupied_until = now + 60
        self._tick_work(now)
        result['success'] = True
        result['purpose'] = self.job.purpose
        self.gain_exp(2)
        return result

    def _tick_work(self, now: int = 0):
        """Per-tick work processing: purpose effect + wage.

        Called each tick while the creature is occupied with 'work'.
        """
        tile = self.current_map.tiles.get(self.location)
        if tile is None or self.job is None:
            return
        purpose = self.job.purpose
        if purpose == 'farming':
            self.farm()
        elif purpose == 'mining':
            if getattr(tile, 'resource_type', None) and tile.growth_rate > 0:
                str_mod = (self.stats.active[Stat.STR]() - 10) // 2
                multiplier = 2.0 + max(0, str_mod) * 0.5
                boost = tile.growth_rate * multiplier
                tile.resource_amount = min(tile.resource_max,
                                           tile.resource_amount + boost)
        elif purpose == 'crafting':
            self.process()
        elif purpose == 'trading':
            from classes.world_object import WorldObject
            from classes.creature import Creature as _Creature
            partner = next(
                (o for o in WorldObject.on_map(self.current_map)
                 if isinstance(o, _Creature) and o is not self
                 and o.is_alive
                 and abs(o.location.x - self.location.x) +
                     abs(o.location.y - self.location.y) <= 1),
                None
            )
            if partner is not None:
                self.auto_trade(partner)
        elif purpose == 'guarding':
            self.guard(cols=1, rows=1)
        elif purpose == 'hunting':
            self.search_tile()
        elif purpose == 'healing':
            cur = self.stats.active[Stat.CUR_MANA]()
            mx  = self.stats.active[Stat.MAX_MANA]()
            self.stats.base[Stat.CUR_MANA] = min(mx, cur + 1)

        wage = self.job.wage_per_tick
        self._wage_accumulated = getattr(self, '_wage_accumulated', 0.0) + wage
        # Accumulate fractional gold; only bank whole units
        self._wage_fractional = getattr(self, '_wage_fractional', 0.0) + wage
        if self._wage_fractional >= 1.0:
            whole = int(self._wage_fractional)
            self.gold = getattr(self, 'gold', 0) + whole
            self._wage_fractional -= whole

    def _check_work_interrupt(self, now: int) -> bool:
        """Check if a hostile creature is in sight, warranting a work break.

        Returns True if the creature should stop working to respond.
        """
        if now >= self._occupied_until:
            self._occupation = None
            self._occupied_until = 0
            return True
        from classes.relationship_graph import GRAPH
        from classes.world_object import WorldObject
        from classes.creature import Creature as _C
        sight = self.stats.active[Stat.SIGHT_RANGE]()
        cx, cy = self.location.x, self.location.y
        rels = GRAPH.edges_from(self.uid)
        for obj in WorldObject.on_map(self.current_map):
            if not isinstance(obj, _C) or obj is self or not obj.is_alive:
                continue
            d = abs(cx - obj.location.x) + abs(cy - obj.location.y)
            if d > sight:
                continue
            rel = rels.get(obj.uid)
            if rel and rel[0] < -5:
                self._occupation = None
                self._occupied_until = 0
                return True
        return False

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

    def call_backup(self) -> list:
        """Broadcast a call for help within hearing range.

        Returns list of creatures that could potentially respond
        (within their HEARING_RANGE of the caller, with positive sentiment).
        """
        from classes.creature import Creature
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
        """Enter sleep state as a sustained occupation (6-8 game hours).

        While sleeping:
          - Stamina/mana restore gradually (full over ~360 ticks / 6 hrs)
          - sleep_debt decreases by 1 per 360 ticks of sleep
          - Restfulness fills from 0→1 over the sleep duration
          - Detection is severely reduced (vulnerable)

        The creature stays asleep until:
          - Natural wake: 360-480 ticks (6-8 game hours)
          - Loud noise: combat/death_cry/struggle sound within hearing
          - Being attacked: HP drops during sleep
          - Sleepwalking: ~1% chance per tick, random move then resume
        """
        if getattr(self, '_sleeping', False):
            return False

        import random as _rng
        self._sleeping = True
        self._occupation = 'sleep'
        self._sleep_start_tick = now
        self._sleep_ticks = 0
        duration = _rng.randint(360, 480)
        self._occupied_until = now + duration
        self._sleep_hp_snapshot = self.stats.active[Stat.HP_CURR]()
        self._sleep_mod = self.stats.add_mod('sleep', Stat.DETECTION, -5)
        return True

    def _tick_sleep(self, now: int):
        """Per-tick sleep processing: gradual restore + interrupt check.

        Called by the dispatch occupation intercept each tick while
        the creature is sleeping. Returns an interrupt action tuple
        (action, reason) if the creature should wake, or None to
        stay asleep.
        """
        import random as _rng
        self._sleep_ticks += 1

        # Gradual restore: full stamina/mana over ~360 ticks
        max_stam = self.stats.active[Stat.MAX_STAMINA]()
        max_mana = self.stats.active[Stat.MAX_MANA]()
        stam_per_tick = max_stam / 360.0
        mana_per_tick = max_mana / 360.0
        cur_stam = self.stats.active[Stat.CUR_STAMINA]()
        cur_mana = self.stats.active[Stat.CUR_MANA]()
        self.stats.base[Stat.CUR_STAMINA] = min(max_stam, cur_stam + stam_per_tick)
        self.stats.base[Stat.CUR_MANA] = min(max_mana, cur_mana + mana_per_tick)

        # Reduce sleep debt: 1 day per 360 ticks of continuous sleep
        if self._sleep_ticks > 0 and self._sleep_ticks % 360 == 0:
            if self.sleep_debt > 0:
                self.sleep_debt -= 1
                self._update_fatigue()

        # Restfulness fills linearly
        duration = max(1, self._occupied_until - self._sleep_start_tick)
        self._restfulness = min(1.0, self._sleep_ticks / duration)

        # --- Interrupt checks ---

        # Natural wake: occupation time expired
        if now >= self._occupied_until:
            self.sleep_debt = max(0, self.sleep_debt - 1)
            self._update_fatigue()
            return ('wake', 'rested')

        # Attacked: HP dropped since sleep started
        current_hp = self.stats.active[Stat.HP_CURR]()
        if current_hp < getattr(self, '_sleep_hp_snapshot', current_hp):
            return ('wake', 'attacked')

        # Loud noise: check hearing buffer for combat/death_cry/struggle
        buf = getattr(self, '_hearing_buffer', None)
        if buf:
            wake_types = {'combat', 'death_cry', 'struggle'}
            for ev in buf:
                if ev.type in wake_types and ev.tick >= self._sleep_start_tick:
                    return ('wake', 'noise')

        # Sleepwalking: ~1% chance per tick
        if _rng.random() < 0.01:
            return ('sleepwalk', 'sleepwalk')

        return None

    def wake(self):
        """Exit sleep state and clear occupation."""
        if getattr(self, '_sleeping', False):
            self._sleeping = False
            self._occupation = None
            self._occupied_until = 0
            if hasattr(self, '_sleep_mod'):
                self.stats.remove_mod(self._sleep_mod)

    @property
    def is_sleeping(self) -> bool:
        return getattr(self, '_sleeping', False)

    def add_sleep_debt(self, days: int = 1):
        """Increment sleep debt (called once per day cycle).

        Fatigue debuffs stack at thresholds:
          1 day  -> mild: -1 STR, -1 AGL, -1 PER
          2 days -> exhaustion: -2 STR, -2 AGL, -2 PER, -1 STAM_REGEN
          3 days -> severe: -3 all base stats, -2 DETECTION, -2 ACCURACY
          4 days -> collapse: forced sleep (creature is vulnerable)
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

    # enter_guard is an alias referenced in the spec
    def enter_guard(self, cols: int, rows: int) -> bool:
        """Alias for guard()."""
        return self.guard(cols, rows)

    def dig(self) -> dict:
        """Dig at current tile to access buried inventory.

        Requires a shovel-type tool in inventory or equipment.
        Costs stamina. Transfers buried items to surface.
        Returns dict with success, items_found.
        """
        from classes.inventory import Weapon, Equippable

        result = {'success': False, 'items_found': []}

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            result['reason'] = 'no_tile'
            return result

        has_buried = (hasattr(tile, 'buried_inventory') and tile.buried_inventory.items) or \
                     getattr(tile, 'buried_gold', 0) > 0
        if not has_buried:
            result['reason'] = 'nothing_buried'
            return result

        # Check for shovel in inventory or equipment
        has_shovel = False
        all_items = list(self.inventory.items) + list(set(self.equipment.values()))
        for item in all_items:
            if getattr(item, 'name', '').lower() in ('shovel', 'spade', 'pickaxe'):
                has_shovel = True
                break

        if not has_shovel:
            result['reason'] = 'no_shovel'
            return result

        # Stamina cost
        stam_cost = 5
        if self.stats.active[Stat.CUR_STAMINA]() < stam_cost:
            result['reason'] = 'exhausted'
            return result
        self.stats.base[Stat.CUR_STAMINA] = max(
            0, self.stats.base.get(Stat.CUR_STAMINA, 0) - stam_cost)

        # Transfer all buried items to surface
        for item in list(tile.buried_inventory.items):
            tile.buried_inventory.items.remove(item)
            tile.inventory.items.append(item)
            result['items_found'].append(item)

        # Transfer buried gold to surface
        buried_gold = getattr(tile, 'buried_gold', 0)
        if buried_gold > 0:
            tile.gold += buried_gold
            tile.buried_gold = 0
            result['gold_found'] = buried_gold

        result['success'] = True
        return result

    def push(self, target, dx: int, dy: int, cols: int, rows: int) -> dict:
        """Push another creature one tile in a direction.

        Requires: adjacent to target, enough stamina, STR contest.
        The push direction is from self toward target.
        """
        from classes.maps import MapKey

        result = {'success': False}

        # Must be adjacent
        dist = abs(self.location.x - target.location.x) + abs(self.location.y - target.location.y)
        if dist > 1:
            result['reason'] = 'too_far'
            return result

        # Stamina cost
        stam_cost = 3
        if self.stats.active[Stat.CUR_STAMINA]() < stam_cost:
            result['reason'] = 'exhausted'
            return result
        self.stats.base[Stat.CUR_STAMINA] = max(
            0, self.stats.base.get(Stat.CUR_STAMINA, 0) - stam_cost)

        # STR contest: pusher vs target
        won, margin = self.stats.contest(target.stats, 'push')
        if not won:
            result['reason'] = 'resisted'
            target.record_interaction(self, -1.0)
            return result

        # Normalize push direction to unit vector
        if dx != 0:
            dx = 1 if dx > 0 else -1
        if dy != 0:
            dy = 1 if dy > 0 else -1
        if dx == 0 and dy == 0:
            dx = 1  # default push east if on same tile somehow

        # Check target tile
        new_x = target.location.x + dx
        new_y = target.location.y + dy
        if new_x < 0 or new_x >= cols or new_y < 0 or new_y >= rows:
            result['reason'] = 'edge'
            return result

        new_key = MapKey(new_x, new_y, target.location.z)
        new_tile = target.current_map.tiles.get(new_key)
        if new_tile is None:
            result['reason'] = 'no_tile'
            return result

        # Push succeeds — move the target (even into unwalkable/liquid tiles!)
        target.location = new_key
        result['success'] = True
        result['pushed_to'] = (new_x, new_y)

        # Hostile act
        target.record_interaction(self, -3.0)

        return result

    def craft(self) -> dict:
        """Attempt to complete the first ready ItemFrame in inventory.

        For non-consumable frames: the frame IS the finished item (no-op
        beyond marking complete). For consumable frames: produces output,
        destroys ingredients and frame.

        Returns dict with success and the result.
        """
        from classes.inventory import ItemFrame

        result = {'success': False}

        for inv_item in self.inventory.items:
            if isinstance(inv_item, ItemFrame) and inv_item.is_complete:
                output = inv_item.try_complete(self)
                if output is not None:
                    result['success'] = True
                    result['crafted'] = output
                    result['frame_key'] = inv_item.frame_key
                    result['is_consumable'] = inv_item.consumable_output
                    return result

        result['reason'] = 'no_complete_frame'
        return result

    def disassemble(self, item) -> dict:
        """Pop all parts out of an ItemFrame back into inventory.

        Only works on ItemFrame items. The frame stays (now empty).
        """
        from classes.inventory import ItemFrame

        result = {'success': False}

        if item not in self.inventory.items:
            result['reason'] = 'not_in_inventory'
            return result

        if not isinstance(item, ItemFrame):
            result['reason'] = 'not_a_frame'
            return result

        moved = item.disassemble_into(self.inventory)
        # Empty frame self-destructs
        if not item.ingredients.items and item in self.inventory.items:
            self.inventory.items.remove(item)
        result['success'] = True
        result['parts'] = len(moved)
        return result
