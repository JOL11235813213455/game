"""
Live simulation viewer — pygame window showing creatures on a map.

Launched from the Training tab. Renders the headless simulation
in real-time using tile sprites and creature positions.
"""
from __future__ import annotations
import sys
import time
import random
import numpy as np
from pathlib import Path

_SRC = Path(__file__).parent.parent.parent / 'src'
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pygame
from classes.maps import MapKey
from classes.creature import Creature
from classes.world_object import WorldObject
from classes.stats import Stat
from editor.simulation.arena import generate_arena, generate_trade_scenario


# Colors
C_GRASS = (34, 139, 34)
C_DIRT  = (139, 90, 43)
C_SAND  = (210, 190, 130)
C_WATER = (30, 100, 200)
C_BLACK = (0, 0, 0)
C_WHITE = (255, 255, 255)
C_RED   = (200, 40, 40)
C_GREEN = (40, 200, 40)
C_BLUE  = (40, 80, 200)
C_YELLOW = (220, 180, 40)
C_GRAY  = (120, 120, 120)
C_ORANGE = (220, 140, 40)
C_PINK  = (220, 120, 160)

TILE_COLORS = {
    'grass': C_GRASS, 'dirt': C_DIRT, 'sand': C_SAND, 'water': C_WATER,
}

SPECIES_COLORS = {
    'human': C_BLUE, 'orc': C_GREEN, 'bug': C_GRAY,
}


