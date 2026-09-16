"""
Fade and cut transitions between two pygame Surfaces.
"""
from __future__ import annotations

import time


def fade(
    screen,
    surface_from,
    surface_to,
    duration_ms: int = 1000,
    fps: int = 30,
) -> None:
    """
    Cross-fade from surface_from to surface_to over duration_ms milliseconds.
    Blocks the caller for the duration.
    """
    import pygame

    steps = max(1, duration_ms * fps // 1000)
    delay = duration_ms / 1000 / steps

    for i in range(steps + 1):
        alpha = int(255 * i / steps)
        screen.blit(surface_from, (0, 0))
        surface_to.set_alpha(alpha)
        screen.blit(surface_to, (0, 0))
        pygame.display.flip()
        time.sleep(delay)

    surface_to.set_alpha(255)


def cut(screen, surface_to) -> None:
    """Instant switch to surface_to."""
    import pygame
    screen.blit(surface_to, (0, 0))
    pygame.display.flip()
