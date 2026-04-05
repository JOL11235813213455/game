import os
from dotenv import load_dotenv

load_dotenv()

SCREEN_WIDTH  = int(os.getenv("SCREEN_WIDTH", 1280))
SCREEN_HEIGHT = int(os.getenv("SCREEN_HEIGHT", 720))
FPS           = 300
DEBUG         = os.getenv("DEBUG", "false").lower() == "true"

BLOCK_SIZE    = 128
THREE_QUARTER = os.getenv("THREE_QUARTER", "true").lower() == "true"
TILE_HEIGHT   = int(BLOCK_SIZE * 0.75) if THREE_QUARTER else BLOCK_SIZE
MOVE_DELAY    = 150

COLOR_WALKABLE = (60, 90, 60)
COLOR_BLOCKED  = (40, 40, 40)
COLOR_NESTED   = (180, 140, 60)
COLOR_EXIT     = (75, 115, 195)
COLOR_PLAYER   = (100, 180, 255)
COLOR_GRID     = (50, 50, 50)

MENU_OPTIONS = ["Resume", "Save", "Load", "Quit"]
