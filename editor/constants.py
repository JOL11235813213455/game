ITEM_CLASSES = ['Item', 'Weapon', 'Wearable', 'Consumable', 'Ammunition', 'Structure']
SLOTS        = ['head', 'neck', 'shoulders', 'chest', 'back', 'wrists', 'hands',
                'waist', 'legs', 'feet', 'ring_l', 'ring_r', 'hand_l', 'hand_r']
STATS        = ['strength', 'vitality', 'intelligence', 'agility',
                'perception', 'charisma', 'luck', 'hit dice']
STAT_LABELS  = {
    'strength':      'STR',
    'vitality':      'VIT',
    'intelligence':  'INT',
    'agility':       'AGL',
    'perception':    'PER',
    'charisma':      'CHR',
    'luck':          'LCK',
    'hit dice':      'HIT_DICE',
}

CLASS_FIELDS = {
    'Item':       ['action_word'],
    'Consumable': ['action_word', 'max_stack_size', 'quantity', 'duration'],
    'Ammunition': ['action_word', 'max_stack_size', 'quantity', 'damage', 'destroy_on_use_probability'],
    'Weapon':     ['action_word', 'slots', 'slot_count', 'durability_max', 'durability_current', 'render_on_creature',
                   'requirements', 'damage', 'attack_time_ms', 'directions', 'range', 'ammunition_type'],
    'Wearable':   ['action_word', 'slots', 'slot_count', 'durability_max', 'durability_current', 'render_on_creature',
                   'requirements'],
    'Structure':  ['footprint', 'collision_mask', 'entry_points', 'nested_map'],
}

GRID_COLS    = 32
GRID_ROWS    = 32
CELL_SIZE    = 20
PREVIEW_SIZE = 64
MAX_PALETTE  = 12
