import os
import sys

import pygame
from dotenv import load_dotenv

load_dotenv()

SCREEN_WIDTH = int(os.getenv("SCREEN_WIDTH", 1280))
SCREEN_HEIGHT = int(os.getenv("SCREEN_HEIGHT", 720))
FPS = 300  # int(os.getenv("FPS", 60))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

BLOCK_SIZE = 40
MOVE_DELAY = 150  # ms between grid steps when key is held


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Game")
    clock = pygame.time.Clock()

    # Snap starting position to grid
    block = pygame.Rect(
        (SCREEN_WIDTH // 2 // BLOCK_SIZE) * BLOCK_SIZE,
        (SCREEN_HEIGHT // 2 // BLOCK_SIZE) * BLOCK_SIZE,
        BLOCK_SIZE,
        BLOCK_SIZE,
    )

    last_move = 0

    running = True
    while running:
        now = pygame.time.get_ticks()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        if now - last_move >= MOVE_DELAY:
            keys = pygame.key.get_pressed()
            dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
            dy = keys[pygame.K_DOWN] - keys[pygame.K_UP]
            if dx != 0 or dy != 0:
                block.x += dx * BLOCK_SIZE
                block.y += dy * BLOCK_SIZE
                block.clamp_ip(screen.get_rect())
                last_move = now

        screen.fill((30, 30, 30))
        pygame.draw.rect(screen, (100, 180, 255), block)

        if DEBUG:
            font = pygame.font.SysFont(None, 36)
            fps_text = font.render(f"FPS: {clock.get_fps():.0f}", True, (0, 255, 0))
            screen.blit(fps_text, (10, 10))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
