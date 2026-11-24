"""Gebündelte Schriften (statische TTF, SIL OFL). Fehlt eine Datei, fällt Pillow auf seine eingebaute Schrift zurück."""
import logging
import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

log = logging.getLogger(__name__)

FONT_DIR = Path(os.environ.get("FRAMELINK_FONT_DIR") or Path(__file__).parent / "assets" / "fonts")
FILES = {
    "inter": {400: "Inter-Regular.ttf", 500: "Inter-Medium.ttf", 600: "Inter-SemiBold.ttf"},
    "grotesk": {500: "SpaceGrotesk-Medium.ttf", 600: "SpaceGrotesk-SemiBold.ttf", 700: "SpaceGrotesk-Bold.ttf"},
}


@lru_cache(maxsize=512)
def get(family: str, weight: int, px: float) -> ImageFont.FreeTypeFont:
    """Schrift je (Familie, Gewicht, Größe). Gewicht rastet auf das nächste gebündelte ein."""
    files = FILES[family]
    w = min(files, key=lambda k: abs(k - weight))
    px = max(1.0, round(px * 8) / 8)
    try:
        return ImageFont.truetype(str(FONT_DIR / files[w]), px, layout_engine=ImageFont.Layout.BASIC)
    except OSError:
        log.warning("Schrift %s fehlt, nehme Pillow-Standardschrift", FONT_DIR / files[w])
        return ImageFont.load_default(px)


def ascent_descent(font) -> tuple[int, int]:
    return font.getmetrics()


def baseline(font, top: float, line_h: float) -> float:
    """Grundlinie einer Zeile, die wie in CSS mittig in einer Zeilenbox [top, top+line_h] sitzt."""
    asc, desc = font.getmetrics()
    return top + (line_h - (asc + desc)) / 2 + asc


def ellipsize(font, text: str, max_w: float) -> tuple[str, float]:
    """Kürzt `text` mit „…“ auf höchstens `max_w` Pixel. Liefert (Text, gemessene Breite)."""
    w = font.getlength(text)
    if w <= max_w:
        return text, w
    ell = font.getlength("…")
    if ell > max_w:
        return "", 0.0
    lo, hi = 0, len(text)  # größtes Präfix, das mit … noch passt
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.getlength(text[:mid].rstrip()) + ell <= max_w:
            lo = mid
        else:
            hi = mid - 1
    out = text[:lo].rstrip() + "…"
    return out, font.getlength(out)
