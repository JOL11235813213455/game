"""
Doom-style first-person raycaster.

Uses DDA (Digital Differential Analyzer) to cast rays through the
tile grid. Renders textured walls, floors, ceilings, and sprite
billboards. Integrates with the existing tile/sprite system.

Toggle with V key. Both views share the same game state.
"""
import math
import pygame
from classes.maps import MapKey, DIRECTION_BOUNDS

FOV = math.pi / 3  # 60 degrees
HALF_FOV = FOV / 2
MAX_DEPTH = 40  # max ray distance in tiles
WALL_HEIGHT_SCALE = 1.0


def _get_wall_color(tile, side: int) -> tuple:
    """Get wall color from tile. Side: 0=NS face, 1=EW face."""
    if tile and tile.bg_color:
        try:
            c = pygame.Color(tile.bg_color)
            r, g, b = c.r, c.g, c.b
        except ValueError:
            r, g, b = 100, 100, 100
    elif tile and not tile.walkable:
        r, g, b = 80, 80, 80
    else:
        r, g, b = 120, 100, 80
    if side == 1:
        r, g, b = int(r * 0.7), int(g * 0.7), int(b * 0.7)
    return (r, g, b)


def _get_floor_color(tile) -> tuple:
    if tile and tile.bg_color:
        try:
            c = pygame.Color(tile.bg_color)
            return (c.r, c.g, c.b)
        except ValueError:
            pass
    if tile and getattr(tile, 'liquid', False):
        depth = getattr(tile, 'depth', 0)
        if depth >= 1:
            return (20, 40, 120)
        return (40, 70, 140)
    return (50, 70, 50)


def _get_ceiling_color(tile, covered: bool) -> tuple:
    if covered:
        return (40, 35, 30)
    return (80, 120, 180)


