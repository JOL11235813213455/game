"""
Procedural species/monster sprite generator.

Generates pixel-art sprites at the sizes required by the species size
category:

  tiny       < 8 px   (6x6 typical)
  small      8 - 16   (12x12 typical)
  medium     16 - 24  (20x20 typical)
  large      24 - 32  (28x28 typical)
  huge       32 - 40  (36x36 typical)
  colossal   > 40     (44x44 typical)

For each species, produces sprites for:
  - idle (1 frame)
  - walk (2 frames per direction × 4 directions)
  - attack (1 frame per direction × 4 directions)
  - hurt (1 frame)
  - death (1 frame)

All sprites are auto-lassoed: the bounding box of non-transparent pixels
is trimmed so there's no blank border. Run from src/:

    python -m data.seed_sprites_species
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path


DB_PATH = Path(__file__).parent / 'game.db'

SIZE_TO_PIXELS = {
    'tiny': 6,
    'small': 12,
    'medium': 20,
    'large': 28,
    'huge': 36,
    'colossal': 44,
}


# -----------------------------------------------------------------------
# Pixel canvas helper
# -----------------------------------------------------------------------

class Canvas:
    """Character-grid sprite canvas. Origin top-left, '.' is transparent."""

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.grid = [['.'] * w for _ in range(h)]

    def px(self, x: int, y: int, ch: str):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.grid[y][x] = ch

    def hline(self, x0: int, x1: int, y: int, ch: str):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.px(x, y, ch)

    def vline(self, x: int, y0: int, y1: int, ch: str):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.px(x, y, ch)

    def rect(self, x0: int, y0: int, x1: int, y1: int, ch: str, fill: bool = True):
        if fill:
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    self.px(x, y, ch)
        else:
            for x in range(x0, x1 + 1):
                self.px(x, y0, ch)
                self.px(x, y1, ch)
            for y in range(y0, y1 + 1):
                self.px(x0, y, ch)
                self.px(x1, y, ch)

    def ellipse(self, cx: int, cy: int, rx: int, ry: int, ch: str):
        for y in range(max(0, cy - ry), min(self.h, cy + ry + 1)):
            for x in range(max(0, cx - rx), min(self.w, cx + rx + 1)):
                dx = (x - cx) / max(1, rx)
                dy = (y - cy) / max(1, ry)
                if dx * dx + dy * dy <= 1.0:
                    self.px(x, y, ch)

    def flip_h(self):
        """Return a horizontally-flipped copy."""
        c = Canvas(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                c.grid[y][self.w - 1 - x] = self.grid[y][x]
        return c

    def lassoed(self) -> tuple[list[str], int, int]:
        """Trim blank borders. Returns (pixel_rows, width, height)."""
        # Find bounding box of non-transparent cells
        min_x, min_y = self.w, self.h
        max_x, max_y = -1, -1
        for y in range(self.h):
            for x in range(self.w):
                if self.grid[y][x] != '.':
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)
        if max_x < 0:
            # Empty canvas
            return ['.'], 1, 1
        rows = []
        for y in range(min_y, max_y + 1):
            row = ''.join(self.grid[y][min_x:max_x + 1])
            rows.append(row)
        return rows, max_x - min_x + 1, max_y - min_y + 1


# -----------------------------------------------------------------------
# Palettes
# -----------------------------------------------------------------------

def mix(a: tuple, b: tuple, t: float) -> list:
    return [int(a[i] + (b[i] - a[i]) * t) for i in range(3)]


PALETTES = {
    # name: {char: RGB triple}
    'human_male': {
        'S': [230, 200, 170],  # skin
        's': [190, 160, 135],  # skin shadow
        'H': [90, 60, 40],     # hair
        'C': [60, 90, 150],    # clothing
        'c': [45, 70, 115],    # clothing shadow
        'B': [80, 50, 30],     # belt
        'P': [50, 50, 50],     # pants
        'E': [30, 30, 30],     # eyes
        'O': [200, 180, 50],   # buckle/accent
    },
    'human_female': {
        'S': [235, 210, 185],
        's': [200, 170, 145],
        'H': [120, 60, 30],
        'C': [140, 80, 140],   # dress
        'c': [110, 60, 110],
        'B': [80, 50, 30],
        'P': [100, 60, 100],
        'E': [30, 30, 30],
        'O': [220, 180, 60],
    },
    'orc_male': {
        'G': [100, 160, 80],   # green skin
        'g': [70, 120, 55],    # shadow
        'T': [160, 140, 120],  # tusks
        'H': [40, 30, 20],     # dark hair
        'A': [80, 60, 40],     # armor/leather
        'a': [55, 40, 25],
        'E': [200, 40, 40],    # red eyes
    },
    'bug': {
        'K': [40, 30, 30],     # chitin
        'k': [70, 50, 40],     # chitin shadow
        'E': [180, 40, 40],
    },
    'wolf': {
        'G': [130, 130, 140],  # grey fur
        'g': [90, 90, 100],    # shadow
        'W': [220, 215, 210],  # belly
        'E': [210, 200, 60],   # yellow eyes
        'N': [30, 25, 30],     # nose/mouth
        'R': [200, 60, 60],    # blood / attack flash
    },
    'bear': {
        'B': [90, 55, 30],     # brown fur
        'b': [60, 35, 20],     # shadow
        'T': [150, 110, 80],   # tan belly
        'N': [20, 15, 10],     # nose
        'E': [120, 80, 40],    # eye
        'C': [230, 230, 220],  # claw
    },
    'rat': {
        'R': [100, 90, 80],    # dirty grey-brown
        'r': [70, 60, 50],
        'P': [180, 140, 130],  # pink
        'E': [200, 40, 40],    # red eye
        'T': [60, 50, 45],     # tail
    },
    'lizard': {
        'G': [80, 140, 60],    # scale green
        'g': [50, 100, 40],
        'Y': [200, 180, 60],   # underbelly yellow
        'E': [255, 210, 100],  # slit eye
        'A': [140, 220, 110],  # acid spittle
    },
    'bee': {
        'Y': [240, 200, 50],   # yellow
        'K': [30, 20, 10],     # black stripe
        'W': [200, 210, 230],  # translucent wing
        'E': [40, 30, 30],     # eye
    },
    'orc_monster': {
        'G': [90, 130, 70],
        'g': [60, 90, 50],
        'T': [200, 190, 170],  # tusks
        'R': [150, 40, 40],    # war paint
        'A': [90, 60, 40],     # armor
        'a': [60, 40, 25],
        'E': [220, 180, 40],   # eye
        'W': [90, 90, 90],     # club
    },
    'crawler': {
        'P': [60, 40, 80],     # dark purple
        'p': [40, 25, 60],
        'E': [230, 80, 230],   # magenta eye cluster
        'C': [220, 210, 200],  # claw
    },
    'boar': {
        'B': [100, 70, 55],    # boar brown
        'b': [70, 50, 35],
        'T': [230, 220, 200],  # tusk
        'N': [40, 30, 25],
        'E': [40, 30, 20],
    },
    'ant': {
        'A': [130, 60, 40],    # red-brown
        'a': [90, 40, 25],
        'E': [30, 20, 10],
        'J': [200, 200, 200],  # mandible
    },
    'egg': {
        'E': [240, 220, 180],  # shell
        'e': [200, 180, 140],  # shadow
        'S': [200, 120, 60],   # spots
    },
}


# -----------------------------------------------------------------------
# Sprite builders per species
# -----------------------------------------------------------------------

def _centered(c: Canvas) -> Canvas:
    """Return c (passes through — used as readability hint)."""
    return c


def human_sprite(direction: str, frame: int = 0, action: str = 'idle',
                 female: bool = False) -> Canvas:
    """20x20 human. direction: 's'/'n'/'e'/'w'. action: idle/walk/attack/hurt/death."""
    c = Canvas(20, 20)
    skin = 's' if action == 'hurt' else 'S'
    # Head (centered-top)
    c.ellipse(10, 4, 3, 3, skin)
    # Hair
    c.hline(7, 13, 1, 'H')
    c.hline(7, 13, 2, 'H')
    if direction == 's':
        c.px(8, 4, 'E')
        c.px(11, 4, 'E')
    elif direction == 'n':
        # Back of head — no eyes, more hair
        c.hline(7, 13, 3, 'H')
    elif direction == 'e':
        c.px(11, 4, 'E')
    elif direction == 'w':
        c.px(8, 4, 'E')
    # Torso
    c.rect(7, 8, 12, 13, 'C')
    c.hline(7, 12, 13, 'c')
    # Belt
    c.hline(7, 12, 14, 'B')
    c.px(9, 14, 'O')
    # Legs (walk frame toggles)
    leg_offset = 1 if (action == 'walk' and frame == 1) else 0
    if action == 'death':
        # Body prone
        c2 = Canvas(20, 20)
        c2.rect(4, 12, 15, 14, 'C')
        c2.rect(5, 14, 15, 15, 'P')
        c2.ellipse(3, 13, 2, 2, skin)
        return c2
    c.rect(7, 15, 9, 19 - leg_offset, 'P')
    c.rect(10, 15, 12, 19 - (1 - leg_offset if action == 'walk' else 0), 'P')
    # Arms / attack
    if action == 'attack':
        if direction == 'e':
            c.hline(13, 16, 10, skin)
            c.px(17, 10, 'E')  # weapon extension
        elif direction == 'w':
            c.hline(3, 6, 10, skin)
            c.px(2, 10, 'E')
        elif direction == 'n':
            c.vline(10, 4, 7, skin)
        else:  # s
            c.vline(10, 13, 16, skin)
    else:
        # Arms at sides
        c.vline(6, 9, 12, skin)
        c.vline(13, 9, 12, skin)
    return c


def orc_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    c = Canvas(20, 20)
    skin = 'g' if action == 'hurt' else 'G'
    # Bigger head, tusks
    c.ellipse(10, 5, 4, 4, skin)
    c.hline(7, 13, 1, 'H')
    c.hline(7, 13, 2, 'H')
    if direction in ('s', 'e', 'w'):
        c.px(11 if direction != 'w' else 8, 5, 'E')
        c.px(10, 8, 'T')  # tusk
        c.px(12, 8, 'T')
    # Torso with armor
    c.rect(6, 9, 13, 14, 'A')
    c.hline(6, 13, 14, 'a')
    # Legs
    leg_offset = 1 if (action == 'walk' and frame == 1) else 0
    if action == 'death':
        c2 = Canvas(20, 20)
        c2.rect(4, 13, 15, 15, 'A')
        c2.ellipse(3, 14, 2, 2, skin)
        return c2
    c.rect(6, 15, 9, 19 - leg_offset, 'a')
    c.rect(10, 15, 13, 19 - (1 - leg_offset if action == 'walk' else 0), 'a')
    # Arms
    if action == 'attack':
        if direction == 'e':
            c.hline(14, 18, 11, skin)
        elif direction == 'w':
            c.hline(1, 5, 11, skin)
        elif direction == 'n':
            c.vline(10, 5, 8, skin)
        else:
            c.vline(10, 14, 17, skin)
    else:
        c.vline(5, 10, 13, skin)
        c.vline(14, 10, 13, skin)
    return c


def bug_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    c = Canvas(6, 6)
    body = 'k' if action == 'hurt' else 'K'
    c.ellipse(3, 3, 2, 2, body)
    c.px(2, 2, 'E')
    c.px(3, 2, 'E')
    if action == 'death':
        c2 = Canvas(6, 6)
        c2.hline(1, 4, 4, body)
        return c2
    return c


def wolf_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """20x20 wolf — quadruped, medium size."""
    c = Canvas(20, 20)
    body = 'g' if action == 'hurt' else 'G'
    # Body ellipse (horizontal) — larger to fit medium (16-24) range
    c.ellipse(10, 11, 8, 4, body)
    c.ellipse(10, 12, 6, 3, 'W')  # white belly
    if direction in ('e', 's'):
        # Head on right (east) or front-facing bottom (south)
        if direction == 'e':
            c.ellipse(16, 10, 2, 2, body)
            # Ears
            c.px(15, 7, body); c.px(16, 7, body)
            c.px(17, 7, body); c.px(18, 7, body)
            # Eye + snout
            c.px(17, 10, 'E')
            c.px(18, 11, 'N')
        else:  # south — face towards viewer
            c.ellipse(10, 7, 3, 2, body)
            c.px(8, 5, body); c.px(9, 5, body)  # L ear
            c.px(11, 5, body); c.px(12, 5, body)  # R ear
            c.px(9, 7, 'E'); c.px(11, 7, 'E')
            c.px(10, 8, 'N')
    elif direction == 'w':
        c.ellipse(4, 10, 2, 2, body)
        c.px(3, 7, body); c.px(4, 7, body)
        c.px(1, 7, body); c.px(2, 7, body)
        c.px(3, 10, 'E')
        c.px(1, 11, 'N')
    elif direction == 'n':
        # Back — tail up
        c.ellipse(10, 7, 3, 2, body)
        c.vline(10, 2, 5, body)  # tail
    # Legs (walk toggles)
    if action == 'death':
        c2 = Canvas(20, 20)
        c2.ellipse(10, 14, 7, 2, body)
        c2.hline(3, 5, 12, body)
        c2.hline(15, 17, 12, body)
        return c2
    if action == 'walk' and frame == 1:
        c.vline(5, 14, 16, body)
        c.vline(15, 14, 16, body)
        c.vline(8, 14, 17, body)
        c.vline(12, 14, 17, body)
    else:
        c.vline(5, 14, 17, body)
        c.vline(15, 14, 17, body)
        c.vline(8, 14, 16, body)
        c.vline(12, 14, 16, body)
    if action == 'attack':
        # Open mouth, bared fangs
        if direction == 'e':
            c.px(18, 10, 'R')
            c.px(19, 10, 'W')
        elif direction == 'w':
            c.px(1, 10, 'R')
            c.px(0, 10, 'W')
        elif direction == 's':
            c.px(10, 9, 'R')
    # Tail
    if direction != 'n':
        if direction == 'e':
            c.hline(3, 5, 11, body)
        elif direction == 'w':
            c.hline(14, 17, 11, body)
        else:
            c.vline(10, 14, 17, body) if False else None
    return c


def bear_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """36x36 bear — huge quadruped (needs 32-40px)."""
    c = Canvas(36, 36)
    body = 'b' if action == 'hurt' else 'B'
    # Large body — explicitly span 32+ pixels
    c.ellipse(18, 20, 16, 9, body)
    c.ellipse(18, 22, 13, 5, 'T')
    # Head (larger to push total silhouette past 32 px)
    if direction == 'e':
        c.ellipse(30, 18, 5, 5, body)
        c.px(27, 13, body); c.px(28, 13, body)
        c.px(32, 13, body); c.px(33, 13, body)
        c.px(32, 18, 'E')
        c.px(34, 20, 'N')
    elif direction == 'w':
        c.ellipse(6, 18, 5, 5, body)
        c.px(2, 13, body); c.px(3, 13, body)
        c.px(8, 13, body); c.px(9, 13, body)
        c.px(4, 18, 'E')
        c.px(2, 20, 'N')
    elif direction == 's':
        c.ellipse(18, 10, 7, 5, body)
        c.px(11, 5, body); c.px(12, 5, body)
        c.px(24, 5, body); c.px(25, 5, body)
        c.px(15, 10, 'E'); c.px(21, 10, 'E')
        c.px(18, 14, 'N')
    else:  # n
        c.ellipse(18, 10, 7, 4, body)
    # Legs
    leg_offset = 2 if (action == 'walk' and frame == 1) else 0
    if action == 'death':
        c2 = Canvas(36, 36)
        c2.ellipse(18, 26, 14, 3, body)
        c2.hline(4, 8, 22, body)
        c2.hline(28, 32, 22, body)
        return c2
    c.rect(7, 27, 10, 33 - leg_offset, body)
    c.rect(26, 27, 29, 33 - (2 - leg_offset if action == 'walk' else 0), body)
    c.rect(13, 27, 16, 33, body)
    c.rect(20, 27, 23, 33, body)
    # Claws on attack
    if action == 'attack':
        if direction == 'e':
            c.hline(33, 35, 18, 'C')
        elif direction == 'w':
            c.hline(0, 2, 18, 'C')
        elif direction == 's':
            c.hline(16, 20, 16, 'C')
    return c


def rat_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """12x12 giant rat."""
    c = Canvas(12, 12)
    body = 'r' if action == 'hurt' else 'R'
    c.ellipse(6, 6, 4, 2, body)
    c.ellipse(6, 7, 3, 1, 'P')
    # Head side-facing
    if direction == 'e':
        c.ellipse(10, 5, 1, 1, body)
        c.px(9, 3, body); c.px(10, 3, body)  # ear
        c.px(11, 5, 'E')
    elif direction == 'w':
        c.ellipse(1, 5, 1, 1, body)
        c.px(1, 3, body); c.px(2, 3, body)
        c.px(0, 5, 'E')
    elif direction == 's':
        c.ellipse(6, 3, 2, 1, body)
        c.px(5, 4, 'E'); c.px(7, 4, 'E')
    else:  # n
        c.ellipse(6, 3, 2, 1, body)
    # Tail
    if direction == 'e':
        c.hline(0, 3, 7, 'T')
    elif direction == 'w':
        c.hline(8, 11, 7, 'T')
    else:
        c.vline(6, 9, 11, 'T')
    # Legs
    if action == 'death':
        c2 = Canvas(12, 12)
        c2.ellipse(6, 8, 5, 1, body)
        return c2
    leg_off = 1 if (action == 'walk' and frame == 1) else 0
    c.vline(3, 8, 10 - leg_off, 'P')
    c.vline(9, 8, 10 - (1 - leg_off if action == 'walk' else 0), 'P')
    if action == 'attack' and direction == 'e':
        c.px(11, 4, 'E')
    return c


def lizard_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """12x12 spitter lizard."""
    c = Canvas(12, 12)
    body = 'g' if action == 'hurt' else 'G'
    # Elongated body
    c.ellipse(6, 6, 4, 2, body)
    c.ellipse(6, 7, 3, 1, 'Y')
    # Head
    if direction == 'e':
        c.ellipse(10, 5, 1, 1, body)
        c.px(11, 5, 'E')
    elif direction == 'w':
        c.ellipse(1, 5, 1, 1, body)
        c.px(0, 5, 'E')
    elif direction == 's':
        c.ellipse(6, 3, 2, 1, body)
        c.px(5, 4, 'E'); c.px(7, 4, 'E')
    # Tail (long)
    if direction == 'e':
        c.hline(0, 2, 6, body)
    elif direction == 'w':
        c.hline(9, 11, 6, body)
    else:
        c.vline(6, 9, 11, body)
    # 4 legs
    if action == 'death':
        c2 = Canvas(12, 12)
        c2.ellipse(6, 8, 5, 1, body)
        return c2
    c.vline(2, 8, 9, body)
    c.vline(4, 8, 9, body)
    c.vline(7, 8, 9, body)
    c.vline(10, 8, 9, body)
    # Acid spit on attack
    if action == 'attack':
        if direction == 'e':
            c.hline(11, 11, 5, 'A')
        elif direction == 'w':
            c.hline(0, 0, 5, 'A')
    return c


def bee_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """6x6 bee (tiny)."""
    c = Canvas(6, 6)
    body = 'Y'
    c.ellipse(3, 3, 2, 2, body)
    c.hline(1, 4, 3, 'K')  # stripe
    # Wings
    if action == 'attack':
        c.px(0, 1, 'W'); c.px(1, 1, 'W')
        c.px(4, 1, 'W'); c.px(5, 1, 'W')
    # Eyes
    c.px(2, 2, 'E')
    c.px(4, 2, 'E')
    if action == 'death':
        c2 = Canvas(6, 6)
        c2.hline(1, 4, 4, 'K')
        return c2
    return c


def orc_monster_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """28x28 dire orc — large humanoid."""
    c = Canvas(28, 28)
    skin = 'g' if action == 'hurt' else 'G'
    # Head (bigger)
    c.ellipse(14, 7, 5, 5, skin)
    c.hline(9, 19, 2, 'R')  # war paint
    if direction in ('s', 'e', 'w'):
        c.px(12 if direction != 'w' else 15, 7, 'E')
        c.px(13, 11, 'T'); c.px(15, 11, 'T')  # tusks
    # Armored torso
    c.rect(9, 13, 19, 19, 'A')
    c.hline(9, 19, 20, 'a')
    # Legs
    if action == 'death':
        c2 = Canvas(28, 28)
        c2.rect(5, 19, 22, 23, 'A')
        c2.ellipse(4, 20, 3, 3, skin)
        return c2
    leg_off = 2 if (action == 'walk' and frame == 1) else 0
    c.rect(9, 21, 13, 26 - leg_off, 'a')
    c.rect(14, 21, 18, 26 - (2 - leg_off if action == 'walk' else 0), 'a')
    # Club
    if action == 'attack':
        if direction == 'e':
            c.rect(20, 11, 26, 13, 'W')
        elif direction == 'w':
            c.rect(1, 11, 7, 13, 'W')
        elif direction == 'n':
            c.vline(14, 3, 10, 'W')
        else:
            c.vline(14, 17, 24, 'W')
    else:
        # Club at side
        c.vline(5, 14, 20, 'W')
    # Arms
    c.vline(8, 14, 19, skin)
    c.vline(20, 14, 19, skin)
    return c


def crawler_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """20x20 deep crawler — spider-like."""
    c = Canvas(20, 20)
    body = 'p' if action == 'hurt' else 'P'
    c.ellipse(10, 10, 4, 4, body)
    # Eye cluster
    if direction == 's':
        c.px(8, 9, 'E'); c.px(10, 9, 'E'); c.px(12, 9, 'E')
        c.px(9, 11, 'E'); c.px(11, 11, 'E')
    elif direction == 'e':
        c.px(12, 8, 'E'); c.px(13, 9, 'E'); c.px(13, 11, 'E')
    elif direction == 'w':
        c.px(7, 8, 'E'); c.px(6, 9, 'E'); c.px(6, 11, 'E')
    # 6 legs
    if action == 'death':
        c2 = Canvas(20, 20)
        c2.ellipse(10, 14, 6, 2, body)
        return c2
    leg_off = 1 if (action == 'walk' and frame == 1) else 0
    for (sx, sy, ex, ey) in [
        (4, 10, 1, 6 + leg_off),
        (4, 11, 1, 14 - leg_off),
        (4, 12, 1, 17 - leg_off),
        (16, 10, 19, 6 + leg_off),
        (16, 11, 19, 14 - leg_off),
        (16, 12, 19, 17 - leg_off),
    ]:
        c.px(sx, sy, body)
        c.px(ex, ey, body)
        c.px((sx + ex) // 2, (sy + ey) // 2, body)
    # Claws on attack
    if action == 'attack':
        if direction == 's':
            c.px(8, 15, 'C'); c.px(12, 15, 'C')
    return c


def boar_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """20x20 wild boar (medium, 16-24px)."""
    c = Canvas(20, 20)
    body = 'b' if action == 'hurt' else 'B'
    c.ellipse(10, 11, 8, 4, body)
    # Head + tusks
    if direction == 'e':
        c.ellipse(16, 10, 2, 2, body)
        c.px(18, 11, 'T'); c.px(17, 12, 'T')
        c.px(17, 10, 'E')
    elif direction == 'w':
        c.ellipse(4, 10, 2, 2, body)
        c.px(2, 11, 'T'); c.px(3, 12, 'T')
        c.px(3, 10, 'E')
    elif direction == 's':
        c.ellipse(10, 7, 3, 2, body)
        c.px(8, 9, 'T'); c.px(12, 9, 'T')
        c.px(9, 7, 'E'); c.px(11, 7, 'E')
    # Legs
    if action == 'death':
        c2 = Canvas(20, 20)
        c2.ellipse(10, 14, 7, 2, body)
        return c2
    leg_off = 1 if (action == 'walk' and frame == 1) else 0
    c.vline(5, 14, 17 - leg_off, body)
    c.vline(15, 14, 17 - leg_off, body)
    c.vline(8, 14, 16, body)
    c.vline(12, 14, 16, body)
    # Tail wisp
    if direction == 'e':
        c.px(3, 11, body)
    elif direction == 'w':
        c.px(16, 11, body)
    return c


def ant_sprite(direction: str, frame: int = 0, action: str = 'idle') -> Canvas:
    """6x6 army ant."""
    c = Canvas(6, 6)
    body = 'a' if action == 'hurt' else 'A'
    # 3-segment body
    c.px(1, 3, body); c.px(2, 3, body); c.px(3, 3, body); c.px(4, 3, body)
    c.px(1, 2, body); c.px(4, 2, body)
    c.px(0, 3, body); c.px(5, 3, body)
    # Head + mandibles
    if direction == 'e':
        c.px(5, 2, 'J')
        c.px(5, 4, 'J')
    elif direction == 'w':
        c.px(0, 2, 'J')
        c.px(0, 4, 'J')
    # Eyes
    c.px(2, 2, 'E')
    c.px(3, 2, 'E')
    # Legs
    if action == 'death':
        c2 = Canvas(6, 6)
        c2.hline(1, 4, 4, body)
        return c2
    c.px(1, 4, body); c.px(4, 4, body)
    c.px(2, 5, body); c.px(3, 5, body)
    return c


def egg_sprite(species_color_ch: str = 'S') -> Canvas:
    """Single egg sprite, ~6x8."""
    c = Canvas(6, 8)
    for y in range(1, 7):
        c.hline(1, 4, y, 'E')
    c.px(2, 2, species_color_ch)
    c.px(3, 4, species_color_ch)
    c.hline(0, 5, 7, 'e')
    return c


# -----------------------------------------------------------------------
# Registry: species → (builder, palette, size)
# -----------------------------------------------------------------------

SPECIES_BUILDERS = {
    'c_human_m':  (human_sprite, 'human_male',   'medium'),
    'c_human_f':  (lambda d, f, a: human_sprite(d, f, a, female=True),
                                    'human_female', 'medium'),
    'c_orc_m':    (orc_sprite,    'orc_male',     'medium'),
    'c_bug':      (bug_sprite,    'bug',          'tiny'),
    'c_grey_wolf':     (wolf_sprite,   'wolf',          'medium'),
    'c_cave_bear':     (bear_sprite,   'bear',          'huge'),
    'c_giant_rat':     (rat_sprite,    'rat',           'small'),
    'c_spitter_lizard':(lizard_sprite, 'lizard',        'small'),
    'c_honey_bees':    (bee_sprite,    'bee',           'tiny'),
    'c_dire_orc':      (orc_monster_sprite, 'orc_monster', 'large'),
    'c_deep_crawler':  (crawler_sprite, 'crawler',      'medium'),
    'c_wild_boar':     (boar_sprite,   'boar',          'medium'),
    'c_army_ants':     (ant_sprite,    'ant',           'tiny'),
}


# -----------------------------------------------------------------------
# DB insertion
# -----------------------------------------------------------------------

def insert_sprite(con, name: str, palette: dict, pixel_rows: list[str],
                  width: int, height: int, action_point=None):
    con.execute(
        'INSERT OR REPLACE INTO sprites (name, palette, pixels, width, height, '
        'action_point_x, action_point_y) VALUES (?,?,?,?,?,?,?)',
        (name, json.dumps(palette), json.dumps(pixel_rows),
         width, height,
         action_point[0] if action_point else None,
         action_point[1] if action_point else None)
    )


def generate_species_frames(base_name: str, builder, palette_name: str, size: str):
    """Generate all animation frames for a species. Returns list of
    (sprite_name, rows, w, h, action_point)."""
    palette = PALETTES[palette_name]
    out = []

    # Static idle + directional idles
    for direction in ('s', 'n', 'e', 'w'):
        c = builder(direction, 0, 'idle')
        rows, w, h = c.lassoed()
        ap = (w // 2, h - 1)
        out.append((f'{base_name}_idle_{direction}', palette, rows, w, h, ap))

    # Default alias: base_name → south idle
    south_idle = builder('s', 0, 'idle')
    rows, w, h = south_idle.lassoed()
    out.append((base_name, palette, rows, w, h, (w // 2, h - 1)))

    # Walk (2 frames per direction)
    for direction in ('s', 'n', 'e', 'w'):
        for frame in (0, 1):
            c = builder(direction, frame, 'walk')
            rows, w, h = c.lassoed()
            ap = (w // 2, h - 1)
            out.append((f'{base_name}_walk_{direction}_{frame}',
                        palette, rows, w, h, ap))

    # Attack (1 frame per direction)
    for direction in ('s', 'n', 'e', 'w'):
        c = builder(direction, 0, 'attack')
        rows, w, h = c.lassoed()
        ap = (w // 2, h - 1)
        out.append((f'{base_name}_attack_{direction}',
                    palette, rows, w, h, ap))

    # Hurt (1 frame, south)
    c = builder('s', 0, 'hurt')
    rows, w, h = c.lassoed()
    out.append((f'{base_name}_hurt', palette, rows, w, h, (w // 2, h - 1)))

    # Death (1 frame)
    c = builder('s', 0, 'death')
    rows, w, h = c.lassoed()
    out.append((f'{base_name}_death', palette, rows, w, h, (w // 2, h - 1)))

    return out


def insert_animations(con, base_name: str):
    """Build ANIMATIONS + ANIMATION_FRAMES rows for this species' anim set."""
    # Animation schema: one row per animation name, with frames referencing sprites
    # Animation names + frame list
    anim_specs = [
        (f'{base_name}_idle', [(f'{base_name}_idle_s', 200)]),
        (f'{base_name}_walk_s', [(f'{base_name}_walk_s_0', 150),
                                  (f'{base_name}_walk_s_1', 150)]),
        (f'{base_name}_walk_n', [(f'{base_name}_walk_n_0', 150),
                                  (f'{base_name}_walk_n_1', 150)]),
        (f'{base_name}_walk_e', [(f'{base_name}_walk_e_0', 150),
                                  (f'{base_name}_walk_e_1', 150)]),
        (f'{base_name}_walk_w', [(f'{base_name}_walk_w_0', 150),
                                  (f'{base_name}_walk_w_1', 150)]),
        (f'{base_name}_attack_s', [(f'{base_name}_attack_s', 200)]),
        (f'{base_name}_attack_n', [(f'{base_name}_attack_n', 200)]),
        (f'{base_name}_attack_e', [(f'{base_name}_attack_e', 200)]),
        (f'{base_name}_attack_w', [(f'{base_name}_attack_w', 200)]),
        (f'{base_name}_hurt', [(f'{base_name}_hurt', 250)]),
        (f'{base_name}_death', [(f'{base_name}_death', 500)]),
    ]

    for anim_name, frames in anim_specs:
        con.execute(
            'INSERT OR REPLACE INTO animations (name, target_type) VALUES (?,?)',
            (anim_name, 'creature')
        )
        con.execute('DELETE FROM animation_frames WHERE animation_name=?',
                    (anim_name,))
        for order, (sprite_name, duration) in enumerate(frames):
            con.execute(
                'INSERT INTO animation_frames '
                '(animation_name, frame_index, sprite_name, duration_ms) '
                'VALUES (?,?,?,?)',
                (anim_name, order, sprite_name, duration)
            )


