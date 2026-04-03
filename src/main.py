import os
import sys
import random

import pygame
from dotenv import load_dotenv

from class_maps import Map, MapKey, Tile
from class_creature import Creature

load_dotenv()

SCREEN_WIDTH = int(os.getenv("SCREEN_WIDTH", 1280))
SCREEN_HEIGHT = int(os.getenv("SCREEN_HEIGHT", 720))
FPS = 300
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

BLOCK_SIZE = 40
MOVE_DELAY = 150

COLOR_WALKABLE  = (60, 90, 60)
COLOR_BLOCKED   = (40, 40, 40)
COLOR_NESTED    = (180, 140, 60)
COLOR_EXIT      = (75, 115, 195)   # inverse of COLOR_NESTED
COLOR_PLAYER    = (100, 180, 255)
COLOR_GRID      = (50, 50, 50)


def make_map(cols, rows, nested_map=None):
    tiles = {}
    for x in range(cols):
        for y in range(rows):
            tiles[MapKey(0, x, y, 0)] = Tile(walkable=random.random() > 0.3)

    walkable_keys = [k for k, t in tiles.items() if t.walkable]

    # Pick entrance and exit from walkable tiles (ensure they differ)
    entrance_key, exit_key = random.sample(walkable_keys, 2)
    entrance = (entrance_key.x, entrance_key.y)
    exit_pos = (exit_key.x, exit_key.y)

    # Place nested map on a walkable tile that isn't entrance or exit
    if nested_map:
        candidates = [k for k in walkable_keys if k not in (entrance_key, exit_key)]
        if candidates:
            tiles[random.choice(candidates)].nested_map = nested_map

    return Map(tile_set=tiles, entrance=entrance, exit=exit_pos)


def draw_map(surface, game_map, cols, rows, block_size, has_parent=False):
    for x in range(cols):
        for y in range(rows):
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
            rect = pygame.Rect(x * block_size, y * block_size, block_size, block_size)
            pygame.draw.rect(surface, color, rect)
            pygame.draw.rect(surface, COLOR_GRID, rect, 1)


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    cols = SCREEN_WIDTH // BLOCK_SIZE
    rows = SCREEN_HEIGHT // BLOCK_SIZE

    nested_map = make_map(cols, rows)
    game_map = make_map(cols, rows, nested_map=nested_map)

    player = Creature(current_map=game_map)
    player.x, player.y = game_map.entrance

    last_move = 0

    running = True
    while running:
        now = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                if event.key == pygame.K_RETURN:
                    if not player.enter():
                        player.exit()

        if now - last_move >= MOVE_DELAY:
            keys = pygame.key.get_pressed()
            dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
            dy = keys[pygame.K_DOWN] - keys[pygame.K_UP]
            if dx != 0 or dy != 0:
                player.move(dx, dy, cols, rows)
                last_move = now

        screen.fill((30, 30, 30))
        draw_map(screen, player.current_map, cols, rows, BLOCK_SIZE, has_parent=bool(player.map_stack))

        player_rect = pygame.Rect(player.x * BLOCK_SIZE, player.y * BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE)
        pygame.draw.rect(screen, COLOR_PLAYER, player_rect)

        if DEBUG:
            font = pygame.font.SysFont(None, 36)
            fps_text = font.render(f"FPS: {clock.get_fps():.0f}", True, (0, 255, 0))
            screen.blit(fps_text, (10, 10))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