def cast_rays(player_x: float, player_y: float, angle: float,
              game_map, screen_w: int,
              wall_structures: dict = None) -> list:
    """Cast rays for each screen column.

    Returns list of (distance, tile, side, wall_x_frac, hit_x, hit_y)
    for each column. side: 0=NS wall, 1=EW wall.
    wall_x_frac: 0-1 position along the wall face (for texturing).
    """
    results = []
    for col in range(screen_w):
        ray_angle = angle - HALF_FOV + (col / screen_w) * FOV
        sin_a = math.sin(ray_angle)
        cos_a = math.cos(ray_angle)

        # DDA setup
        map_x = int(player_x)
        map_y = int(player_y)

        if cos_a == 0:
            cos_a = 1e-8
        if sin_a == 0:
            sin_a = 1e-8

        delta_dist_x = abs(1.0 / cos_a)
        delta_dist_y = abs(1.0 / sin_a)

        if cos_a < 0:
            step_x = -1
            side_dist_x = (player_x - map_x) * delta_dist_x
        else:
            step_x = 1
            side_dist_x = (map_x + 1.0 - player_x) * delta_dist_x

        if sin_a < 0:
            step_y = -1
            side_dist_y = (player_y - map_y) * delta_dist_y
        else:
            step_y = 1
            side_dist_y = (map_y + 1.0 - player_y) * delta_dist_y

        # DDA loop
        hit = False
        side = 0
        depth = 0
        while depth < MAX_DEPTH:
            if side_dist_x < side_dist_y:
                side_dist_x += delta_dist_x
                map_x += step_x
                side = 0
                depth += 1
            else:
                side_dist_y += delta_dist_y
                map_y += step_y
                side = 1
                depth += 1

            tile = game_map.tiles.get(MapKey(map_x, map_y, 0))

            # Check for wall-faced structure on this tile.
            # wall_face = which wall the sprite is mounted on.
            # Ray going east enters from west → sees 'W' wall.
            if wall_structures:
                if side == 0:
                    face = 'W' if step_x > 0 else 'E'
                else:
                    face = 'N' if step_y > 0 else 'S'
                ws_key = (map_x, map_y, face)
                if ws_key in wall_structures:
                    # Structure hit — compute distance and wall frac
                    if side == 0:
                        perp_dist = side_dist_x - delta_dist_x
                    else:
                        perp_dist = side_dist_y - delta_dist_y
                    perp_dist = max(0.001, perp_dist)
                    perp_dist *= math.cos(ray_angle - angle)
                    if side == 0:
                        wall_x = player_y + perp_dist * sin_a / math.cos(ray_angle - angle)
                    else:
                        wall_x = player_x + perp_dist * cos_a / math.cos(ray_angle - angle)
                    wall_x -= math.floor(wall_x)
                    results.append((perp_dist, tile, side, wall_x,
                                    map_x, map_y))
                    hit = True
                    break

            # Check if this tile blocks the ray
            blocked = False
            if tile is None or not tile.walkable:
                blocked = True
            else:
                # Check bounds: does the previous tile allow exit,
                # and does this tile allow entry?
                if side == 0:
                    # Hit a vertical (EW) wall
                    exit_dir = 'e' if step_x > 0 else 'w'
                    entry_dir = 'w' if step_x > 0 else 'e'
                else:
                    # Hit a horizontal (NS) wall
                    exit_dir = 's' if step_y > 0 else 'n'
                    entry_dir = 'n' if step_y > 0 else 's'

                prev_tile = game_map.tiles.get(
                    MapKey(map_x - step_x if side == 0 else map_x,
                           map_y - step_y if side == 1 else map_y, 0))
                if prev_tile and not getattr(prev_tile.bounds, exit_dir, True):
                    blocked = True
                elif tile and not getattr(tile.bounds, entry_dir, True):
                    blocked = True

            if blocked:
                hit = True
                # Perpendicular distance (fish-eye correction)
                if side == 0:
                    perp_dist = side_dist_x - delta_dist_x
                else:
                    perp_dist = side_dist_y - delta_dist_y
                perp_dist = max(0.001, perp_dist)

                # Fish-eye correction
                perp_dist *= math.cos(ray_angle - angle)

                # Wall hit fraction (for texture mapping)
                if side == 0:
                    wall_x = player_y + perp_dist * sin_a / math.cos(ray_angle - angle)
                else:
                    wall_x = player_x + perp_dist * cos_a / math.cos(ray_angle - angle)
                wall_x -= math.floor(wall_x)

                results.append((perp_dist, tile, side, wall_x,
                                map_x, map_y))
                break

        if not hit:
            results.append((MAX_DEPTH, None, 0, 0, 0, 0))

    return results


def _build_wall_structure_lookup(game_map) -> dict:
    """Build {(tile_x, tile_y, face): structure} for wall-aligned structures."""
    from classes.world_object import WorldObject
    from classes.inventory import Structure
    lookup = {}
    for obj in WorldObject.on_map(game_map):
        if not isinstance(obj, Structure):
            continue
        face = getattr(obj, 'wall_face', None)
        if face:
            key = (obj.location.x, obj.location.y, face)
            lookup[key] = obj
    return lookup


def _get_structure_wall_strip(structure, wall_frac: float,
                               strip_h: int) -> pygame.Surface | None:
    """Sample a vertical strip from a structure's sprite for wall rendering."""
    result = structure.make_surface(32)
    if result is None:
        return None
    surf, _ = result
    sw_s, sh_s = surf.get_size()
    if sw_s <= 0 or sh_s <= 0:
        return None
    src_x = int(wall_frac * (sw_s - 1))
    src_x = max(0, min(sw_s - 1, src_x))
    strip = pygame.Surface((1, strip_h), pygame.SRCALPHA)
    for dy in range(strip_h):
        src_y = int(dy / strip_h * sh_s)
        src_y = min(sh_s - 1, src_y)
        strip.set_at((0, dy), surf.get_at((src_x, src_y)))
    return strip


