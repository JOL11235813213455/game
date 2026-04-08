from __future__ import annotations
from enum import Enum
from classes.trackable import Trackable
from classes.world_object import WorldObject


class Slot(Enum):
    HEAD        = 'head'
    NECK        = 'neck'
    SHOULDERS   = 'shoulders'
    CHEST       = 'chest'
    BACK        = 'back'
    WRISTS      = 'wrists'
    HANDS       = 'hands'
    WAIST       = 'waist'
    LEGS        = 'legs'
    FEET        = 'feet'
    RING_L      = 'ring_l'
    RING_R      = 'ring_r'
    HAND_L      = 'hand_l'
    HAND_R      = 'hand_r'


class Item(WorldObject):
    z_index   = 2
    collision = False
    def __init__(
        self
        ,name: str = ''
        ,description: str = ''
        ,weight: float = 0
        ,value: float = 0
        ,sprite_name: str = None
        ,inventoriable: bool = True
        ,buffs: dict = None
        ,action_word: str = ''
        ,requirements: dict = None
        ):
        super().__init__()
        self.name         = name
        self.description  = description
        self.weight       = weight
        self.value        = value
        self.sprite_name  = sprite_name
        self.inventoriable = inventoriable
        self.buffs        = buffs or {}
        self.action_word  = action_word
        self.requirements = requirements or {}

class Stackable(Item):

    def __init__(self, *args, max_stack_size: int = 99, quantity: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_stack_size = max_stack_size
        self.quantity       = quantity

    def add(self, amount: int, inventory: Inventory) -> int:
        """
        Add amount to this stack. If the stack is full, create new stacks in
        the inventory for the overflow. Returns any amount that could not fit.
        """
        space = self.max_stack_size - self.quantity
        added = min(amount, space)
        self.quantity += added
        remaining = amount - added
        while remaining > 0:
            new_stack = self.__class__(
                name=self.name, description=self.description,
                weight=self.weight, value=self.value,
                sprite_name=self.sprite_name, inventoriable=self.inventoriable,
                buffs=dict(self.buffs), max_stack_size=self.max_stack_size,
                quantity=0,
            )
            inventory.items.append(new_stack)
            chunk = min(remaining, self.max_stack_size)
            new_stack.quantity = chunk
            remaining -= chunk
        return 0

    @staticmethod
    def coalesce(inventory: Inventory):
        """Merge stacks of the same item type (matched by name) where possible."""
        from collections import defaultdict
        groups: dict[str, list[Stackable]] = defaultdict(list)
        for item in inventory.items:
            if isinstance(item, Stackable):
                groups[item.name].append(item)
        for name, stacks in groups.items():
            stacks.sort(key=lambda s: s.quantity)
            for i in range(len(stacks) - 1):
                src = stacks[i]
                for dst in stacks[i + 1:]:
                    if dst.quantity >= dst.max_stack_size:
                        continue
                    space = dst.max_stack_size - dst.quantity
                    move  = min(src.quantity, space)
                    dst.quantity += move
                    src.quantity -= move
        inventory.items = [i for i in inventory.items
                           if not isinstance(i, Stackable) or i.quantity > 0]


class Consumable(Stackable):

    def __init__(self, *args, duration: float = 0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.duration = duration


class Ammunition(Stackable):

    def __init__(self, *args, damage: float = 0, destroy_on_use_probability: float = 1.0,
                 recoverable: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.damage                    = damage
        self.destroy_on_use_probability = destroy_on_use_probability
        self.recoverable               = recoverable


class Equippable(Item):

    def __init__(
        self
        ,*args
        ,slots: list[Slot] = None
        ,slot_count: int = 1
        ,durability_max: int = 100
        ,durability_current: int = None
        ,render_on_creature: bool = False
        ,**kwargs
        ):
        super().__init__(*args, **kwargs)
        self.slots              = slots or []
        self.slot_count         = slot_count
        self.durability_max     = durability_max
        self.durability_current = durability_current if durability_current is not None else durability_max
        self.render_on_creature = render_on_creature


class Weapon(Equippable):

    def __init__(
        self
        ,*args
        ,damage: float = 0
        ,attack_time_ms: int = 500
        ,directions: list[str] = None
        ,range: int = 1
        ,ammunition_type: str = None
        ,**kwargs
        ):
        super().__init__(*args, **kwargs)
        self.damage           = damage
        self.attack_time_ms   = attack_time_ms
        self.directions       = directions or ['front']
        self.range            = range
        self.ammunition_type  = ammunition_type

class Wearable(Equippable):
    pass

class Structure(Item):
    z_index   = 1
    collision = False

    def __init__(
        self
        ,*args
        ,footprint: list[list[int]] = None
        ,collision_mask: list[list[int]] = None
        ,entry_points: dict[str, list[int]] = None
        ,nested_map: str = None
        ,**kwargs
        ):
        kwargs.setdefault('inventoriable', False)
        super().__init__(*args, **kwargs)
        self.footprint      = [tuple(p) for p in (footprint or [[0, 0]])]
        self.collision_mask  = [tuple(p) for p in (collision_mask or list(self.footprint))]
        self.entry_points    = entry_points or {}
        self.nested_map_name = nested_map

CLASS_MAP: dict[str, type] = {
    'Item':       Item,
    'Consumable': Consumable,
    'Ammunition': Ammunition,
    'Weapon':     Weapon,
    'Wearable':   Wearable,
    'Structure':  Structure,
}

class Inventory(Trackable):
    def __init__(self, items: list = None):
        super().__init__()
        self.items: list[Item] = list(items) if items else []
