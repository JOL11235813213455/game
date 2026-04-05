import pygame
from classes.maps import MapKey
from main.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, get_tile_height,
    COLOR_WALKABLE, COLOR_BLOCKED, COLOR_NESTED, COLOR_EXIT,
    COLOR_PLAYER, COLOR_GRID, MENU_OPTIONS,
)
from main.sprite_cache import get_tiled, get_scaled


def camera_offset(player_loc, cols, rows, block_size):
    """Return (cam_x, cam_y) in pixels -- the world-space origin of the viewport."""
    tile_h = get_tile_height()
    cx = player_loc.x * block_size - SCREEN_WIDTH  // 2 + block_size // 2
    cy = player_loc.y * tile_h     - SCREEN_HEIGHT // 2 + tile_h // 2
    cx = max(0, min(cx, cols * block_size - SCREEN_WIDTH))
    cy = max(0, min(cy, rows * tile_h     - SCREEN_HEIGHT))
    return cx, cy


def _resolve_tile_sprite(tile, time_ms: int) -> str | None:
    """Return the sprite name for a tile, resolving animation if present."""
    anim_name = tile.animation_name
    if anim_name:
        from data.db import ANIMATIONS
        anim = ANIMATIONS.get(anim_name)
        if anim and anim['frames']:
            frames = anim['frames']
            total = anim.get('total_duration_ms')
            if total is None:
                total = sum(f['duration_ms'] for f in frames)
            if total > 0:
                t = time_ms % total
                acc = 0
                for f in frames:
                    acc += f['duration_ms']
                    if t < acc:
                        return f['sprite_name']
                return frames[-1]['sprite_name']
    return tile.sprite_name


def make_tile_surface(tile, block_size, time_ms: int = 0):
    sprite_name = _resolve_tile_sprite(tile, time_ms)
    if not sprite_name:
        return None

    target_w = block_size
    target_h = get_tile_height()

    # Use cached tiled/scaled surface
    return get_tiled(sprite_name, target_w, target_h, block_size)


def draw_map_row(surface, game_map, cols, y, block_size, cam, has_parent=False, time_ms=0):
    """Draw a single row of tiles."""
    cx, cy = cam
    tile_h = get_tile_height()
    sy = y * tile_h - cy
    if sy + tile_h < 0 or sy > SCREEN_HEIGHT:
        return
    for x in range(cols):
        sx = x * block_size - cx
        if sx + block_size < 0 or sx > SCREEN_WIDTH:
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
        rect = pygame.Rect(sx, sy, block_size, tile_h)
        pygame.draw.rect(surface, color, rect)
        if tile and tile.sprite_name:
            tile_surf = make_tile_surface(tile, block_size, time_ms)
            if tile_surf:
                tw, th = tile_surf.get_size()
                surface.blit(tile_surf, (sx + (block_size - tw) // 2, sy + (tile_h - th) // 2))


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
