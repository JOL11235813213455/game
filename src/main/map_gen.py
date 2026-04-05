import random
from classes.maps import Map, MapKey, Tile


def make_map(cols, rows, nested_map=None):
    tiles = {}
    for x in range(cols):
        for y in range(rows):
            walkable = random.random() > 0.3
            tiles[MapKey(0, x, y, 0)] = Tile(
                walkable=walkable,
                sprite_name='grass_frame_1' if walkable else None,
                animation_name='grass_breeze' if walkable else None,
            )

    walkable_keys = [k for k, t in tiles.items() if t.walkable]
    entrance_key = random.choice(walkable_keys)
    entrance = (entrance_key.x, entrance_key.y)

    if nested_map:
        candidates = [k for k in walkable_keys if k != entrance_key]
        if candidates:
            tiles[random.choice(candidates)].nested_map = nested_map

    return Map(tile_set=tiles, entrance=entrance)
