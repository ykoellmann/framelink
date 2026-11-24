"""
Semi-transparent metadata overlay rendered onto a pygame Surface.

Fields (each toggleable in config):
  album_name | owner | date | location (reverse-geocoded from EXIF GPS)
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .. import config as _cfg_mod
from ..sync.cache import load_metadata
from ..sync.icloud import PhotoMeta
from .geocoder import reverse_geocode

log = logging.getLogger(__name__)

# Loaded lazily — only import pygame when the display service actually runs
_pygame = None


def _pg():
    global _pygame
    if _pygame is None:
        import pygame
        _pygame = pygame
    return _pygame


# Font size relative to screen height
_FONT_SIZE_RATIO = 0.030
_PAD_X = 28   # horizontal padding inside the pill
_PAD_Y = 12   # vertical padding inside the pill
_MARGIN_BOTTOM_RATIO = 0.045  # distance from screen bottom


_MONTHS_DE = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def _format_date(dt: datetime | None) -> str:
    if not dt:
        return ""
    return f"{dt.day}. {_MONTHS_DE[dt.month]} {dt.year}"


def _get_location(photo: PhotoMeta) -> str:
    if photo.lat is not None and photo.lon is not None:
        return reverse_geocode(photo.lat, photo.lon) or ""
    return ""


def _build_text(photo: PhotoMeta) -> str:
    """Build overlay text string from enabled fields."""
    fields_cfg = _cfg_mod.config.overlay.fields
    parts: list[str] = []

    if fields_cfg.album_name and photo.album_name:
        parts.append(photo.album_name)
    if fields_cfg.owner and (photo.owner_first or photo.owner_last):
        parts.append(photo.display_owner)
    if fields_cfg.date and photo.captured_at:
        parts.append(_format_date(photo.captured_at))
    if fields_cfg.location:
        loc = _get_location(photo)
        if loc:
            parts.append(loc)

    return "  ·  ".join(parts)


def draw_overlay(
    surface,
    primary_guid: str,
    screen_w: int,
    screen_h: int,
    all_metadata: dict[str, PhotoMeta] | None = None,
    area_w: int | None = None,
) -> None:
    """Draw the metadata overlay onto *surface* in-place, centred in the first *area_w* pixels (default: whole screen)."""
    if not _cfg_mod.config.overlay.enabled:
        return

    if all_metadata is None:
        all_metadata = load_metadata()

    photo = all_metadata.get(primary_guid)
    if not photo:
        return

    text = _build_text(photo)
    if not text:
        return

    pg = _pg()

    font_size = max(14, int(screen_h * _FONT_SIZE_RATIO))
    alpha = int(_cfg_mod.config.overlay.opacity * 255)

    # Render text first to know the box size
    try:
        font = pg.font.SysFont("dejavusans,sans-serif", font_size)
    except Exception:
        font = pg.font.Font(None, font_size)

    text_surf = font.render(text, True, (255, 255, 255))
    text_w = text_surf.get_width()
    text_h = text_surf.get_height()

    box_w = text_w + _PAD_X * 2
    box_h = text_h + _PAD_Y * 2
    radius = box_h // 2  # full pill shape

    # Center horizontally; position near bottom
    box_x = ((area_w or screen_w) - box_w) // 2
    margin = int(screen_h * _MARGIN_BOTTOM_RATIO)
    if _cfg_mod.config.overlay.position == "bottom":
        box_y = screen_h - box_h - margin
    else:
        box_y = margin

    # Draw pill with SRCALPHA so corners are truly transparent
    pill = pg.Surface((box_w, box_h), pg.SRCALPHA)
    pg.draw.rect(pill, (15, 15, 15, alpha), (0, 0, box_w, box_h), border_radius=radius)

    surface.blit(pill, (box_x, box_y))
    surface.blit(text_surf, (box_x + _PAD_X, box_y + _PAD_Y))
