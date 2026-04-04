import os
import sys
import random

import pygame
from dotenv import load_dotenv

from classes.maps import Map, MapKey, Tile
from classes.creature import Creature, Stat
from classes.npc import NPC
from classes.levels import exp_for_level
from save import save, load
from data.db import load as load_db

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
COLOR_EXIT      = (75, 115, 195)
COLOR_PLAYER    = (100, 180, 255)
COLOR_GRID      = (50, 50, 50)

MENU_OPTIONS = ["Resume", "Save", "Load", "Quit"]

def make_map(cols, rows, nested_map=None):
    tiles = {}
    for x in range(cols):
        for y in range(rows):
            tiles[MapKey(0, x, y, 0)] = Tile(
            walkable=random.random() > 0.3
            )

    walkable_keys = [k for k, t in tiles.items() if t.walkable]

    entrance_key = random.choice(walkable_keys)
    entrance = (entrance_key.x, entrance_key.y)

    if nested_map:
        candidates = [k for k in walkable_keys if k != entrance_key]
        if candidates:
            tiles[random.choice(candidates)].nested_map = nested_map

    return Map(tile_set=tiles, entrance=entrance)


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


def draw_menu(surface, selected):
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    surface.blit(overlay, (0, 0))

    title_font = pygame.font.SysFont(None, 64)
    option_font = pygame.font.SysFont(None, 48)

    box_w = 320
    box_h = 80 + len(MENU_OPTIONS) * 55
    box_x = (SCREEN_WIDTH - box_w) // 2
    box_y = (SCREEN_HEIGHT - box_h) // 2

    pygame.draw.rect(surface, (25, 25, 25), (box_x, box_y, box_w, box_h))
    pygame.draw.rect(surface, (120, 120, 120), (box_x, box_y, box_w, box_h), 2)

    title = title_font.render("PAUSED", True, (220, 220, 220))
    surface.blit(title, (box_x + (box_w - title.get_width()) // 2, box_y + 14))

    for i, option in enumerate(MENU_OPTIONS):
        color = COLOR_PLAYER if i == selected else (160, 160, 160)
        text = option_font.render(option, True, color)
        surface.blit(text, (box_x + (box_w - text.get_width()) // 2, box_y + 80 + i * 55))


def main():
    load_db()
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    cols = SCREEN_WIDTH // BLOCK_SIZE
    rows = SCREEN_HEIGHT // BLOCK_SIZE

    nested_map = make_map(cols, rows)
    game_map = make_map(cols, rows, nested_map=nested_map)

    player = Creature(current_map=game_map, location=MapKey(0, *game_map.entrance, 0), stats={Stat.CON: 10})

    npc = NPC(current_map=game_map)

    font = pygame.font.SysFont(None, 28)
    last_move = 0
    paused = False
    menu_idx = 0

    running = True
    while running:
        now = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if paused:
                    if event.key == pygame.K_ESCAPE:
                        paused = False
                    elif event.key == pygame.K_UP:
                        menu_idx = (menu_idx - 1) % len(MENU_OPTIONS)
                    elif event.key == pygame.K_DOWN:
                        menu_idx = (menu_idx + 1) % len(MENU_OPTIONS)
                    elif event.key == pygame.K_RETURN:
                        option = MENU_OPTIONS[menu_idx]
                        if option == "Resume":
                            paused = False
                        elif option == "Save":
                            save(player)
                        elif option == "Load":
                            player = load()
                            for npc in NPC.all():
                                npc._last_move = now
                            paused = False
                        elif option == "Quit":
                            running = False
                else:
                    if event.key == pygame.K_ESCAPE:
                        paused = True
                        menu_idx = 0
                    if event.key == pygame.K_RETURN:
                        if not player.enter():
                            player.exit()
                    if event.key == pygame.K_l:
                        lvl = player.stats.get(Stat.LVL, 0)
                        player.gain_exp(exp_for_level(lvl + 1))

        if not paused and now - last_move >= MOVE_DELAY:
            keys = pygame.key.get_pressed()
            dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
            dy = keys[pygame.K_DOWN] - keys[pygame.K_UP]
            if dx != 0 or dy != 0:
                player.move(dx, dy, cols, rows)
                last_move = now

        if not paused:
            for npc in NPC.all():
                if npc.current_map is player.current_map:
                    npc.update(now, cols, rows)

        screen.fill((30, 30, 30))
        draw_map(screen, player.current_map, cols, rows, BLOCK_SIZE, has_parent=bool(player.map_stack))

        renderables = [player] + [npc for npc in NPC.all() if npc.current_map is player.current_map]
        for obj in sorted(renderables, key=lambda o: o.z_index):
            surface = obj.make_surface(BLOCK_SIZE)
            if surface:
                screen.blit(surface, (obj.location.x * BLOCK_SIZE, obj.location.y * BLOCK_SIZE))

        lvl = player.stats.get(Stat.LVL, 0)
        chp = player.stats.get(Stat.CHP, 0)
        mhp = player.stats.get(Stat.MHP, 0)
        exp = player.stats.get(Stat.EXP, 0)
        exp_next = exp_for_level(lvl + 1)
        hud = font.render(f"LVL {lvl}   HP {chp}/{mhp}   EXP {exp} / +{exp_next}", True, (220, 220, 220))
        screen.blit(hud, (10, SCREEN_HEIGHT - 30))

        if paused:
            draw_menu(screen, menu_idx)

        if DEBUG:
            fps_font = pygame.font.SysFont(None, 36)
            fps_text = fps_font.render(f"FPS: {clock.get_fps():.0f}", True, (0, 255, 0))
            screen.blit(fps_text, (10, 10))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
