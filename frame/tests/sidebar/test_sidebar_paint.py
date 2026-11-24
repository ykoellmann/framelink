from datetime import date

import pytest
from PIL import Image, ImageChops

from framelink_frame.sidebar import render as R
from framelink_frame.sidebar.render import render_sidebar
from framelink_frame.sidebar.theme import THEMES

from sidebar_helpers import mockup

TODAY = date(2026, 11, 21)


@pytest.mark.parametrize("style", ["dark", "glass", "light"])
@pytest.mark.parametrize("screen", [(1920, 1080), (1280, 720)])
def test_render_smoke(style, screen):
    size = (screen[0] // 4, screen[1])
    img = render_sidebar(mockup()["entries"], TODAY, size, style=style)
    assert img.mode == "RGBA" and img.size == size
    panel = Image.new("RGBA", size, THEMES[style].panel)
    changed = ImageChops.difference(img, panel).convert("L").point(lambda v: 255 if v else 0).histogram()[255]
    assert changed > size[0] * size[1] * .05  # Text, Zeilen, Streifen heben sich vom Hintergrund ab


def test_glass_is_translucent_dark_and_light_are_opaque():
    e = mockup()["entries"]
    glass = render_sidebar(e, TODAY, (480, 1080), style="glass")
    assert glass.getpixel((200, 5))[3] == 128                      # Tönung rgba(10,11,14,.5) im Leerraum
    assert glass.getpixel((0, 500))[:3] != glass.getpixel((200, 5))[:3] or glass.getpixel((0, 500))[3] > 128   # helle Linie links
    for s in ("dark", "light"):
        assert render_sidebar(e, TODAY, (480, 1080), style=s).getchannel("A").getextrema() == (255, 255)


def test_today_row_is_filled_with_foreground():
    img = render_sidebar(mockup()["entries"], TODAY, (480, 1080), style="dark")
    fg = THEMES["dark"].fg[:3]
    assert sum(1 for x in range(60, 440, 20) if img.getpixel((x, 295))[:3] == fg) >= 10   # Sa 21. gefüllt, siehe Mockup


def test_cache_returns_same_image_and_keys_differ():
    R._CACHE.clear()
    e = mockup()["entries"]
    a = render_sidebar(e, TODAY, (480, 1080))
    assert render_sidebar(list(e), TODAY, (480, 1080)) is a
    assert render_sidebar(e, TODAY, (480, 1080), style="light") is not a
    assert render_sidebar(e, date(2026, 11, 22), (480, 1080)) is not a
    assert render_sidebar(e, TODAY, (480, 1080), horizon=3) is not a
    assert render_sidebar(e, TODAY, (480, 1080), multi_line=False) is not a
    assert render_sidebar(e[:-1], TODAY, (480, 1080)) is not a


def test_rows_modes_differ_and_fully_empty_data_renders():
    e = mockup()["entries"]
    assert render_sidebar(e, TODAY, (480, 1080), rows="we").tobytes() != render_sidebar(e, TODAY, (480, 1080)).tobytes()
    assert render_sidebar([], TODAY, (480, 1080)).size == (480, 1080)
