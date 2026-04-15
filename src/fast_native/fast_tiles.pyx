# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""
Flat C arrays for tile walkability and bounds — fast raycaster + spatial wall queries.

Synced from the Python tile dict once per tick (or on map change).
The raycaster and observation spatial_walls section read from these
arrays instead of doing Python dict lookups per cell.
"""
from libc.stdlib cimport malloc, free
from libc.math cimport fabs, sin, cos, floor, exp
from libc.math cimport M_PI
import numpy as np
cimport numpy as np

np.import_array()

# Bounds bits: packed into a single byte per tile
# bit 0=N, 1=S, 2=E, 3=W, 4=NE, 5=NW, 6=SE, 7=SW
DEF B_N  = 0
DEF B_S  = 1
DEF B_E  = 2
DEF B_W  = 3
DEF B_NE = 4
DEF B_NW = 5
DEF B_SE = 6
DEF B_SW = 7


cdef class TileGrid:
    """Flat C arrays mirroring the Python tile dict for fast spatial queries."""
    cdef unsigned char* walkable   # 1 = walkable, 0 = blocked
    cdef unsigned char* bounds     # packed 8 direction bits per tile
    cdef unsigned char* liquid     # 1 = liquid tile
    cdef unsigned char* covered    # 1 = covered/roofed
    cdef int width, height
    cdef int x_min, y_min

    def __cinit__(self):
        self.walkable = NULL
        self.bounds = NULL
        self.liquid = NULL
        self.covered = NULL
        self.width = self.height = 0

    def __dealloc__(self):
        if self.walkable != NULL: free(self.walkable)
        if self.bounds != NULL:   free(self.bounds)
        if self.liquid != NULL:   free(self.liquid)
        if self.covered != NULL:  free(self.covered)

    def sync(self, game_map):
        """Sync from Python tile dict. Call on map load or tile changes."""
        cdef int w = game_map.x_max - game_map.x_min + 1
        cdef int h = game_map.y_max - game_map.y_min + 1
        self.x_min = game_map.x_min
        self.y_min = game_map.y_min
        self.width = w
        self.height = h

        cdef int n = w * h
        # Allocate (or reallocate)
        if self.walkable != NULL: free(self.walkable)
        if self.bounds != NULL:   free(self.bounds)
        if self.liquid != NULL:   free(self.liquid)
        if self.covered != NULL:  free(self.covered)
        self.walkable = <unsigned char*>malloc(n)
        self.bounds   = <unsigned char*>malloc(n)
        self.liquid   = <unsigned char*>malloc(n)
        self.covered  = <unsigned char*>malloc(n)

        # Zero-fill (default: not walkable, all bounds open, no liquid, no cover)
        cdef int i
        for i in range(n):
            self.walkable[i] = 0
            self.bounds[i] = 0xFF   # all 8 directions open by default
            self.liquid[i] = 0
            self.covered[i] = 0

        # Populate from tile dict
        cdef unsigned char packed
        for key, tile in game_map.tiles.items():
            tx = key.x - self.x_min
            ty = key.y - self.y_min
            if tx < 0 or tx >= w or ty < 0 or ty >= h:
                continue
            idx = ty * w + tx
            self.walkable[idx] = 1 if tile.walkable else 0
            self.liquid[idx] = 1 if getattr(tile, 'liquid', False) else 0
            self.covered[idx] = 1 if getattr(tile, 'covered', False) else 0

            # Pack bounds
            b = getattr(tile, 'bounds', None)
            if b is not None:
                packed = 0
                if getattr(b, 'n', True):  packed |= (1 << B_N)
                if getattr(b, 's', True):  packed |= (1 << B_S)
                if getattr(b, 'e', True):  packed |= (1 << B_E)
                if getattr(b, 'w', True):  packed |= (1 << B_W)
                if getattr(b, 'ne', True): packed |= (1 << B_NE)
                if getattr(b, 'nw', True): packed |= (1 << B_NW)
                if getattr(b, 'se', True): packed |= (1 << B_SE)
                if getattr(b, 'sw', True): packed |= (1 << B_SW)
                self.bounds[idx] = packed

    cdef inline int _idx(self, int x, int y) nogil:
        return (y - self.y_min) * self.width + (x - self.x_min)

    cdef inline bint _in_bounds(self, int x, int y) nogil:
        cdef int lx = x - self.x_min
        cdef int ly = y - self.y_min
        return 0 <= lx < self.width and 0 <= ly < self.height

    cdef inline bint _is_walkable(self, int x, int y) nogil:
        if not self._in_bounds(x, y):
            return 0
        return self.walkable[self._idx(x, y)] != 0

    cdef inline bint _check_exit(self, int x, int y, int bit) nogil:
        """Check if exit in direction `bit` is allowed at tile (x,y)."""
        if not self._in_bounds(x, y):
            return 1  # out of bounds = no restriction
        return (self.bounds[self._idx(x, y)] >> bit) & 1

    def is_walkable(self, int x, int y):
        return bool(self._is_walkable(x, y))

    def is_passable(self, int from_x, int from_y, int to_x, int to_y):
        """Check if movement from (from) to (to) is possible (walkable + bounds)."""
        if not self._is_walkable(to_x, to_y):
            return False
        cdef int dx = to_x - from_x
        cdef int dy = to_y - from_y
        # Check exit direction from source
        cdef int exit_bit, entry_bit
        if dx == 1 and dy == 0:
            exit_bit = B_E; entry_bit = B_W
        elif dx == -1 and dy == 0:
            exit_bit = B_W; entry_bit = B_E
        elif dx == 0 and dy == -1:
            exit_bit = B_N; entry_bit = B_S
        elif dx == 0 and dy == 1:
            exit_bit = B_S; entry_bit = B_N
        elif dx == 1 and dy == -1:
            exit_bit = B_NE; entry_bit = B_SW
        elif dx == -1 and dy == -1:
            exit_bit = B_NW; entry_bit = B_SE
        elif dx == 1 and dy == 1:
            exit_bit = B_SE; entry_bit = B_NW
        elif dx == -1 and dy == 1:
            exit_bit = B_SW; entry_bit = B_NE
        else:
            return True  # same tile or weird offset

        if not self._check_exit(from_x, from_y, exit_bit):
            return False
        if not self._check_exit(to_x, to_y, entry_bit):
            return False
        return True

    def spatial_walls(self, int cx, int cy, int sight):
        """Compute the 25-float spatial_walls section for observation.

        8 ray-cast distances + 8 adjacent passability + 3 ring walkability
        + 3 chokepoint + 2 exit direction = 25 floats.

        Returns a list of 25 floats matching the observation format.
        """
        cdef float sight_f = <float>max(1, sight)
        cdef int dirs[8][2]
        dirs[0][0] = 0;  dirs[0][1] = -1   # N
        dirs[1][0] = 0;  dirs[1][1] = 1    # S
        dirs[2][0] = 1;  dirs[2][1] = 0    # E
        dirs[3][0] = -1; dirs[3][1] = 0    # W
        dirs[4][0] = 1;  dirs[4][1] = -1   # NE
        dirs[5][0] = -1; dirs[5][1] = -1   # NW
        dirs[6][0] = 1;  dirs[6][1] = 1    # SE
        dirs[7][0] = -1; dirs[7][1] = 1    # SW

        result = []
        cdef int dx, dy, step, d, px, py, ppx, ppy, i
        cdef bint passable

        # Ray-cast distances (8)
        for i in range(8):
            dx = dirs[i][0]
            dy = dirs[i][1]
            d = 0
            for step in range(1, sight + 1):
                px = cx + dx * step
                py = cy + dy * step
                if not self._is_walkable(px, py):
                    break
                # Check bounds
                ppx = cx + dx * (step - 1)
                ppy = cy + dy * (step - 1)
                if not self.is_passable(ppx, ppy, px, py):
                    break
                d = step
            result.append(d / sight_f)

        # Adjacent passability (8)
        for i in range(8):
            dx = dirs[i][0]
            dy = dirs[i][1]
            passable = self.is_passable(cx, cy, cx + dx, cy + dy)
            result.append(1.0 if passable else 0.0)

        # Ring walkability (3 rings)
        cdef int ring, ring_tiles, ring_walk, ddx, ddy
        for ring in range(1, 4):
            ring_tiles = 0
            ring_walk = 0
            for ddx in range(-ring, ring + 1):
                for ddy in range(-ring, ring + 1):
                    if abs(ddx) == ring or abs(ddy) == ring:
                        ring_tiles += 1
                        if self._is_walkable(cx + ddx, cy + ddy):
                            ring_walk += 1
            result.append(<float>ring_walk / <float>max(1, ring_tiles))

        # Chokepoint flags
        cdef int adj_walk = 0
        for i in range(4):  # cardinal only
            if self._is_walkable(cx + dirs[i][0], cy + dirs[i][1]):
                adj_walk += 1
        result.append(1.0 if adj_walk <= 2 else 0.0)
        result.append(1.0 if adj_walk >= 6 else 0.0)
        result.append(1.0 if adj_walk <= 2 else 0.0)

        # Exit direction (simplified: 0,0)
        result.append(0.0)
        result.append(0.0)

        return result

    def cast_rays(self, double player_x, double player_y, double angle,
                  int screen_w, int max_depth=40, dict wall_structures=None):
        """DDA raycasting using C tile arrays — zero Python object access in inner loop.

        Returns list of (dist, side, wall_frac, hx, hy, is_wall_struct).
        """
        cdef double half_fov = M_PI / 6.0
        cdef double fov = M_PI / 3.0
        cdef double ray_angle, sin_a, cos_a
        cdef double delta_dist_x, delta_dist_y
        cdef double side_dist_x, side_dist_y
        cdef int step_x, step_y, map_x, map_y
        cdef int side, depth, col
        cdef double perp_dist, wall_x, cos_corr
        cdef int exit_bit, entry_bit, prev_x, prev_y

        results = []

        for col in range(screen_w):
            ray_angle = angle - half_fov + (<double>col / <double>screen_w) * fov
            sin_a = sin(ray_angle)
            cos_a = cos(ray_angle)
            if cos_a == 0.0: cos_a = 1e-8
            if sin_a == 0.0: sin_a = 1e-8

            map_x = <int>player_x
            map_y = <int>player_y
            delta_dist_x = fabs(1.0 / cos_a)
            delta_dist_y = fabs(1.0 / sin_a)

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

            hit = False
            side = 0
            depth = 0
            cos_corr = cos(ray_angle - angle)

            while depth < max_depth:
                if side_dist_x < side_dist_y:
                    side_dist_x += delta_dist_x
                    map_x += step_x
                    side = 0
                else:
                    side_dist_y += delta_dist_y
                    map_y += step_y
                    side = 1
                depth += 1

                # Wall structure check
                if wall_structures is not None:
                    if side == 0:
                        face = 'W' if step_x > 0 else 'E'
                    else:
                        face = 'N' if step_y > 0 else 'S'
                    ws_key = (map_x, map_y, face)
                    if ws_key in wall_structures:
                        if side == 0:
                            perp_dist = side_dist_x - delta_dist_x
                        else:
                            perp_dist = side_dist_y - delta_dist_y
                        if perp_dist < 0.001: perp_dist = 0.001
                        perp_dist *= cos_corr
                        if side == 0:
                            wall_x = player_y + perp_dist * sin_a / cos_corr
                        else:
                            wall_x = player_x + perp_dist * cos_a / cos_corr
                        wall_x -= floor(wall_x)
                        results.append((perp_dist, side, wall_x, map_x, map_y, True))
                        hit = True
                        break

                # C tile array check — no Python dict lookup
                if not self._in_bounds(map_x, map_y) or not self._is_walkable(map_x, map_y):
                    if side == 0:
                        perp_dist = side_dist_x - delta_dist_x
                    else:
                        perp_dist = side_dist_y - delta_dist_y
                    if perp_dist < 0.001: perp_dist = 0.001
                    perp_dist *= cos_corr
                    if side == 0:
                        wall_x = player_y + perp_dist * sin_a / cos_corr
                    else:
                        wall_x = player_x + perp_dist * cos_a / cos_corr
                    wall_x -= floor(wall_x)
                    results.append((perp_dist, side, wall_x, map_x, map_y, False))
                    hit = True
                    break

                # Bounds check via packed bytes
                if side == 0:
                    exit_bit = B_E if step_x > 0 else B_W
                    entry_bit = B_W if step_x > 0 else B_E
                    prev_x = map_x - step_x
                    prev_y = map_y
                else:
                    exit_bit = B_S if step_y > 0 else B_N
                    entry_bit = B_N if step_y > 0 else B_S
                    prev_x = map_x
                    prev_y = map_y - step_y

                if self._in_bounds(prev_x, prev_y) and not self._check_exit(prev_x, prev_y, exit_bit):
                    if side == 0:
                        perp_dist = side_dist_x - delta_dist_x
                    else:
                        perp_dist = side_dist_y - delta_dist_y
                    if perp_dist < 0.001: perp_dist = 0.001
                    perp_dist *= cos_corr
                    if side == 0:
                        wall_x = player_y + perp_dist * sin_a / cos_corr
                    else:
                        wall_x = player_x + perp_dist * cos_a / cos_corr
                    wall_x -= floor(wall_x)
                    results.append((perp_dist, side, wall_x, map_x, map_y, False))
                    hit = True
                    break

                if not self._check_exit(map_x, map_y, entry_bit):
                    if side == 0:
                        perp_dist = side_dist_x - delta_dist_x
                    else:
                        perp_dist = side_dist_y - delta_dist_y
                    if perp_dist < 0.001: perp_dist = 0.001
                    perp_dist *= cos_corr
                    if side == 0:
                        wall_x = player_y + perp_dist * sin_a / cos_corr
                    else:
                        wall_x = player_x + perp_dist * cos_a / cos_corr
                    wall_x -= floor(wall_x)
                    results.append((perp_dist, side, wall_x, map_x, map_y, False))
                    hit = True
                    break

            if not hit:
                results.append((<double>max_depth, 0, 0.0, 0, 0, False))

        return results