def insert_anim_bindings(con, base_name: str):
    """Bind species anim names to behaviors."""
    bindings = [
        ('idle', f'{base_name}_idle'),
        ('walk_south', f'{base_name}_walk_s'),
        ('walk_north', f'{base_name}_walk_n'),
        ('walk_east',  f'{base_name}_walk_e'),
        ('walk_west',  f'{base_name}_walk_w'),
        ('attack_south', f'{base_name}_attack_s'),
        ('attack_north', f'{base_name}_attack_n'),
        ('attack_east',  f'{base_name}_attack_e'),
        ('attack_west',  f'{base_name}_attack_w'),
        ('hurt', f'{base_name}_hurt'),
        ('death', f'{base_name}_death'),
    ]
    for behavior, anim_name in bindings:
        con.execute(
            'INSERT OR REPLACE INTO animation_bindings '
            '(target_name, behavior, animation_name) VALUES (?,?,?)',
            (base_name, behavior, anim_name)
        )


def main():
    con = sqlite3.connect(DB_PATH)

    for base_name, (builder, palette_name, size) in SPECIES_BUILDERS.items():
        print(f'Generating {base_name} ({size})...')
        frames = generate_species_frames(base_name, builder, palette_name, size)
        for sprite_name, palette, rows, w, h, ap in frames:
            insert_sprite(con, sprite_name, palette, rows, w, h, ap)
        insert_animations(con, base_name)
        insert_anim_bindings(con, base_name)

    # Generic egg sprite (shared across species for now)
    egg = egg_sprite()
    rows, w, h = egg.lassoed()
    insert_sprite(con, 'c_egg', PALETTES['egg'], rows, w, h, (w // 2, h - 1))

    # Wire up species sprite_name + monster_species sprite_name
    # Map creature species
    creature_map = {
        'human': 'c_human_m',
        'orc': 'c_orc_m',
        'bug': 'c_bug',
    }
    for sp, sprite in creature_map.items():
        con.execute('UPDATE species SET sprite_name=? WHERE name=?',
                    (sprite, sp))

    # Map monster species to their new sprite names
    monster_map = {
        'grey_wolf':      'c_grey_wolf',
        'giant_rat':      'c_giant_rat',
        'cave_bear':      'c_cave_bear',
        'spitter_lizard': 'c_spitter_lizard',
        'honey_bees':     'c_honey_bees',
        'dire_orc':       'c_dire_orc',
        'deep_crawler':   'c_deep_crawler',
        'wild_boar':      'c_wild_boar',
        'army_ants':      'c_army_ants',
    }
    for sp, sprite in monster_map.items():
        con.execute('UPDATE monster_species SET sprite_name=? WHERE name=?',
                    (sprite, sp))

    con.commit()
    con.close()
    print(f'Done. Generated sprites + animations for '
          f'{len(SPECIES_BUILDERS)} species.')


if __name__ == '__main__':
    main()
