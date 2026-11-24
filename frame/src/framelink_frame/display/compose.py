"""
Slot composition for the calendar layout: photo area (left 75 % of the screen), a
feathered or mirrored edge toward the free space, and the calendar sidebar (right 25 %).

Sizes follow the design spec: u = screen width / 100 pixels. All blurring is done at
1/8 resolution and scaled up, which is far cheaper on the Pi and looks just as soft.
"""
from __future__ import annotations

import functools
from datetime import date
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

from ..sidebar import render_sidebar
from . import renderer

PANE_FRACTION = 0.75
PAIR_GAP = 0.012            # gap between the two photos of a pair, as a share of the group width
BG_BLUR_U = 3.0             # background blur sigma (u)
BG_BRIGHTNESS = 0.7
MIRROR_BLUR_U = 2.0
MIRROR_BRIGHTNESS = 0.75
GLASS_BLUR_U = 1.8
GLASS_SATURATION = 1.3
EDGE_FEATHER_U = {"hard": 0.0, "soft": 6.0, "softer": 10.0, "mirror": 3.0}
FREE_TOLERANCE = 0.995      # a photo narrower/shorter than this share of the pane leaves free space
_DIV = 8                    # blur resolution divisor


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def plan_layout(aspects: list[float], pane_w: int, pane_h: int) -> list[tuple[int, int, int, int]]:
    """
    Rectangles (x, y, w, h) in pane coordinates. All photos share one height; the group
    (two photos get a 1.2 % gap) is fitted into the pane without cropping and centred.
    """
    n = len(aspects)
    gap_ratio = PAIR_GAP if n == 2 else 0.0
    group_aspect = sum(aspects) / (1 - gap_ratio)
    if group_aspect >= pane_w / pane_h:
        gw, gh = pane_w, round(pane_w / group_aspect)
    else:
        gw, gh = round(pane_h * group_aspect), pane_h
    gap = round(gw * gap_ratio)
    photos_w = gw - gap * (n - 1)
    widths = [round(photos_w * a / sum(aspects)) for a in aspects]
    widths[-1] = photos_w - sum(widths[:-1])        # absorb rounding in the last photo
    x, y = (pane_w - gw) // 2, (pane_h - gh) // 2
    rects = []
    for w in widths:
        rects.append((x, y, w, gh))
        x += w + gap
    return rects


