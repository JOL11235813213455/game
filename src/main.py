import sys
import pygame

from main.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, DEBUG,
    BLOCK_SIZE, MOVE_DELAY, MENU_OPTIONS,
)
from classes.creature import Creature, NPC, Stat
from classes.levels import exp_for_level
from classes.maps import MapKey
from data.db import load as load_db
from main.map_gen import make_map
from main.rendering import camera_offset, draw_map, draw_menu, draw_hud, draw_debug
from main.save_ui import SaveLoadUI, set_player
from main.game_clock import GameClock
from main.lighting import draw_ambient_overlay, make_shadow, apply_top_highlight

def main():
    load_db()
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    cols = (SCREEN_WIDTH  // BLOCK_SIZE) * 3
    rows = (SCREEN_HEIGHT // BLOCK_SIZE) * 3

    nested_map = make_map(cols, rows)
    game_map   = make_map(cols, rows, nested_map=nested_map)

    player = Creature(
        current_map=game_map,
        location=MapKey(0, *game_map.entrance, 0),
        species='human',
        stats={Stat.CON: 10},
    )
    # Place NPC on a walkable tile near the entrance
    npc_loc = MapKey(0, game_map.entrance[0] + 3, game_map.entrance[1] + 2, 0)
    npcs = [NPC(current_map=game_map, location=npc_loc, species='automaton')]

    font       = pygame.font.SysFont(None, 28)
    clock_font = pygame.font.SysFont(None, 24)
    last_move  = 0
    paused     = False
    menu_idx   = 0
    save_ui    = None   # SaveLoadUI instance when open, else None
    game_clock = GameClock(start_hour=8.0)

    running = True
    while running:
        now = pygame.time.get_ticks()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):

                # ---- save/load UI is open -----------------------------------
                if save_ui is not None:
                    result = save_ui.handle_event(event)
                    if result is not None:
                        if result[0] in ('close', 'saved'):
                            save_ui = None
                        elif result[0] == 'loaded':
                            player  = result[1]
                            save_ui = None
                            paused  = False
                            for npc in NPC.all():
                                npc._last_move = now

                elif event.type == pygame.KEYDOWN:
                    # ---- pause menu -----------------------------------------
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
                                set_player(player)
                                save_ui = SaveLoadUI('save')
                            elif option == "Load":
                                save_ui = SaveLoadUI('load')
                            elif option == "Quit":
                                running = False

                    # ---- gameplay -------------------------------------------
                    else:
                        if event.key == pygame.K_ESCAPE:
                            paused   = True
                            menu_idx = 0
                        if event.key == pygame.K_RETURN:
                            if not player.enter():
                                player.exit()
                        if event.key == pygame.K_l:
                            lvl = player.stats.get(Stat.LVL, 0)
                            player.gain_exp(exp_for_level(lvl + 1))
                        if event.key == pygame.K_t:
                            game_clock.update(60.0)  # advance 1 game hour

        # ---- update ---------------------------------------------------------
        dt = clock.get_time() / 1000.0  # seconds since last frame
        if not paused and save_ui is None:
            game_clock.update(dt)

        if save_ui is None and not paused and now - last_move >= MOVE_DELAY:
            keys = pygame.key.get_pressed()
            dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
            dy = keys[pygame.K_DOWN]  - keys[pygame.K_UP]
            if dx != 0 or dy != 0:
                player.move(dx, dy, cols, rows)
                last_move = now

        if save_ui is None and not paused:
            for npc in NPC.all():
                if npc.current_map is player.current_map:
                    npc.update(now, cols, rows)

        # ---- render ---------------------------------------------------------
        cam = camera_offset(player.location, cols, rows, BLOCK_SIZE)

        screen.fill((30, 30, 30))
        draw_map(screen, player.current_map, cols, rows, BLOCK_SIZE, cam,
                 has_parent=bool(player.map_stack))

        sun_dir    = game_clock.sun_direction
        shadow_len = game_clock.shadow_length_factor
        sun_elev   = game_clock.sun_elevation

        renderables = [player] + [n for n in NPC.all() if n.current_map is player.current_map]
        for obj in sorted(renderables, key=lambda o: o.z_index):
            result = obj.make_surface(BLOCK_SIZE)
            if result:
                sprite_surf, (bdx, bdy) = result
                sx = obj.location.x * BLOCK_SIZE - cam[0] + bdx
                sy = obj.location.y * BLOCK_SIZE - cam[1] + bdy

                # shadow (drawn first, underneath the sprite)
                shadow = make_shadow(sprite_surf, sun_dir, shadow_len, BLOCK_SIZE)
                if shadow:
                    sh_surf, sh_ox, sh_oy = shadow
                    screen.blit(sh_surf, (sx + sh_ox, sy + sh_oy))

                # sprite with top-lighting highlight
                lit = apply_top_highlight(sprite_surf, sun_elev)
                screen.blit(lit, (sx, sy))

        # ambient day/night overlay (after all world rendering, before UI)
        draw_ambient_overlay(screen, game_clock.hour, game_clock.moon_brightness)

        draw_hud(screen, player, font)

        # clock display with moon phase at night
        time_str = f'{game_clock.format_time()}  {game_clock.format_period()}'
        if not game_clock.is_day:
            time_str += f'  {game_clock.moon_phase_name}'
        time_surf = clock_font.render(time_str, True, (200, 200, 200))
        screen.blit(time_surf, (SCREEN_WIDTH - time_surf.get_width() - 10, SCREEN_HEIGHT - 26))

        if paused and save_ui is None:
            draw_menu(screen, menu_idx)

        if save_ui is not None:
            save_ui.draw(screen)

        if DEBUG:
            draw_debug(screen, clock)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
