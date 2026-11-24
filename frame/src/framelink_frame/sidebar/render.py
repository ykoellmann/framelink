"""Einstieg: Registry-Einträge -> fertige RGBA-Leiste, zwischengespeichert."""
import hashlib
import json
from collections import OrderedDict
from datetime import date

from .data import build_data
from .layout import build_layout
from .paint import paint
from .theme import THEMES

_CACHE: OrderedDict = OrderedDict()
_MAX = 4


def render_sidebar(entries: list, today: date, size: tuple, *, style: str = "dark", horizon: int = 4,
                   multi_line: bool = True, rows: str = "zebra"):
    """Leiste in `size` (Breite = 25 % des Bildschirms) als RGBA. Das Ergebnis wird gecacht; nicht verändern, nur kopieren."""
    digest = hashlib.sha1(json.dumps(entries, sort_keys=True, default=str).encode()).hexdigest()
    key = (today, digest, style, horizon, bool(multi_line), tuple(size), rows)
    img = _CACHE.get(key)
    if img is None:
        layout = build_layout(build_data(entries, today), tuple(size), horizon, multi_line, rows)
        img = paint(layout, THEMES[style])
        _CACHE[key] = img
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return img