def run_viewer(scenario: str = 'arena', cols: int = 25, rows: int = 25,
               num_creatures: int = 12, tick_ms: int = 500,
               cell_size: int = 20):
    """Run the live simulation viewer.

    Args:
        scenario: 'arena' or 'trade'
        cols, rows: map dimensions
        num_creatures: creatures to spawn
        tick_ms: ms per simulation tick
        cell_size: pixel size per tile
    """
    pygame.init()
    width = cols * cell_size + 300  # extra space for info panel
    height = rows * cell_size
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption('Simulation Viewer')
    font = pygame.font.SysFont('monospace', 12)
    font_sm = pygame.font.SysFont('monospace', 10)
    clock = pygame.time.Clock()

    # Create simulation
    if scenario == 'trade':
        arena = generate_trade_scenario(cols=cols, rows=rows, num_creatures=num_creatures)
    else:
        arena = generate_arena(cols=cols, rows=rows, num_creatures=num_creatures,
                               species_mix={'human': 0.6, 'orc': 0.3, 'bug': 0.1})

    from editor.simulation.headless import Simulation
    sim = Simulation(arena)

    # Disable built-in behavior — let StatWeightedBehavior drive
    from classes.creature import StatWeightedBehavior
    for c in sim.creatures:
        c.behavior = StatWeightedBehavior()
        c.register_tick('behavior', tick_ms, c._do_behavior)

    game_map = arena['map']
    paused = False
    selected = None  # selected creature for info
    sim_speed = 1.0
    tick_accum = 0.0

    running = True
    while running:
        dt = clock.tick(30)  # 30 FPS rendering

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
                    sim_speed = min(10.0, sim_speed * 1.5)
                elif event.key == pygame.K_MINUS:
                    sim_speed = max(0.1, sim_speed / 1.5)
                elif event.key == pygame.K_r:
                    # Reset
                    if scenario == 'trade':
                        arena = generate_trade_scenario(cols=cols, rows=rows, num_creatures=num_creatures)
                    else:
                        arena = generate_arena(cols=cols, rows=rows, num_creatures=num_creatures,
                                               species_mix={'human': 0.6, 'orc': 0.3, 'bug': 0.1})
                    sim = Simulation(arena)
                    for c in sim.creatures:
                        c.behavior = StatWeightedBehavior()
                        c.register_tick('behavior', tick_ms, c._do_behavior)
                    game_map = arena['map']
                    selected = None
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                tx = mx // cell_size
                ty = my // cell_size
                # Find creature at this tile
                selected = None
                for c in sim.creatures:
                    if c.location.x == tx and c.location.y == ty:
                        selected = c
                        break

        # Advance simulation
        if not paused:
            tick_accum += dt * sim_speed
            while tick_accum >= tick_ms:
                tick_accum -= tick_ms
                sim.now += tick_ms
                sim.step_count += 1
                for c in sim.creatures:
                    if c.is_alive:
                        c.update(sim.now, cols, rows)

        # ---- RENDER ----
        screen.fill(C_BLACK)

        # Tiles
        for x in range(cols):
            for y in range(rows):
                tile = game_map.tiles.get(MapKey(x, y, 0))
                if tile:
                    tmpl = tile.tile_template or 'grass'
                    color = TILE_COLORS.get(tmpl, C_GRAY)
                    # Slightly vary color for visual interest
                    r, g, b = color
                    noise = ((x * 7 + y * 13) % 20) - 10
                    color = (max(0, min(255, r + noise)),
                             max(0, min(255, g + noise)),
                             max(0, min(255, b + noise)))
                    pygame.draw.rect(screen, color,
                                     (x * cell_size, y * cell_size, cell_size, cell_size))

                    # Gold on tile
                    if tile.gold > 0:
                        pygame.draw.circle(screen, C_YELLOW,
                                           (x * cell_size + cell_size // 2,
                                            y * cell_size + cell_size // 2), 3)

                    # Items on tile
                    if tile.inventory.items:
                        pygame.draw.rect(screen, C_ORANGE,
                                         (x * cell_size + 1, y * cell_size + 1, 4, 4))

        # Creatures
        for c in sim.creatures:
            if not c.is_alive:
                continue
            cx = c.location.x * cell_size + cell_size // 2
            cy = c.location.y * cell_size + cell_size // 2

            # Body color by species
            color = SPECIES_COLORS.get(c.species, C_WHITE)
            if c.sex == 'female':
                # Slightly lighter for females
                r, g, b = color
                color = (min(255, r + 40), min(255, g + 40), min(255, b + 40))

            size = {'tiny': 3, 'small': 4, 'medium': 5, 'large': 7, 'huge': 9, 'colossal': 12}
            radius = size.get(c.size, 5)
            pygame.draw.circle(screen, color, (cx, cy), radius)

            # HP bar
            hp_ratio = c.stats.active[Stat.HP_CURR]() / max(1, c.stats.active[Stat.HP_MAX]())
            bar_w = cell_size - 4
            bar_x = c.location.x * cell_size + 2
            bar_y = c.location.y * cell_size - 3
            pygame.draw.rect(screen, C_RED, (bar_x, bar_y, bar_w, 2))
            pygame.draw.rect(screen, C_GREEN, (bar_x, bar_y, int(bar_w * hp_ratio), 2))

            # Selection highlight
            if c is selected:
                pygame.draw.circle(screen, C_YELLOW, (cx, cy), radius + 3, 1)

            # Name for named creatures
            if c.name and len(c.name) < 15:
                label = font_sm.render(c.name[:8], True, C_WHITE)
                screen.blit(label, (cx - label.get_width() // 2, cy + radius + 1))

        # ---- INFO PANEL ----
        panel_x = cols * cell_size + 10
        y = 10

        def text(s, color=C_WHITE, bold=False):
            nonlocal y
            f = font if not bold else font
            surf = f.render(s, True, color)
            screen.blit(surf, (panel_x, y))
            y += 15

        text(f'Tick: {sim.step_count}', C_YELLOW)
        text(f'Time: {sim.now / 1000:.0f}s')
        text(f'Alive: {sim.alive_count} / {len(sim.creatures)}')
        text(f'Speed: {sim_speed:.1f}x')
        text(f'{"PAUSED" if paused else "RUNNING"}', C_RED if paused else C_GREEN)
        y += 10
        text('[Space] Pause  [+/-] Speed', C_GRAY)
        text('[R] Reset  [Click] Select', C_GRAY)
        y += 10

        # Selected creature info
        if selected and selected.is_alive:
            text(f'--- {selected.name or "?"} ---', C_YELLOW)
            text(f'Species: {selected.species}  Sex: {selected.sex}')
            text(f'Age: {selected.age}  Lvl: {selected.stats.base.get(Stat.LVL, 0)}')
            hp = selected.stats.active[Stat.HP_CURR]()
            hp_max = selected.stats.active[Stat.HP_MAX]()
            text(f'HP: {hp}/{hp_max}')
            text(f'Stam: {selected.stats.active[Stat.CUR_STAMINA]()}/{selected.stats.active[Stat.MAX_STAMINA]()}')
            text(f'Gold: {selected.gold}')
            text(f'Items: {len(selected.inventory.items)}')
            text(f'Equip: {len(selected.equipment)}')
            if selected.deity:
                text(f'Deity: {selected.deity} ({selected.piety:.1f})')
            text(f'Allies: {sum(1 for r in selected.relationships.values() if r[0] > 5)}')
            text(f'Enemies: {sum(1 for r in selected.relationships.values() if r[0] < -5)}')
            if selected.observation_mask:
                text(f'Mask: {selected.observation_mask}', C_ORANGE)
            if selected.is_pregnant:
                text('PREGNANT', C_PINK)
            if selected.has_partner:
                text('PAIRED', C_PINK)

            y += 5
            text('Stats:', C_GRAY)
            for stat in [Stat.STR, Stat.VIT, Stat.AGL, Stat.PER, Stat.INT, Stat.CHR, Stat.LCK]:
                val = selected.stats.active[stat]()
                text(f'  {stat.name}: {val}')
        elif selected:
            text(f'{selected.name or "?"} — DEAD', C_RED)

        # Population summary
        y = height - 120
        text('--- Population ---', C_GRAY)
        species_count = {}
        total_gold = 0
        for c in sim.creatures:
            if c.is_alive:
                species_count[c.species] = species_count.get(c.species, 0) + 1
                total_gold += c.gold
        for sp, n in sorted(species_count.items()):
            text(f'  {sp}: {n}', SPECIES_COLORS.get(sp, C_WHITE))
        text(f'Total gold: {total_gold}')
        tile_gold = sum(t.gold for t in game_map.tiles.values())
        text(f'Ground gold: {tile_gold}')

        pygame.display.flip()

    pygame.quit()


def run_training_viewer(cell_size: int = 20):
    """Watch live training — reads state from training process."""
    from editor.simulation.train_state import read_state

    pygame.init()
    # Start with a default size, resize when we get data
    screen = pygame.display.set_mode((800, 600), pygame.RESIZABLE)
    pygame.display.set_caption('Training Viewer (LIVE)')
    font = pygame.font.SysFont('monospace', 12)
    font_sm = pygame.font.SysFont('monospace', 10)
    font_lg = pygame.font.SysFont('monospace', 16)
    clock = pygame.time.Clock()

    selected_uid = None
    cols = rows = 25  # default until we get data

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                tx = mx // cell_size
                ty = my // cell_size
                state = read_state()
                if state:
                    selected_uid = None
                    for c in state['creatures']:
                        if c['x'] == tx and c['y'] == ty and c['alive']:
                            selected_uid = c['uid']
                            break

        state = read_state()

        screen.fill(C_BLACK)

        if state is None:
            surf = font_lg.render('Waiting for training to start...', True, C_YELLOW)
            screen.blit(surf, (50, 50))
            surf2 = font.render('Start training from the Training tab', True, C_GRAY)
            screen.blit(surf2, (50, 80))
            pygame.display.flip()
            clock.tick(5)
            continue

        cols = state['cols']
        rows = state['rows']
        panel_w = 300
        need_w = cols * cell_size + panel_w
        need_h = rows * cell_size
        if screen.get_width() != need_w or screen.get_height() != need_h:
            screen = pygame.display.set_mode((need_w, need_h))

        # Draw base tile grid
        for x in range(cols):
            for y in range(rows):
                r, g, b = C_GRASS
                noise = ((x * 7 + y * 13) % 20) - 10
                color = (max(0, min(255, r + noise)),
                         max(0, min(255, g + noise)),
                         max(0, min(255, b + noise)))
                pygame.draw.rect(screen, color,
                                 (x * cell_size, y * cell_size, cell_size, cell_size))

        # Overlay tile info (gold, items, water tiles)
        for ti in state.get('tile_info', []):
            tx, ty = ti['x'], ti['y']
            tmpl = ti.get('template', 'grass')
            if tmpl != 'grass':
                color = TILE_COLORS.get(tmpl, C_GRASS)
                pygame.draw.rect(screen, color,
                                 (tx * cell_size, ty * cell_size, cell_size, cell_size))
            if ti['gold'] > 0:
                pygame.draw.circle(screen, C_YELLOW,
                                   (tx * cell_size + cell_size // 2,
                                    ty * cell_size + cell_size // 2), 3)
            if ti['items'] > 0:
                pygame.draw.rect(screen, C_ORANGE,
                                 (tx * cell_size + 1, ty * cell_size + 1, 4, 4))

        # Draw creatures
        selected_data = None
        for c in state['creatures']:
            if not c['alive']:
                continue
            cx = c['x'] * cell_size + cell_size // 2
            cy = c['y'] * cell_size + cell_size // 2

            color = SPECIES_COLORS.get(c['species'], C_WHITE)
            if c['sex'] == 'female':
                r, g, b = color
                color = (min(255, r + 40), min(255, g + 40), min(255, b + 40))

            sizes = {'tiny': 3, 'small': 4, 'medium': 5, 'large': 7, 'huge': 9, 'colossal': 12}
            radius = sizes.get(c['size'], 5)
            pygame.draw.circle(screen, color, (cx, cy), radius)

            # HP bar
            hp_ratio = c['hp'] / max(1, c['hp_max'])
            bar_w = cell_size - 4
            bar_x = c['x'] * cell_size + 2
            bar_y = c['y'] * cell_size - 3
            pygame.draw.rect(screen, C_RED, (bar_x, bar_y, bar_w, 2))
            pygame.draw.rect(screen, C_GREEN, (bar_x, bar_y, int(bar_w * hp_ratio), 2))

            # Selection
            if c['uid'] == selected_uid:
                pygame.draw.circle(screen, C_YELLOW, (cx, cy), radius + 3, 1)
                selected_data = c

            # Name
            if c['name']:
                label = font_sm.render(c['name'][:8], True, C_WHITE)
                screen.blit(label, (cx - label.get_width() // 2, cy + radius + 1))

        # Info panel
        panel_x = cols * cell_size + 10
        y = 10

        def text(s, color=C_WHITE):
            nonlocal y
            screen.blit(font.render(s, True, color), (panel_x, y))
            y += 15

        stale = state.get('stale', False)
        phase = state.get('phase', '?')
        text(f'Phase: {phase}', C_YELLOW if not stale else C_RED)
        text(f'Step: {state["step"]}')
        text(f'Tick: {state["tick"]}')
        text(f'Alive: {state["alive"]} / {state["total"]}')
        if stale:
            text('STALE — training may have stopped', C_RED)
        y += 5

        # Training stats from info dict
        info = state.get('info', {})
        if info:
            avg_r = info.get('avg_reward', 0)
            tot_r = info.get('total_reward', 0)
            color_r = C_GREEN if avg_r > 0 else C_RED if avg_r < 0 else C_GRAY
            text(f'Avg reward: {avg_r:+.4f}', color_r)
            text(f'Total reward: {tot_r:+.2f}', color_r)
            text(f'Ep steps: {info.get("ep_steps", 0)}')
            y += 5
            top_acts = info.get('top_actions', [])
            if top_acts:
                text('Decisions:  10s / cum', C_GRAY)
                for entry in top_acts:
                    if len(entry) == 3:
                        name, trail, cum = entry
                        text(f'  {name}: {trail}/{cum}', C_WHITE)
                    else:
                        name, cum = entry[0], entry[-1]
                        text(f'  {name}: {cum}', C_WHITE)
            y += 5

        # Selected creature
        if selected_data:
            c = selected_data
            text(f'--- {c["name"]} ---', C_YELLOW)
            text(f'Species: {c["species"]}  Sex: {c["sex"]}')
            text(f'HP: {c["hp"]}/{c["hp_max"]}')
            text(f'Gold: {c["gold"]}')
            text(f'Items: {c["items"]}  Equip: {c["equip"]}')
            if c.get('deity'):
                text(f'Deity: {c["deity"]}')
            if c.get('mask'):
                text(f'Mask: {c["mask"]}', C_ORANGE)

        # Population
        y = need_h - 100
        text('--- Population ---', C_GRAY)
        sp_count = {}
        total_gold = 0
        total_items = 0
        total_equip = 0
        for c in state['creatures']:
            if c['alive']:
                sp_count[c['species']] = sp_count.get(c['species'], 0) + 1
                total_gold += c['gold']
                total_items += c['items']
                total_equip += c['equip']
        for sp, n in sorted(sp_count.items()):
            text(f'  {sp}: {n}', SPECIES_COLORS.get(sp, C_WHITE))
        text(f'Gold: {total_gold}  Items: {total_items}  Equip: {total_equip}')
        tile_gold = sum(ti['gold'] for ti in state.get('tile_info', []))
        text(f'Ground gold: {tile_gold}')

        pygame.display.flip()
        clock.tick(15)  # 15 FPS for viewer — training writes every 10 ticks

    pygame.quit()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', default='arena', choices=['arena', 'trade', 'training'])
    parser.add_argument('--cols', type=int, default=25)
    parser.add_argument('--rows', type=int, default=25)
    parser.add_argument('--creatures', type=int, default=12)
    parser.add_argument('--cell', type=int, default=20)
    args = parser.parse_args()
    if args.scenario == 'training':
        run_training_viewer(cell_size=args.cell)
    else:
        run_viewer(scenario=args.scenario, cols=args.cols, rows=args.rows,
                   num_creatures=args.creatures, cell_size=args.cell)