def render_first_person(screen: pygame.Surface, player, game_map,
                        cols: int, rows: int, game_clock=None):
    """Render the first-person view."""
    from classes.world_object import WorldObject
    from classes.creature import Creature
    from classes.inventory import Structure
    from main.config import SCREEN_WIDTH, SCREEN_HEIGHT

    sw, sh = screen.get_size()
    half_h = sh // 2

    px = player.location.x + player.fp_x
    py = player.location.y + player.fp_y
    angle = player.facing_angle

    # Build wall-structure lookup for this frame
    wall_structures = _build_wall_structure_lookup(game_map)

    # Cast all rays — use Cython TileGrid if available
    from classes.creature import Creature as _CRef
    _tg = _CRef._tile_grid
    if _tg is not None:
        ray_results = _tg.cast_rays(px, py, angle, sw,
                                     wall_structures=wall_structures)
    else:
        ray_results = cast_rays(px, py, angle, game_map, sw,
                                wall_structures=wall_structures)

    # Depth buffer for sprite clipping
    depth_buffer = [MAX_DEPTH] * sw

    # Determine if player is under cover
    player_tile = game_map.tiles.get(player.location)
    player_covered = getattr(player_tile, 'covered', False) if player_tile else False

    # Get ambient light from game clock
    ambient = 1.0
    if game_clock:
        hour = game_clock.hour
        if hour < 6 or hour > 20:
            ambient = 0.3
        elif hour < 8:
            ambient = 0.3 + (hour - 6) * 0.35
        elif hour > 18:
            ambient = 1.0 - (hour - 18) * 0.35

    # Draw sky/ceiling gradient above horizon
    sky_top = (int(40 * ambient), int(80 * ambient), int(160 * ambient))
    sky_bot = (int(100 * ambient), int(150 * ambient), int(220 * ambient))
    if player_covered:
        sky_top = (30, 25, 20)
        sky_bot = (40, 35, 30)
    for y in range(half_h):
        t = y / max(1, half_h)
        r = int(sky_top[0] + (sky_bot[0] - sky_top[0]) * t)
        g = int(sky_top[1] + (sky_bot[1] - sky_top[1]) * t)
        b = int(sky_top[2] + (sky_bot[2] - sky_top[2]) * t)
        pygame.draw.line(screen, (r, g, b), (0, y), (sw - 1, y))

    # Draw floor gradient below horizon
    floor_near = (int(60 * ambient), int(80 * ambient), int(50 * ambient))
    floor_far = (int(30 * ambient), int(40 * ambient), int(25 * ambient))
    for y in range(half_h, sh):
        t = (y - half_h) / max(1, half_h)
        r = int(floor_far[0] + (floor_near[0] - floor_far[0]) * t)
        g = int(floor_far[1] + (floor_near[1] - floor_far[1]) * t)
        b = int(floor_far[2] + (floor_near[2] - floor_far[2]) * t)
        pygame.draw.line(screen, (r, g, b), (0, y), (sw - 1, y))

    # Draw walls column by column
    for col, ray in enumerate(ray_results):
        if len(ray) == 6 and isinstance(ray[1], int):
            # C format: (dist, side, wall_frac, hx, hy, is_wall_struct)
            dist, side, wall_frac, hx, hy, is_ws = ray
            tile = game_map.tiles.get((hx, hy, 0)) if dist < MAX_DEPTH else None
        else:
            # Python format: (dist, tile, side, wall_frac, hx, hy)
            dist, tile, side, wall_frac, hx, hy = ray
        if dist >= MAX_DEPTH:
            depth_buffer[col] = MAX_DEPTH
            continue

        depth_buffer[col] = dist

        # Wall strip height
        line_height = int(sh / dist * WALL_HEIGHT_SCALE)
        draw_start = max(0, half_h - line_height // 2)
        draw_end = min(sh, half_h + line_height // 2)
        strip_h = draw_end - draw_start

        # Check for wall-aligned structure on this face
        # wall_face = which wall the sprite is on. Player east of tile sees 'W' wall.
        if side == 0:
            face = 'W' if hx > px else 'E'
        else:
            face = 'N' if hy > py else 'S'
        ws_key = (hx, hy, face)
        wall_struct = wall_structures.get(ws_key)

        if wall_struct and strip_h > 0:
            strip = _get_structure_wall_strip(wall_struct, wall_frac, strip_h)
            if strip:
                fog = max(0.2, 1.0 - dist / MAX_DEPTH)
                if fog < 0.95 or ambient < 0.95:
                    dark = pygame.Surface((1, strip_h), pygame.SRCALPHA)
                    alpha = int((1.0 - fog * ambient) * 200)
                    dark.fill((0, 0, 0, min(255, alpha)))
                    strip.blit(dark, (0, 0))
                screen.blit(strip, (col, draw_start))
                continue

        # Default wall color with distance fog
        base_color = _get_wall_color(tile, side)
        fog = max(0.2, 1.0 - dist / MAX_DEPTH)
        r = int(base_color[0] * fog * ambient)
        g = int(base_color[1] * fog * ambient)
        b = int(base_color[2] * fog * ambient)
        color = (min(255, r), min(255, g), min(255, b))

        pygame.draw.line(screen, color, (col, draw_start), (col, draw_end))

    # Draw sprite billboards
    _draw_sprites(screen, player, px, py, angle, game_map,
                  depth_buffer, sw, sh, ambient)


def _draw_sprites(screen, player, px, py, angle, game_map,
                  depth_buffer, sw, sh, ambient):
    """Render creatures and structures as billboards."""
    from classes.world_object import WorldObject
    from classes.creature import Creature
    from classes.inventory import Structure

    half_h = sh // 2
    sprites_to_draw = []

    for obj in WorldObject.on_map(player.current_map):
        if obj is player:
            continue
        if not isinstance(obj, (Creature, Structure)):
            continue
        if isinstance(obj, Creature) and not obj.is_alive:
            continue
        if isinstance(obj, Structure) and getattr(obj, 'wall_face', None):
            continue

        ox = obj.location.x + 0.5
        oy = obj.location.y + 0.5
        dx = ox - px
        dy = oy - py
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.1 or dist > MAX_DEPTH:
            continue

        sprite_angle = math.atan2(dy, dx)
        rel_angle = sprite_angle - angle
        # Normalize to -pi..pi
        while rel_angle > math.pi:
            rel_angle -= 2 * math.pi
        while rel_angle < -math.pi:
            rel_angle += 2 * math.pi

        if abs(rel_angle) > HALF_FOV + 0.2:
            continue

        sprites_to_draw.append((dist, rel_angle, obj))

    # Sort back to front
    sprites_to_draw.sort(key=lambda s: -s[0])

    for dist, rel_angle, obj in sprites_to_draw:
        screen_x = int((0.5 + rel_angle / FOV) * sw)

        sprite_height = int(sh / dist * 0.8)
        sprite_width = max(1, sprite_height)

        draw_start_y = half_h - sprite_height // 2
        draw_start_x = screen_x - sprite_width // 2

        # Get sprite surface
        result = obj.make_surface(32)
        if result is None:
            continue
        surf, _ = result

        # Scale to billboard size
        try:
            scaled = pygame.transform.scale(surf, (sprite_width, sprite_height))
        except (pygame.error, ValueError):
            continue

        # Apply fog
        fog = max(0.2, 1.0 - dist / MAX_DEPTH)
        if fog < 0.95:
            dark = pygame.Surface(scaled.get_size(), pygame.SRCALPHA)
            alpha = int((1.0 - fog * ambient) * 200)
            dark.fill((0, 0, 0, min(255, alpha)))
            scaled.blit(dark, (0, 0))

        # Clip against depth buffer column by column
        for sx in range(max(0, draw_start_x), min(sw, draw_start_x + sprite_width)):
            if dist < depth_buffer[sx]:
                src_x = sx - draw_start_x
                strip = scaled.subsurface(pygame.Rect(src_x, 0, 1, sprite_height))
                screen.blit(strip, (sx, draw_start_y))