def group_box(rects: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    return x0, y0, max(r[0] + r[2] for r in rects) - x0, max(r[1] + r[3] for r in rects) - y0


def free_axes(box: tuple[int, int, int, int], pane_w: int, pane_h: int) -> tuple[bool, bool]:
    """(horizontal, vertical): does the photo group leave free space on that axis?"""
    return box[2] < pane_w * FREE_TOLERANCE, box[3] < pane_h * FREE_TOLERANCE


# ---------------------------------------------------------------------------
# Masks (smoothstep ramps)
# ---------------------------------------------------------------------------

def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def _ramp(n: int, r: int) -> bytes:
    """n values 0..255: smoothstep up over r px at the start and down over r px at the end."""
    r = min(r, n // 2)
    vals = bytearray([255]) * n
    for i in range(r):
        a = round(255 * _smooth((i + 0.5) / r))
        vals[i] = a
        vals[n - 1 - i] = a
    return bytes(vals)


@functools.lru_cache(maxsize=8)
def feather_mask(w: int, h: int, rx: int, ry: int) -> Image.Image:
    """L mask for a w x h photo group: 0 at the border, 255 inside, ramp widths rx / ry (0 = hard). Do not modify."""
    white = Image.new("L", (w, h), 255)
    mx = Image.frombytes("L", (w, 1), _ramp(w, rx)).resize((w, h), Image.NEAREST) if rx else white
    my = Image.frombytes("L", (1, h), _ramp(h, ry)).resize((w, h), Image.NEAREST) if ry else white
    return ImageChops.multiply(mx, my)


def _fade(size: tuple[int, int], side: str) -> Image.Image:
    """Mask for a mirrored copy on `side` ('l','r','t','b'): opaque at the photo, transparent far away."""
    w, h = size
    n = w if side in "lr" else h
    vals = bytearray(n)
    for i in range(n):
        near_first = side in "rb"                       # copy to the right/below: photo edge is at index 0
        dist = ((i if near_first else n - 1 - i) + 0.5) / n
        vals[i] = round(255 * (1 - _smooth(dist)))
    shape = (n, 1) if side in "lr" else (1, n)
    return Image.frombytes("L", shape, bytes(vals)).resize((w, h), Image.NEAREST)


# ---------------------------------------------------------------------------
# Background and edge
# ---------------------------------------------------------------------------

def background(photos: list[Image.Image], w: int, h: int, u: float) -> Image.Image:
    """Blurred, darkened cover of the photo(s). A pair crossfades photo 1 (left) into photo 2 (right)."""
    sw, sh = max(1, w // _DIV), max(1, h // _DIV)

    def one(p: Image.Image) -> Image.Image:
        s = max(sw / p.width, sh / p.height) * 1.15      # slightly oversized so the blur has no dark rim
        sm = p.resize((max(sw, round(p.width * s)), max(sh, round(p.height * s))), Image.BILINEAR, reducing_gap=2.0)
        l, t = (sm.width - sw) // 2, (sm.height - sh) // 2
        return sm.crop((l, t, l + sw, t + sh)).filter(ImageFilter.GaussianBlur(BG_BLUR_U * u / _DIV))

    smalls = [one(p) for p in photos]
    small = smalls[0]
    if len(smalls) == 2:
        small = renderer._crossfade(smalls[0], smalls[1], sw, sh, sw // 2, max(2, int(sw * 0.2)))
    return ImageEnhance.Brightness(small.resize((w, h), Image.BICUBIC)).enhance(BG_BRIGHTNESS)


def mirror_layer(group: Image.Image, origin: tuple[int, int], pane: tuple[int, int],
                 free: tuple[bool, bool], u: float, overlap: int = 0) -> Image.Image:
    """
    RGBA layer (pane size): blurred mirror images of the photo group on the free sides, fading outward.
    The copies reach `overlap` px under the photo, so the feathered photo edge blends into the mirror
    (not into the plain background, which would leave a dark seam).
    """
    pw, ph = pane
    q = lambda v: max(1, round(v / _DIV))                                    # noqa: E731
    gs = group.convert("RGB").resize((q(group.width), q(group.height)), Image.BILINEAR)
    layer = Image.new("RGBA", (q(pw), q(ph)), (0, 0, 0, 0))
    blur = ImageFilter.GaussianBlur(MIRROR_BLUR_U * u / _DIV)
    x, y = round(origin[0] / _DIV), round(origin[1] / _DIV)      # positions may be 0 (q() would bump them to 1)
    ov = round(overlap / _DIV)
    sides = (["l", "r"] if free[0] else []) + (["t", "b"] if free[1] else [])
    for side in sides:
        m = ImageOps.mirror(gs) if side in "lr" else ImageOps.flip(gs)
        m = ImageEnhance.Brightness(m.filter(blur)).enhance(MIRROR_BRIGHTNESS)
        pos = {"l": (x - m.width + ov, y), "r": (x + gs.width - ov, y),
               "t": (x, y - m.height + ov), "b": (x, y + gs.height - ov)}[side]
        layer.paste(m.convert("RGBA"), pos, _fade(m.size, side))
    return layer.resize((pw, ph), Image.BICUBIC)


def glass_backdrop(bg_region: Image.Image, u: float) -> Image.Image:
    """What shows through the glass sidebar: the background, softened further and more saturated."""
    sw, sh = max(1, bg_region.width // _DIV), max(1, bg_region.height // _DIV)
    small = bg_region.resize((sw, sh), Image.BILINEAR).filter(ImageFilter.GaussianBlur(GLASS_BLUR_U * u / _DIV))
    return ImageEnhance.Color(small.resize(bg_region.size, Image.BICUBIC)).enhance(GLASS_SATURATION)


# ---------------------------------------------------------------------------
# Whole slot
# ---------------------------------------------------------------------------

def _aspect(path: Path) -> float:
    with Image.open(path) as im:
        return im.width / im.height


def compose_slot(paths: list[Path], size: tuple[int, int], cal, entries: list, today: date) -> Image.Image:
    """
    Render a photo slot (one photo or a portrait pair) plus the calendar sidebar.
    `cal` is the CalendarConfig; `entries` the registry entries from calendar.json.
    """
    sw, sh = size
    u = sw / 100
    pane_w = round(sw * PANE_FRACTION)
    side_w = sw - pane_w

    rects = plan_layout([_aspect(p) for p in paths], pane_w, sh)
    photos = [
        renderer._load_pil(p, fit=(r[2], r[3])).resize((r[2], r[3]), Image.LANCZOS)
        for p, r in zip(paths, rects)
    ]
    gx, gy, gw, gh = group_box(rects)
    free = free_axes((gx, gy, gw, gh), pane_w, sh)

    glass = cal.style == "glass"
    bg_full = background(photos, sw, sh, u) if glass else None      # glass shows the background across the full width
    canvas = (bg_full.crop((0, 0, pane_w, sh)) if glass else background(photos, pane_w, sh, u)).convert("RGBA")

    group = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    for photo, r in zip(photos, rects):
        group.paste(photo, (r[0] - gx, r[1] - gy))
    fe = round(EDGE_FEATHER_U[cal.edge] * u)
    if cal.edge == "mirror" and any(free):
        canvas = Image.alpha_composite(canvas, mirror_layer(group, (gx, gy), (pane_w, sh), free, u, fe))
    if fe and any(free):
        mask = feather_mask(gw, gh, fe if free[0] else 0, fe if free[1] else 0)
        group.putalpha(ImageChops.multiply(group.getchannel("A"), mask))
    canvas.alpha_composite(group, (gx, gy))

    full = Image.new("RGB", (sw, sh))
    full.paste(canvas.convert("RGB"), (0, 0))
    if glass:
        full.paste(glass_backdrop(bg_full.crop((pane_w, 0, sw, sh)), u), (pane_w, 0))
    side = render_sidebar(entries, today, (side_w, sh), style=cal.style, horizon=cal.horizon_weeks,
                          multi_line=cal.multi_line)
    full.paste(side, (pane_w, 0), side)
    return full
