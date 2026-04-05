import os
from dotenv import load_dotenv

load_dotenv()

SCREEN_WIDTH  = int(os.getenv("SCREEN_WIDTH", 1280))
SCREEN_HEIGHT = int(os.getenv("SCREEN_HEIGHT", 720))
FPS           = 300
DEBUG         = os.getenv("DEBUG", "false").lower() == "true"

BASE_BLOCK_SIZE = 32
THREE_QUARTER   = os.getenv("THREE_QUARTER", "true").lower() == "true"
MOVE_DELAY      = 150

# Zoom state — mutated at runtime by +/- keys
_zoom_level = 1.0
ZOOM_MIN    = 0.25
ZOOM_MAX    = 4.0
ZOOM_STEP   = 0.25

def get_zoom() -> float:
    return _zoom_level

def set_zoom(level: float):
    global _zoom_level
    _zoom_level = max(ZOOM_MIN, min(ZOOM_MAX, level))

def get_block_size() -> int:
    return int(BASE_BLOCK_SIZE * _zoom_level)

def get_tile_height() -> int:
    bs = get_block_size()
    return int(bs * 0.75) if THREE_QUARTER else bs

COLOR_WALKABLE = (60, 90, 60)
COLOR_BLOCKED  = (40, 40, 40)
COLOR_NESTED   = (180, 140, 60)
COLOR_EXIT     = (75, 115, 195)
COLOR_PLAYER   = (100, 180, 255)
COLOR_GRID     = (50, 50, 50)

MENU_OPTIONS = ["Resume", "Save", "Load", "Quit"]
