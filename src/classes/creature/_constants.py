from __future__ import annotations

# Size categories and tile capacity rules
SIZE_CATEGORIES = ('tiny', 'small', 'medium', 'large', 'huge', 'colossal')

# How many of each size fit in a tile (in "tile units", 1 tile = 16 units)
SIZE_UNITS = {
    'tiny': 0,        # unlimited — no space consumed
    'small': 1,       # 16 per tile
    'medium': 4,      # 4 per tile
    'large': 8,       # 2 per tile
    'huge': 16,       # 1 per tile
    'colossal': 32,   # needs 2 tiles (footprint)
}

# Size footprints (tile offsets occupied beyond anchor tile)
SIZE_FOOTPRINT = {
    'tiny': [],
    'small': [],
    'medium': [],
    'large': [],
    'huge': [],
    'colossal': [(1, 0), (0, 1), (1, 1)],  # 2×2
}

TILE_CAPACITY = 16  # total units per tile
