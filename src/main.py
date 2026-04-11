import os
import sys

# Auto-detect working SDL audio driver before pygame initializes audio
for _drv in ('pipewire', 'pulse', 'alsa', ''):
    os.environ['SDL_AUDIODRIVER'] = _drv
    try:
        import pygame          # noqa: E402
        pygame.mixer.init()
        pygame.mixer.quit()
        break
    except Exception:
        pass

from main.config import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, DEBUG,
    MOVE_DELAY, MENU_OPTIONS,
    get_block_size, get_tile_height, get_zoom, set_zoom, ZOOM_STEP,
)
from classes.creature import Creature, RandomWanderBehavior
from classes.stats import Stat
from classes.inventory import Structure
from classes.world_object import WorldObject
from classes.levels import exp_for_level
from classes.maps import MapKey
from data.db import load as load_db, MAPS, CREATURES, ITEMS
from main.map_gen import make_map
from main.rendering import camera_offset, draw_map_row, draw_menu, draw_debug
from main.save_ui import SaveLoadUI, set_player
from main.game_clock import GameClock
from main.lighting import draw_ambient_overlay, make_shadow, apply_top_highlight
from main.menus import InventoryMenu, QuestLogMenu, HUD

def main():
    load_db()
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    # Spawn into the seeded test_town if it exists, otherwise fall back
    # to a generated map (preserves backward compat for users who haven't
    # run seed_test_world.py yet).
    game_map = MAPS.get('test_town')
    if game_map is None:
        cols = (SCREEN_WIDTH  // get_block_size()) * 3
        rows = (SCREEN_HEIGHT // get_block_size()) * 3
        nested_map = make_map(cols, rows)
        game_map   = make_map(cols, rows, nested_map=nested_map)
    cols = game_map.x_max + 1
    rows = game_map.y_max + 1

    player = Creature(
        current_map=game_map,
        location=MapKey(*game_map.entrance, 0),
        name='Hero',
        species='human',
        stats={Stat.VIT: 10},
    )
    # Spawn the seeded test-town NPCs at their stored locations.
    for npc_key, npc_block in CREATURES.items():
        if npc_block.get('spawn_map') == game_map.name:
            sx = npc_block.get('spawn_x') or 0
            sy = npc_block.get('spawn_y') or 0
            npc = Creature(
                current_map=game_map,
                location=MapKey(sx, sy, 0),
                name=npc_block.get('name', npc_key),
                species=npc_block.get('species', 'human'),
                sex=npc_block.get('sex'),
                age=npc_block.get('age', 25),
                stats=npc_block.get('stats', {}),
                behavior=RandomWanderBehavior(),
            )
            # Stash the dialogue tree key so the player can talk to them
            npc.dialogue_tree = npc_block.get('dialogue_tree')

    clock_font = pygame.font.SysFont(None, 24)
    last_move  = 0
    paused     = False
    menu_idx   = 0
    save_ui    = None   # SaveLoadUI instance when open, else None
    inv_menu   = None   # InventoryMenu instance when open
    quest_menu = None   # QuestLogMenu instance when open
    hud        = HUD()  # always-visible meters
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
                            for c in Creature.all():
                                c._last_move = now

                # ---- inventory menu is open --------------------------------
                elif inv_menu is not None:
                    r = inv_menu.handle_event(event, player)
                    if r == 'close':
                        inv_menu = None

                # ---- quest log is open -------------------------------------
                elif quest_menu is not None:
                    r = quest_menu.handle_event(event, player)
                    if r == 'close':
                        quest_menu = None

                elif event.type == pygame.KEYDOWN:
                    # ---- pause menu -----------------------------------------i want to add this repo to my github. i want to change my global git e-mail to github@jasonlackey.com, which is the same as my github login e-mail.

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
                        if event.key == pygame.K_i:
                            inv_menu = InventoryMenu()
                        if event.key == pygame.K_q:
                            quest_menu = QuestLogMenu()
                        if event.key == pygame.K_RETURN:
                            if not player.enter():
                                player.exit()
                        if event.key == pygame.K_l:
                            lvl = player.stats.active[Stat.LVL]()
                            player.gain_exp(exp_for_level(lvl + 1))
                        if event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                            set_zoom(get_zoom() + ZOOM_STEP)
                        if event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                            set_zoom(get_zoom() - ZOOM_STEP)

        # ---- update ---------------------------------------------------------
        dt = clock.get_time() / 1000.0  # seconds since last frame
        if not paused and save_ui is None:
            keys_held = pygame.key.get_pressed()
            if keys_held[pygame.K_t]:
                game_clock.update(dt * 120)  # hold T: 2 game-hours per real second
            game_clock.update(dt)

        dt_ms = clock.get_time()  # ms since last frame

        if save_ui is None and not paused and now - last_move >= MOVE_DELAY:
            keys = pygame.key.get_pressed()
            dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
            dy = keys[pygame.K_DOWN]  - keys[pygame.K_UP]
            if dx != 0 or dy != 0:
                player.move(dx, dy, cols, rows)
                last_move = now
            else:
                player.play_animation('idle')

        if save_ui is None and not paused:
            map_objects = WorldObject.on_map(player.current_map)
            map_npcs = [o for o in map_objects
                        if isinstance(o, Creature) and o is not player]
            for npc in map_npcs:
                npc.update(now, cols, rows)

            # Update animations on all world objects
            player.anim.update(dt_ms)
            for npc in map_npcs:
                npc.anim.update(dt_ms)

        # ---- render ---------------------------------------------------------
        bs = get_block_size()
        th = get_tile_height()
        cam = camera_offset(player.location, cols, rows, bs)

        screen.fill((30, 30, 30))

        sun_dir    = game_clock.sun_direction
        shadow_len = game_clock.shadow_length_factor
        sun_elev   = game_clock.sun_elevation

        # Pass 1: draw all ground tiles
        has_parent = bool(player.map_stack)
        for y in range(rows):
            draw_map_row(screen, player.current_map, cols, y, bs, cam,
                         has_parent=has_parent, time_ms=now)

        # Pass 2: draw sprites/structures sorted by Y (z_index breaks ties on same tile)
        renderables = [o for o in WorldObject.on_map(player.current_map)
                       if isinstance(o, (Creature, Structure))]
        for obj in sorted(renderables, key=lambda o: (o.location.y, o.z_index)):
            result = obj.make_surface(bs)
            if result:
                sprite_surf, (bdx, bdy) = result
                sx = obj.location.x * bs - cam[0] + bdx
                sy = obj.location.y * th - cam[1] + bdy

                shadow = make_shadow(sprite_surf, sun_dir, shadow_len, bs)
                if shadow:
                    sh_surf, sh_ox, sh_oy = shadow
                    screen.blit(sh_surf, (sx + sh_ox, sy + sh_oy))

                lit = apply_top_highlight(sprite_surf, sun_elev)
                screen.blit(lit, (sx, sy))

        # ambient day/night overlay (after all world rendering, before UI)
        draw_ambient_overlay(screen, game_clock.hour, game_clock.moon_brightness)

        # Rich HUD with HP/STA/MP/HUNGER meters + name/level/gold
        hud.draw(screen, player)

        # clock display with moon phase at night
        time_str = f'{game_clock.format_time()}  {game_clock.format_period()}'
        if not game_clock.is_day:
            time_str += f'  {game_clock.moon_phase_name}'
        time_surf = clock_font.render(time_str, True, (200, 200, 200))
        screen.blit(time_surf, (SCREEN_WIDTH - time_surf.get_width() - 10, SCREEN_HEIGHT - 26))

        if paused and save_ui is None and inv_menu is None and quest_menu is None:
            draw_menu(screen, menu_idx)

        if save_ui is not None:
            save_ui.draw(screen)

        if inv_menu is not None:
            inv_menu.draw(screen, player)

        if quest_menu is not None:
            quest_menu.draw(screen, player)

        if DEBUG:
            draw_debug(screen, clock)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
