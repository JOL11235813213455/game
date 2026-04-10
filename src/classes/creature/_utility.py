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

        Converts tile.resource_amount into a Stackable item in inventory.
        The full current amount is taken (tile goes to 0) and will grow back.
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

        # Harvest: take the resource, create a stackable item
        tile.resource_amount = 0

        # Check if a matching stack already exists in inventory
        resource_name = tile.resource_type.capitalize()
        for inv_item in self.inventory.items:
            if isinstance(inv_item, Stackable) and inv_item.name == resource_name:
                overflow = inv_item.add(amount, self.inventory)
                result['success'] = True
                result['item'] = inv_item
                result['amount'] = amount - overflow
                return result

        # Create new stack
        harvested = Stackable(
            name=resource_name,
            description=f'Harvested {resource_name.lower()}.',
            weight=0.1 * amount,
            value=float(amount),
            quantity=amount,
        )
        harvested.is_food = tile.resource_type in ('wheat', 'berries', 'fish', 'mushrooms', 'corn')
        self.inventory.items.append(harvested)

        result['success'] = True
        result['item'] = harvested
        result['amount'] = amount
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
        self.inventory.items.append(output)

        result['success'] = True
        result['recipe'] = recipe.name
        result['output'] = output
        return result

    def do_job(self, now: int = 0) -> dict:
        """Perform one tick of assigned work.

        Fails cleanly for wanderers and off-hours attempts. On success,
        pays the job's wage_per_tick into the creature's gold, delegates
        to the purpose-specific effect (farming → farm, mining → dig,
        guarding → guard stance, hunting/crafting → search/craft, etc.)
        so the job is doing something real on the tile.
        """
        result = {'success': False}

        if self.job is None:
            result['reason'] = 'no_job'
            return result

        tile = self.current_map.tiles.get(self.location)
        if tile is None:
            result['reason'] = 'no_tile'
            return result

        # Must be at a workplace tile
        tile_purpose = getattr(tile, 'purpose', None)
        if tile_purpose not in self.job.workplace_purposes:
            result['reason'] = 'not_at_workplace'
            return result

        # Must be during work hours
        hour = _current_hour(now)
        if not self.schedule.in_work_hours(hour):
            result['reason'] = 'off_hours'
            return result

        # Purpose-specific effect. Every job performs a real action on
        # the world; the wage is a reward for the work, not an
        # independent money-printer.
        effect = {'success': True}
        purpose = self.job.purpose
        if purpose == 'farming':
            effect = self.farm()
        elif purpose == 'mining':
            # Miners tend the ore vein — same stewardship model as farming.
            # HARVEST on the tile is what actually extracts ore.
            if getattr(tile, 'resource_type', None) and tile.growth_rate > 0:
                str_mod = (self.stats.active[Stat.STR]() - 10) // 2
                multiplier = 2.0 + max(0, str_mod) * 0.5
                boost = tile.growth_rate * multiplier
                old = tile.resource_amount
                tile.resource_amount = min(tile.resource_max, tile.resource_amount + boost)
                effect['boost'] = tile.resource_amount - old
            else:
                effect = {'success': False, 'reason': 'not_a_vein'}
        elif purpose == 'crafting':
            # Crafters process raw materials into goods while working.
            effect = self.process()
            # Crafter still gets wage even if nothing to process right now —
            # treat an empty inventory as "apprentice work" (wage, no output)
            if not effect.get('success') and effect.get('reason') == 'no_recipe_match':
                effect = {'success': True, 'idle': True}
        elif purpose == 'guarding':
            self.guard(cols=1, rows=1)
        elif purpose == 'hunting':
            self.search_tile()
        elif purpose == 'healing':
            cur = self.stats.active[Stat.CUR_MANA]()
            mx  = self.stats.active[Stat.MAX_MANA]()
            self.stats.base[Stat.CUR_MANA] = min(mx, cur + 1)
        # 'trading' jobs collect wages for showing up — the real TRADE
        # action is separate and NN-chosen.

        # Pay wage if the underlying effect didn't hard-fail
        if effect.get('success', True):
            wage = self.job.wage_per_tick
            self.gold = int(getattr(self, 'gold', 0) + wage)
            self._wage_accumulated = getattr(self, '_wage_accumulated', 0.0) + wage
            result['success'] = True
            result['wage'] = wage
            result['purpose'] = purpose
        else:
            result['reason'] = effect.get('reason', 'effect_failed')
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
