from __future__ import annotations
from enum import Enum
from classes.trackable import Trackable


class ItemType(Enum):
    WEAPON      = 'weapon'
    ARMOR       = 'armor'
    CONSUMABLE  = 'consumable'
    KEY         = 'key'
    MISC        = 'misc'

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

class StateOfMatter(Enum):
    SOLID       = 'solid'
    LIQUID      = 'liquid'
    GAS         = 'gas'
    PLASMA      = 'plasma'

_ITEM_DEFAULTS = dict(
    name            = ''
    ,description    = ''
    ,item_type      = ItemType.MISC
    ,state          = StateOfMatter.SOLID
    ,value          = 0
    ,weight         = 0
    ,damage         = 0
    ,defense        = 0
    ,health         = 0
    ,poison         = False
    ,equippable     = True
    ,slots          = [Slot.HAND_L]
    ,consumable     = False
    ,stackable      = False
    ,quantity       = 1
    ,durability     = 100
    ,durability_current = 100
    )

class Item(Trackable):
    def __init__(self, **kwargs):
        super().__init__()
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getattr__(self, key):
        if key in _ITEM_DEFAULTS:
            return _ITEM_DEFAULTS[key]
        raise AttributeError(key)

class Inventory(Trackable):
    def __init__(self, items: list = []):
        super().__init__()
        self.items: list[Item] = list(items)
