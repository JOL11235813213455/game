from __future__ import annotations
from classes.stats import Stat
from classes.inventory import Equippable, Consumable, Slot
from classes.world_object import WorldObject


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
        from classes.creature import Creature
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

        # Decrement stack
        item.quantity -= 1
        if item.quantity <= 0:
            self.inventory.items.remove(item)

        return True
