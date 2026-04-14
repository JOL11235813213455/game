from __future__ import annotations
from classes.stats import Stat
from classes.inventory import Equippable, Wearable, Weapon, Consumable, Stackable, Slot
from classes.world_object import WorldObject


def _item_score(item) -> float:
    """Score an item for equip comparison. Higher = better."""
    score = sum(abs(v) for v in getattr(item, 'buffs', {}).values())
    if isinstance(item, Weapon):
        score += getattr(item, 'damage', 0)
    score += getattr(item, 'value', 0) * 0.1
    return score


class InventoryMixin:
    """Equipment and inventory methods for Creature."""

    _next_consumable_id = 0

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
        If the item is an ingredient for an auto_pop ItemFrame, the frame
        is auto-created and the item placed inside it.
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

        if isinstance(item, Stackable):
            Stackable.coalesce(self.inventory)

        # Auto-pop: check if this item triggers an ItemFrame creation
        self._check_auto_pop(item)

        # Auto-equip for NN-controlled creatures only. The player
        # manages their own equipment via the inventory menu.
        if self.behavior is not None and isinstance(item, Equippable) and item.slots:
            self._try_auto_equip(item)

        return True

    def _check_auto_pop(self, item):
        """If item is an ingredient for an auto_pop frame, create the frame."""
        from classes.inventory import ItemFrame
        try:
            from data.db import ITEM_FRAMES
        except (ImportError, AttributeError):
            return  # ITEM_FRAMES not loaded yet

        item_id = getattr(item, 'key', '') or getattr(item, 'name', '')

        for frame_key, frame_data in ITEM_FRAMES.items():
            if not frame_data.get('auto_pop'):
                continue
            recipe = frame_data.get('recipe', {})
            if item_id not in recipe:
                continue

            # Check if we already have this frame in inventory
            existing = None
            for inv_item in self.inventory.items:
                if isinstance(inv_item, ItemFrame) and inv_item.frame_key == frame_key:
                    existing = inv_item
                    break

            if existing is None:
                # Create the frame
                existing = ItemFrame(
                    frame_key=frame_key,
                    recipe=dict(recipe),
                    name=frame_data.get('name', f'Frame: {frame_key}'),
                    description=frame_data.get('description', ''),
                    auto_pop=True,
                    composite_name=frame_data.get('composite_name'),
                )
                self.inventory.items.append(existing)

            # Move item from inventory into the frame
            if item in self.inventory.items:
                self.inventory.items.remove(item)
                existing.add_ingredient(item)

    def pickup_gold(self) -> int:
        """Pick up gold from the current tile. Returns amount picked up."""
        tile = self.current_map.tiles.get(self.location)
        if tile is None or tile.gold <= 0:
            return 0
        amount = tile.gold
        self.gold += amount
        tile.gold = 0
        return amount

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
        """Move an item between accessible inventories (self, tile, adjacent creatures)."""
        from classes.creature import Creature
        tile = self.current_map.tiles.get(self.location)
        accessible = [self.inventory]
        if tile:
            accessible.append(tile.inventory)
        cx, cy = self.location.x, self.location.y
        for creature in WorldObject.on_map(self.current_map):
            if isinstance(creature, Creature) and creature is not self and creature.is_alive:
                d = abs(cx - creature.location.x) + abs(cy - creature.location.y)
                if d <= 1:
                    accessible.append(creature.inventory)
        if source not in accessible or target not in accessible:
            return False
        if item not in source.items:
            return False
        source.items.remove(item)
        target.items.append(item)
        return True

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
        from classes.creature import Creature
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

        # Direct heals
        if item.heal_amount > 0:
            hp = self.stats.base.get(Stat.HP_CURR, 0)
            hp_max = self.stats.active[Stat.HP_MAX]()
            self.stats.base[Stat.HP_CURR] = min(hp_max, hp + item.heal_amount)
        if item.stamina_restore > 0:
            stam = self.stats.base.get(Stat.CUR_STAMINA, 0)
            stam_max = self.stats.active[Stat.MAX_STAMINA]()
            self.stats.base[Stat.CUR_STAMINA] = min(stam_max, stam + item.stamina_restore)
        if item.mana_restore > 0:
            mana = self.stats.base.get(Stat.CUR_MANA, 0)
            mana_max = self.stats.active[Stat.MAX_MANA]()
            self.stats.base[Stat.CUR_MANA] = min(mana_max, mana + item.mana_restore)

        # Food: restore hunger proportional to value
        # Any consumable with heal_amount or explicit food flag feeds
        if item.heal_amount > 0 or getattr(item, 'is_food', False):
            food_amount = max(0.1, min(0.5, item.value / 20.0))
            self.eat(food_amount)

        # Decrement stack
        item.quantity -= 1
        if item.quantity <= 0:
            self.inventory.items.remove(item)

        return True

    def _try_auto_equip(self, item: Equippable):
        """Equip item if it's better than what's currently in the slot.

        Compares by _item_score (buff totals + damage + value).
        If current slot is empty, equip. If occupied, only swap when
        the new item scores strictly higher.
        """
        if not item.slots:
            return
        target_slot = item.slots[0]
        current = self.equipment.get(target_slot)
        if current is None:
            self.equip(item)
            return
        if _item_score(item) > _item_score(current):
            self.unequip(target_slot)
            self.equip(item)

    def smart_drop(self) -> bool:
        """Drop the least valuable item by value-per-weight ratio.

        Skips equipped items. Returns True if something was dropped.
        """
        candidates = [i for i in self.inventory.items
                      if i not in set(self.equipment.values())]
        if not candidates:
            return False
        worst = min(candidates,
                    key=lambda i: getattr(i, 'value', 0) / max(0.01, getattr(i, 'weight', 0.01)))
        return self.drop(worst)
