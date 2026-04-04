import pygame
from classes.maps import MapKey
from main.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_WALKABLE, COLOR_BLOCKED, COLOR_NESTED, COLOR_EXIT,
    COLOR_PLAYER, COLOR_GRID, MENU_OPTIONS,
)


def camera_offset(player_loc, cols, rows, block_size):
    """Return (cam_x, cam_y) in pixels -- the world-space origin of the viewport."""
    cx = player_loc.x * block_size - SCREEN_WIDTH  // 2 + block_size // 2
    cy = player_loc.y * block_size - SCREEN_HEIGHT // 2 + block_size // 2
    cx = max(0, min(cx, cols * block_size - SCREEN_WIDTH))
    cy = max(0, min(cy, rows * block_size - SCREEN_HEIGHT))
    return cx, cy


def make_tile_surface(tile, block_size):
    if not tile.sprite_name:
        return None
    from data.db import SPRITE_DATA
    data = SPRITE_DATA.get(tile.sprite_name)
    if not data:
        return None
    pixels  = data['pixels']
    palette = data['palette']
    cols    = len(pixels[0])
    rows    = len(pixels)
    w = int(cols * (block_size / 32) * tile.tile_scale)
    h = int(rows * (block_size / 32) * tile.tile_scale)
    native = pygame.Surface((cols, rows), pygame.SRCALPHA)
    for row_idx, row in enumerate(pixels):
        for col_idx, char in enumerate(row):
            if char == '.' or char not in palette:
                continue
            native.set_at((col_idx, row_idx), palette[char])
    return pygame.transform.scale(native, (w, h))


def draw_map(surface, game_map, cols, rows, block_size, cam, has_parent=False):
    cx, cy = cam
    for x in range(cols):
        for y in range(rows):
            sx = x * block_size - cx
            sy = y * block_size - cy
            if sx + block_size < 0 or sx > SCREEN_WIDTH or sy + block_size < 0 or sy > SCREEN_HEIGHT:
                continue
            tile = game_map.tiles.get(MapKey(0, x, y, 0))
            if (x, y) == game_map.entrance and has_parent:
                color = COLOR_EXIT
            elif tile is None:
                color = COLOR_BLOCKED
            elif tile.nested_map is not None:
                color = COLOR_NESTED
            elif tile.walkable:
                color = COLOR_WALKABLE
            else:
                color = COLOR_BLOCKED
            rect = pygame.Rect(sx, sy, block_size, block_size)
            pygame.draw.rect(surface, color, rect)
            pygame.draw.rect(surface, COLOR_GRID, rect, 1)
            if tile and tile.sprite_name:
                tile_surf = make_tile_surface(tile, block_size)
                if tile_surf:
                    tw, th = tile_surf.get_size()
                    surface.blit(tile_surf, (sx + (block_size - tw) // 2, sy + (block_size - th) // 2))


def draw_menu(surface, selected):
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    surface.blit(overlay, (0, 0))

    title_font  = pygame.font.SysFont(None, 64)
    option_font = pygame.font.SysFont(None, 48)

    box_w = 320
    box_h = 80 + len(MENU_OPTIONS) * 55
    box_x = (SCREEN_WIDTH  - box_w) // 2
    box_y = (SCREEN_HEIGHT - box_h) // 2

    pygame.draw.rect(surface, (25, 25, 25), (box_x, box_y, box_w, box_h))
    pygame.draw.rect(surface, (120, 120, 120), (box_x, box_y, box_w, box_h), 2)

    title = title_font.render("PAUSED", True, (220, 220, 220))
    surface.blit(title, (box_x + (box_w - title.get_width()) // 2, box_y + 14))

    for i, option in enumerate(MENU_OPTIONS):
        color = COLOR_PLAYER if i == selected else (160, 160, 160)
        text = option_font.render(option, True, color)
        surface.blit(text, (box_x + (box_w - text.get_width()) // 2, box_y + 80 + i * 55))


def draw_hud(surface, player, font):
    from classes.creature import Stat
    from classes.levels import exp_for_level
    lvl  = player.stats.get(Stat.LVL, 0)
    chp  = player.stats.get(Stat.CHP, 0)
    mhp  = player.stats.get(Stat.MHP, 0)
    exp  = player.stats.get(Stat.EXP, 0)
    exp_next = exp_for_level(lvl + 1)
    hud = font.render(f"LVL {lvl}   HP {chp}/{mhp}   EXP {exp} / +{exp_next}", True, (220, 220, 220))
    surface.blit(hud, (10, SCREEN_HEIGHT - 30))


def draw_debug(surface, clock):
    fps_font = pygame.font.SysFont(None, 36)
    fps_text = fps_font.render(f"FPS: {clock.get_fps():.0f}", True, (0, 255, 0))
    surface.blit(fps_text, (10, 10))
