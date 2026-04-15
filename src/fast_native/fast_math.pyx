# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""
Fast math helpers for observation, reward, and neural network inference.

Replaces pure-Python math operations with C-level implementations.
Covers: ln transforms, stat modifiers, softmax, relu, layer norm,
neural network forward passes, and DDA raycasting.
"""
from libc.math cimport log, exp, sqrt, fabs, copysign, sin, cos, floor, atan2, M_PI
from libc.stdlib cimport malloc, free
import numpy as np
cimport numpy as np

np.import_array()

# ---------------------------------------------------------------------------
# Math helpers (observation + reward)
# ---------------------------------------------------------------------------

cpdef double c_ln_ratio(double after, double before, double eps=0.001):
    """ln(after / before) with safety for zero/negative."""
    cdef double a = after if after > eps else eps
    cdef double b = before if before > eps else eps
    return log(a / b)

cpdef double c_sln(double x):
    """Signed ln: sign(x) * ln(|x| + 1)."""
    if x == 0.0:
        return 0.0
    return copysign(log(fabs(x) + 1.0), x)

cpdef double c_dmod(double stat_val):
    """D&D-style stat modifier: (stat - 10) // 2."""
    return <double>(<int>(stat_val - 10) >> 1)

cpdef double c_clamp(double x, double lo, double hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x

# ---------------------------------------------------------------------------
# Ratio transform helpers (observation math transforms section)
# ---------------------------------------------------------------------------

def c_ratio_transforms(double val, double ref):
    """Return [ratio, ln_ratio, delta] for a value relative to reference."""
    cdef double ratio, ln_r, delta
    if ref == 0.0:
        ref = 0.001
    ratio = val / ref
    ln_r = log(fabs(ratio) + 0.001) if ratio != 0.0 else 0.0
    delta = val - ref
    return [ratio, ln_r, delta]

def c_signed_transforms(double val):
    """Return [val, abs, sign, ln_abs, sq_sign] for a signed value."""
    cdef double a = fabs(val)
    cdef double s = 1.0 if val > 0 else (-1.0 if val < 0 else 0.0)
    cdef double ln_a = log(a + 0.001)
    cdef double sq = copysign(sqrt(a), val)
    return [val, a, s, ln_a, sq]

def c_dist_transforms(double dist, double sight):
    """Return [normalized, inv_urgency, exp_decay, urgency_close] for distance."""
    cdef double mx = sight if sight > 0.1 else 0.1
    cdef double norm = dist / mx
    cdef double inv = 1.0 / (dist + 1.0)
    cdef double decay = exp(-dist * 0.3)
    cdef double urgency
    if dist > 0:
        urgency = 1.0 / (0.1 + dist)
        if urgency > 5.0:
            urgency = 5.0
    else:
        urgency = 5.0
    return [norm, inv, decay, urgency]


# ---------------------------------------------------------------------------
# Neural network operations
# ---------------------------------------------------------------------------

def c_relu(np.ndarray[np.float32_t, ndim=2] x):
    """In-place ReLU on 2D array."""
    cdef int i, j
    cdef int rows = x.shape[0]
    cdef int cols = x.shape[1]
    for i in range(rows):
        for j in range(cols):
            if x[i, j] < 0:
                x[i, j] = 0
    return x

def c_relu_1d(np.ndarray[np.float32_t, ndim=1] x):
    """In-place ReLU on 1D array."""
    cdef int i
    cdef int n = x.shape[0]
    for i in range(n):
        if x[i] < 0:
            x[i] = 0
    return x

def c_softmax(np.ndarray[np.float32_t, ndim=2] x):
    """Row-wise softmax with numerical stability."""
    cdef int i, j
    cdef int rows = x.shape[0]
    cdef int cols = x.shape[1]
    cdef float row_max, row_sum
    for i in range(rows):
        row_max = x[i, 0]
        for j in range(1, cols):
            if x[i, j] > row_max:
                row_max = x[i, j]
        row_sum = 0.0
        for j in range(cols):
            x[i, j] = exp(x[i, j] - row_max)
            row_sum += x[i, j]
        if row_sum > 0:
            for j in range(cols):
                x[i, j] /= row_sum
    return x

def c_layer_norm(np.ndarray[np.float32_t, ndim=1] x,
                 np.ndarray[np.float32_t, ndim=1] gamma,
                 np.ndarray[np.float32_t, ndim=1] beta,
                 float eps=1e-5):
    """Layer normalization on 1D vector."""
    cdef int i
    cdef int n = x.shape[0]
    cdef float mean = 0.0
    cdef float var = 0.0
    cdef float diff
    cdef float inv_std
    for i in range(n):
        mean += x[i]
    mean /= n
    for i in range(n):
        diff = x[i] - mean
        var += diff * diff
    var /= n
    inv_std = 1.0 / sqrt(var + eps)
    cdef np.ndarray[np.float32_t, ndim=1] out = np.empty(n, dtype=np.float32)
    for i in range(n):
        out[i] = gamma[i] * (x[i] - mean) * inv_std + beta[i]
    return out

def c_forward_5layer(np.ndarray[np.float32_t, ndim=1] obs,
                     np.ndarray[np.float32_t, ndim=2] w1,
                     np.ndarray[np.float32_t, ndim=1] b1,
                     np.ndarray[np.float32_t, ndim=2] w2,
                     np.ndarray[np.float32_t, ndim=1] b2,
                     np.ndarray[np.float32_t, ndim=2] w3,
                     np.ndarray[np.float32_t, ndim=1] b3,
                     np.ndarray[np.float32_t, ndim=2] w4,
                     np.ndarray[np.float32_t, ndim=1] b4,
                     np.ndarray[np.float32_t, ndim=2] w5,
                     np.ndarray[np.float32_t, ndim=1] b5,
                     np.ndarray[np.float32_t, ndim=2] w_pol,
                     np.ndarray[np.float32_t, ndim=1] b_pol):
    """5-layer feedforward network: obs → h1 → h2 → h3 → h4 → h5 → policy logits.

    Returns softmax probabilities.
    """
    cdef np.ndarray[np.float32_t, ndim=1] h
    h = np.ascontiguousarray(obs @ w1 + b1, dtype=np.float32)
    c_relu_1d(h)
    h = np.ascontiguousarray(h @ w2 + b2, dtype=np.float32)
    c_relu_1d(h)
    h = np.ascontiguousarray(h @ w3 + b3, dtype=np.float32)
    c_relu_1d(h)
    h = np.ascontiguousarray(h @ w4 + b4, dtype=np.float32)
    c_relu_1d(h)
    h = np.ascontiguousarray(h @ w5 + b5, dtype=np.float32)
    c_relu_1d(h)
    cdef np.ndarray[np.float32_t, ndim=1] logits = np.ascontiguousarray(
        h @ w_pol + b_pol, dtype=np.float32)
    # Softmax
    cdef int i, n = logits.shape[0]
    cdef float mx = logits[0]
    cdef float s = 0.0
    for i in range(1, n):
        if logits[i] > mx:
            mx = logits[i]
    for i in range(n):
        logits[i] = exp(logits[i] - mx)
        s += logits[i]
    if s > 0:
        for i in range(n):
            logits[i] /= s
    return logits

def c_forward_3layer_ln(np.ndarray[np.float32_t, ndim=1] obs,
                        np.ndarray[np.float32_t, ndim=2] w1,
                        np.ndarray[np.float32_t, ndim=1] b1,
                        np.ndarray[np.float32_t, ndim=1] ln1_g,
                        np.ndarray[np.float32_t, ndim=1] ln1_b,
                        np.ndarray[np.float32_t, ndim=2] w2,
                        np.ndarray[np.float32_t, ndim=1] b2,
                        np.ndarray[np.float32_t, ndim=1] ln2_g,
                        np.ndarray[np.float32_t, ndim=1] ln2_b,
                        np.ndarray[np.float32_t, ndim=2] w3,
                        np.ndarray[np.float32_t, ndim=1] b3,
                        np.ndarray[np.float32_t, ndim=1] ln3_g,
                        np.ndarray[np.float32_t, ndim=1] ln3_b,
                        np.ndarray[np.float32_t, ndim=2] w_out,
                        np.ndarray[np.float32_t, ndim=1] b_out):
    """3-layer network with LayerNorm: obs → LN(h1) → LN(h2) → LN(h3) → logits."""
    cdef np.ndarray[np.float32_t, ndim=1] h
    h = np.ascontiguousarray(obs @ w1 + b1, dtype=np.float32)
    h = c_layer_norm(h, ln1_g, ln1_b)
    c_relu_1d(h)
    h = np.ascontiguousarray(h @ w2 + b2, dtype=np.float32)
    h = c_layer_norm(h, ln2_g, ln2_b)
    c_relu_1d(h)
    h = np.ascontiguousarray(h @ w3 + b3, dtype=np.float32)
    h = c_layer_norm(h, ln3_g, ln3_b)
    c_relu_1d(h)
    return np.ascontiguousarray(h @ w_out + b_out, dtype=np.float32)


# ---------------------------------------------------------------------------
# DDA Raycasting
# ---------------------------------------------------------------------------

def c_cast_rays(double player_x, double player_y, double angle,
                dict tiles, int screen_w, int max_depth=40,
                dict wall_structures=None):
    """Cast rays using DDA. Returns list of (dist, side, wall_frac, hx, hy, is_wall_struct).

    tiles: {(x,y,z): tile_obj} — checked for .walkable and .bounds attributes.
    wall_structures: {(x,y,face): struct_obj} or None.
    """
    cdef double half_fov = M_PI / 6.0  # 30 degrees half
    cdef double fov = M_PI / 3.0
    cdef double ray_angle, sin_a, cos_a
    cdef double delta_dist_x, delta_dist_y
    cdef double side_dist_x, side_dist_y
    cdef int step_x, step_y, map_x, map_y
    cdef int side, depth, col
    cdef double perp_dist, wall_x
    cdef bint hit, blocked

    results = []
    cdef double cos_correction

    for col in range(screen_w):
        ray_angle = angle - half_fov + (<double>col / <double>screen_w) * fov
        sin_a = sin(ray_angle)
        cos_a = cos(ray_angle)
        if cos_a == 0.0:
            cos_a = 1e-8
        if sin_a == 0.0:
            sin_a = 1e-8

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
        cos_correction = cos(ray_angle - angle)

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
                    if perp_dist < 0.001:
                        perp_dist = 0.001
                    perp_dist *= cos_correction
                    if side == 0:
                        wall_x = player_y + perp_dist * sin_a / cos_correction
                    else:
                        wall_x = player_x + perp_dist * cos_a / cos_correction
                    wall_x -= floor(wall_x)
                    results.append((perp_dist, side, wall_x, map_x, map_y, True))
                    hit = True
                    break

            # Tile check
            tile_key = (map_x, map_y, 0)
            tile = tiles.get(tile_key)
            blocked = False
            if tile is None or not getattr(tile, 'walkable', True):
                blocked = True
            else:
                if side == 0:
                    exit_dir = 'e' if step_x > 0 else 'w'
                    entry_dir = 'w' if step_x > 0 else 'e'
                else:
                    exit_dir = 's' if step_y > 0 else 'n'
                    entry_dir = 'n' if step_y > 0 else 's'
                prev_key = (map_x - step_x if side == 0 else map_x,
                            map_y - step_y if side == 1 else map_y, 0)
                prev_tile = tiles.get(prev_key)
                if prev_tile is not None and not getattr(getattr(prev_tile, 'bounds', None), exit_dir, True):
                    blocked = True
                elif tile is not None and not getattr(getattr(tile, 'bounds', None), entry_dir, True):
                    blocked = True

            if blocked:
                if side == 0:
                    perp_dist = side_dist_x - delta_dist_x
                else:
                    perp_dist = side_dist_y - delta_dist_y
                if perp_dist < 0.001:
                    perp_dist = 0.001
                perp_dist *= cos_correction
                if side == 0:
                    wall_x = player_y + perp_dist * sin_a / cos_correction
                else:
                    wall_x = player_x + perp_dist * cos_a / cos_correction
                wall_x -= floor(wall_x)
                results.append((perp_dist, side, wall_x, map_x, map_y, False))
                hit = True
                break

        if not hit:
            results.append((<double>max_depth, 0, 0.0, 0, 0, False))

    return results
