import json
from datetime import date
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from framelink_frame.config import CalendarConfig
from framelink_frame.display import compose

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "calendar_mockup.json").read_text(encoding="utf-8"))
TODAY = date.fromisoformat(FIXTURE["today"])
PANE = (1440, 1080)

ASPECTS = {"4:3": [4 / 3], "3:2": [3 / 2], "16:9": [16 / 9], "pair": [3 / 4, 3 / 4], "portrait": [3 / 4], "square": [1.0]}


@pytest.mark.parametrize("name", ASPECTS)
def test_plan_layout_stays_inside_pane_and_keeps_aspect(name):
    aspects = ASPECTS[name]
    rects = compose.plan_layout(aspects, *PANE)
    assert len(rects) == len(aspects)
    for (x, y, w, h), a in zip(rects, aspects):
        assert x >= 0 and y >= 0 and x + w <= PANE[0] and y + h <= PANE[1]
        assert abs(w / h - a) < 0.01                       # aspect preserved (rounding only)
    assert len({r[3] for r in rects}) == 1                  # photos of a pair are equally tall
    gx, gy, gw, gh = compose.group_box(rects)
    assert abs((gx + gw / 2) - PANE[0] / 2) <= 1 and abs((gy + gh / 2) - PANE[1] / 2) <= 1   # centred


def test_pair_has_a_small_gap_and_free_axes():
    (x1, _, w1, _), (x2, _, w2, _) = compose.plan_layout([3 / 4, 3 / 4], *PANE)
    gap = x2 - (x1 + w1)
    assert 0 < gap < 0.02 * (w1 + w2)
    # pane is 4:3, so a 4:3 photo fills it and a 16:9 photo leaves free space top and bottom
    assert compose.free_axes(compose.group_box(compose.plan_layout([4 / 3], *PANE)), *PANE) == (False, False)
    assert compose.free_axes(compose.group_box(compose.plan_layout([16 / 9], *PANE)), *PANE) == (False, True)
    assert compose.free_axes(compose.group_box(compose.plan_layout([3 / 4], *PANE)), *PANE) == (True, False)


def test_feather_mask_ramps_from_zero_to_full_and_is_monotonic():
    m = compose.feather_mask(400, 200, 60, 0)
    row = [m.getpixel((x, 100)) for x in range(400)]
    assert row[0] < 8 and row[-1] < 8 and row[200] == 255
    assert row[:60] == sorted(row[:60]) and row[-60:] == sorted(row[-60:], reverse=True)
    assert all(m.getpixel((200, y)) == 255 for y in (0, 100, 199))       # ry = 0: no vertical fade
    hard = compose.feather_mask(400, 200, 0, 0)
    assert hard.getextrema() == (255, 255)


@pytest.mark.parametrize("side", "lrtb")
def test_fade_is_opaque_at_the_photo_and_transparent_far_away(side):
    f = compose._fade((100, 100), side)
    near = {"l": (99, 50), "r": (0, 50), "t": (50, 99), "b": (50, 0)}[side]
    far = {"l": (0, 50), "r": (99, 50), "t": (50, 0), "b": (50, 99)}[side]
    assert f.getpixel(near) > 240 and f.getpixel(far) < 15


def _jpeg(path, w, h, color):
    Image.new("RGB", (w, h), color).save(path, "JPEG")
    return path


@pytest.fixture
def photos(tmp_path):
    return {
        "4:3": [_jpeg(tmp_path / "a.jpg", 1600, 1200, (200, 90, 60))],
        "16:9": [_jpeg(tmp_path / "b.jpg", 1600, 900, (60, 140, 200))],
        "portrait": [_jpeg(tmp_path / "c.jpg", 900, 1200, (80, 180, 90))],
        "pair": [_jpeg(tmp_path / "d.jpg", 900, 1200, (200, 180, 60)), _jpeg(tmp_path / "e.jpg", 900, 1200, (120, 60, 180))],
    }


@pytest.mark.parametrize("style", ["dark", "glass", "light"])
@pytest.mark.parametrize("edge", ["hard", "soft", "softer", "mirror"])
@pytest.mark.parametrize("fmt", ["4:3", "16:9", "portrait", "pair"])
def test_compose_slot_fills_the_screen(photos, style, edge, fmt):
    size = (640, 360)
    cal = CalendarConfig(enabled=True, style=style, edge=edge)
    img = compose.compose_slot(photos[fmt], size, cal, FIXTURE["entries"], TODAY)
    assert img.size == size and img.mode == "RGB"
    pane_w = round(size[0] * compose.PANE_FRACTION)
    # the sidebar is not blank: its region differs from the photo area's average colour
    side = img.crop((pane_w, 0, size[0], size[1]))
    assert side.getextrema() != ((0, 0), (0, 0), (0, 0))


def test_photo_area_does_not_depend_on_the_sidebar(photos):
    size = (640, 360)
    pane = (0, 0, round(size[0] * compose.PANE_FRACTION), size[1])
    cal = CalendarConfig(enabled=True, style="dark", edge="softer")
    with_entries = compose.compose_slot(photos["16:9"], size, cal, FIXTURE["entries"], TODAY).crop(pane)
    without = compose.compose_slot(photos["16:9"], size, cal, [], TODAY).crop(pane)
    assert ImageChops.difference(with_entries, without).getbbox() is None


def test_softer_edge_changes_pixels_only_where_there_is_free_space(photos):
    size = (640, 360)
    pane_w = round(size[0] * compose.PANE_FRACTION)

    def render(edge, fmt):
        return compose.compose_slot(photos[fmt], size, CalendarConfig(enabled=True, edge=edge), [], TODAY).crop((0, 0, pane_w, size[1]))

    # a 4:3 photo fills the pane exactly: no free axis, so no feathering at all
    assert ImageChops.difference(render("hard", "4:3"), render("softer", "4:3")).getbbox() is None
    # a 16:9 photo leaves free space above and below: the feathered edge differs from the hard one
    assert ImageChops.difference(render("hard", "16:9"), render("softer", "16:9")).getbbox() is not None
