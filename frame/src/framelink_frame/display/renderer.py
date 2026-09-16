"""
Photo rendering: layout, blurred fill, portrait pairing.

All heavy lifting uses Pillow (PIL) to avoid depending on pygame for
image processing. Surfaces are returned as pygame-compatible bytes and
converted by the caller.

Slot types:
  {"type": "single", "guid": "..."}
  {"type": "pair",   "guids": ["...", "..."]}
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageFilter

log = logging.getLogger(__name__)


def _load_pil(path: str | Path) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img.convert("RGB")


def _blurred_fill(photo: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Create a blurred, slightly-darkened version of photo scaled to (target_w, target_h).
    Used as background for non-16:9 photos.
    """
    bg = photo.resize((target_w, target_h), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
    # Darken so the sharp foreground photo pops
    return bg.point(lambda p: int(p * 0.5))


def _fit_centered(
    photo: Image.Image,
    canvas_w: int,
    canvas_h: int,
) -> tuple[Image.Image, int, int]:
    """
    Scale photo to fit within (canvas_w, canvas_h) keeping aspect ratio.
    Returns (scaled_img, x_offset, y_offset).
    """
    pw, ph = photo.size
    scale = min(canvas_w / pw, canvas_h / ph)
    new_w = int(pw * scale)
    new_h = int(ph * scale)
    scaled = photo.resize((new_w, new_h), Image.LANCZOS)
    x = (canvas_w - new_w) // 2
    y = (canvas_h - new_h) // 2
    return scaled, x, y


def render_single(
    photo_path: str | Path,
    screen_w: int,
    screen_h: int,
    fill_mode: str = "blurred",
) -> Image.Image:
    """Render one photo onto a (screen_w × screen_h) canvas."""
    photo = _load_pil(photo_path)
    canvas = Image.new("RGB", (screen_w, screen_h), (0, 0, 0))

    if fill_mode == "blurred":
        bg = _blurred_fill(photo, screen_w, screen_h)
        canvas.paste(bg, (0, 0))

    scaled, x, y = _fit_centered(photo, screen_w, screen_h)
    canvas.paste(scaled, (x, y))
    return canvas


def render_pair(
    left_path: str | Path,
    right_path: str | Path,
    screen_w: int,
    screen_h: int,
    fill_mode: str = "blurred",
) -> Image.Image:
    """
    Render two portrait photos side-by-side on a (screen_w × screen_h) canvas.
    Each photo gets half the screen width.

    Background: the two blurred fills are crossfaded in the center zone so
    there is no hard seam where the backgrounds meet.

    Photos: sit on top of the background; their inner edges get a subtle
    drop-shadow inward so they appear to float with some depth.
    """
    half_w = screen_w // 2

    left_photo  = _load_pil(left_path)
    right_photo = _load_pil(right_path)

    canvas = Image.new("RGB", (screen_w, screen_h), (0, 0, 0))

    if fill_mode == "blurred":
        # Render each bg at full-screen width so the crossfade looks continuous.
        left_bg  = _blurred_fill(left_photo,  screen_w, screen_h)
        right_bg = _blurred_fill(right_photo, screen_w, screen_h)
        bg_blend_w = int(screen_w * 0.20)  # blend zone: 20 % of width around center
        bg = _crossfade(left_bg, right_bg, screen_w, screen_h, half_w, bg_blend_w)
        canvas.paste(bg, (0, 0))

    # Each photo is centred in its half of the screen.
    # The gap between them shows the smoothly blended background.
    left_scaled,  lx, ly = _fit_centered(left_photo,  half_w, screen_h)
    right_scaled, rx, ry = _fit_centered(right_photo, half_w, screen_h)
    canvas.paste(left_scaled,  (lx, ly))
    canvas.paste(right_scaled, (half_w + rx, ry))


    return canvas


def _crossfade(
    img_a: Image.Image,
    img_b: Image.Image,
    w: int,
    h: int,
    cx: int,
    blend_w: int,
) -> Image.Image:
    """
    Composite img_a (left) and img_b (right) with an S-curve gradient blend
    centred at cx over a horizontal span of blend_w pixels.
    """
    half_blend = blend_w // 2
    row = Image.new("L", (w, 1), 0)
    for x in range(w):
        if x <= cx - half_blend:
            v = 0
        elif x >= cx + half_blend:
            v = 255
        else:
            t = (x - (cx - half_blend)) / blend_w
            v = int(t * t * (3 - 2 * t) * 255)  # smoothstep
        row.putpixel((x, 0), v)
    mask = row.resize((w, h), Image.NEAREST)
    # composite: mask=0 → img_a, mask=255 → img_b
    return Image.composite(img_b, img_a, mask)


def _apply_gap_shadow(
    canvas: Image.Image,
    left_inner: int,
    right_inner: int,
    h: int,
    feather_px: int,
    max_alpha: int = 200,
) -> None:
    """
    Cover the gap between the two photos with a dark shadow and soft feathered
    edges that bleed `feather_px` pixels into each photo.

    Gap region (left_inner → right_inner) is opaque black; the feather zones
    ease in/out with a quadratic curve so photo edges look natural.
    """
    feather_px = max(feather_px, 2)
    gap_w = right_inner - left_inner
    total_w = gap_w + feather_px * 2

    row = Image.new("L", (total_w, 1), 0)
    for x in range(total_w):
        if x < feather_px:
            t = x / feather_px
            a = int(t * t * max_alpha)          # ease in from left photo edge
        elif x >= total_w - feather_px:
            t = (total_w - 1 - x) / feather_px
            a = int(t * t * max_alpha)          # ease out into right photo edge
        else:
            a = max_alpha
        row.putpixel((x, 0), a)

    mask = row.resize((total_w, h), Image.NEAREST)
    dark = Image.new("RGB", (total_w, h), (0, 0, 0))
    canvas.paste(dark, (left_inner - feather_px, 0), mask)


def pil_to_pygame_surface(img: Image.Image):
    """Convert a PIL Image to a pygame Surface (lazy import to keep pygame optional)."""
    import pygame
    raw = img.tobytes()
    return pygame.image.frombytes(raw, img.size, "RGB")
