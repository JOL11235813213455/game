import pygame

# Sprites are 8x8 character grids.
# '.' = transparent. Each character maps to a color in the palette.
# At BLOCK_SIZE=40, each pixel renders as a 5x5 square (40 // 8 = 5).

PLAYER_PALETTE = {
    'H': (70,  50,  30),   # hair
    'S': (190, 150, 110),  # skin
    'C': (90,  110, 80),   # worn olive clothing
    'D': (55,  70,  50),   # dark clothing detail
    'B': (35,  25,  15),   # boots / belt
}

PLAYER_PIXELS = [
    "..HHHH..",
    ".HSSSSH.",
    "..SSSS..",
    "..CCCC..",
    ".DCCCCD.",
    "..CCCC..",
    ".BB..BB.",
    ".BB..BB.",
]

NPC_PALETTE = {
    'H': (30,  20,  10),   # dark hair
    'S': (190, 130, 100),  # skin
    'R': (140, 40,  40),   # dark red clothing
    'D': (80,  20,  20),   # darker red detail
    'B': (25,  15,  15),   # dark boots
}

NPC_PIXELS = [
    ".HHHHHH.",
    ".SSSSSS.",
    ".SSSSSS.",
    ".RRRRRR.",
    "RRRRRRRR",
    ".RR..RR.",
    ".DD..DD.",
    ".BB..BB.",
]


def make_surface(pixels: list[str], palette: dict, block_size: int) -> pygame.Surface:
    cols = len(pixels[0])
    rows = len(pixels)
    pixel_w = block_size // cols
    pixel_h = block_size // rows
    surface = pygame.Surface((block_size, block_size), pygame.SRCALPHA)
    for row_idx, row in enumerate(pixels):
        for col_idx, char in enumerate(row):
            if char == '.' or char not in palette:
                continue
            rect = pygame.Rect(
                col_idx * pixel_w
                ,row_idx * pixel_h
                ,pixel_w
                ,pixel_h
            )
            pygame.draw.rect(surface, palette[char], rect)
    return surface
