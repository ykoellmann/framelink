from datetime import date

import pytest

from framelink_frame.sidebar.data import build_data
from framelink_frame.sidebar.layout import build_layout

from sidebar_helpers import density

SCREENS = [(1920, 1080), (1366, 768), (1280, 1024)]
DAYS = [date(2026, 11, d) for d in (21, 25, 27, 30)]
DENSITIES = ["empty", "typical", "full", "vacations", "long", "today6"]
EPS = 1e-6


def make(screen, day, dens, horizon=4, multi=True):
    size = (round(screen[0] * .25), screen[1])
    return build_layout(build_data(density(dens, day), day), size, horizon, multi)


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("day", DAYS)
@pytest.mark.parametrize("dens", DENSITIES)
@pytest.mark.parametrize("multi", [True, False])
def test_nothing_overflows(screen, day, dens, multi):
    L = make(screen, day, dens, multi=multi)
    w, h = L.size
    assert L.weeks >= 1
    assert L.height <= L.budget + EPS
    # alles liegt innerhalb der Leiste; der letzte Block endet bündig oder davor
    last = L.blocks[-1]
    assert last.y + last.h <= h - L.pad_y + 1
    assert L.header.y + L.header.h <= L.blocks[0].y
    for a, b in zip(L.blocks, L.blocks[1:]):
        assert a.y + a.h <= b.y + EPS
    # Termintexte: jede Zeile passt in ihre Spalte (nach dem Kürzen)
    for b in L.blocks:
        assert len(b.rows) == 7
        for r in b.rows:
            assert len(r.lines) <= 2
            assert r.text_x + r.text_w <= r.x + r.w
            for ln in r.lines:
                assert ln.width <= ln.max_w + .01
            if not r.past:
                assert r.text_top >= r.y - EPS and r.text_top + max(1, len(r.lines)) * r.lh <= r.y + r.h + .5
            assert r.y >= b.y and r.y + r.h <= b.y + b.h + EPS
        for p in b.pills:
            assert p.x >= b.kw_x + 1 and p.x + p.w <= b.kw_x + b.rule_w + .5
    # Kopf: höchstens 3 Zeilen heute, jeder Eintrag in der Textspalte
    tops = {t.top for t in L.header.today}
    assert len(tops) <= 3
    for t in L.header.today:
        assert t.x + t.w <= L.pad_x + L.inner_w + .5
    if L.header.badge:
        assert L.header.badge_x + L.header.badge_w <= L.pad_x + L.inner_w + .5


@pytest.mark.parametrize("dens", DENSITIES)
def test_deterministic(dens):
    day = DAYS[2]
    assert make((1920, 1080), day, dens) == make((1920, 1080), day, dens)


def test_horizon_and_order_of_fallbacks():
    day = date(2026, 11, 21)
    four = make((1920, 1080), day, "empty", horizon=4)
    assert (four.weeks, four.sc, four.one_line) == (4, 1.0, False)       # leer: alles passt, mehrzeilig
    two = make((1920, 1080), day, "empty", horizon=2)
    assert two.weeks == 2
    dense = make((1920, 1080), day, "full", horizon=4)
    assert dense.weeks < 4 or dense.one_line                               # mehr Wochen vor mehrzeilig vor größerer Schrift
    assert make((1920, 1080), day, "typical", multi=False).one_line


def test_spare_space_goes_between_blocks_and_tall_screens_keep_flush():
    day = date(2026, 11, 30)
    L = make((1280, 1024), day, "empty")
    first, last = L.blocks[0], L.blocks[-1]
    assert first.y == pytest.approx(L.pad_y + L.header.h + 1.2 * L.u)     # oben bündig
    assert last.y + last.h == pytest.approx(L.size[1] - L.pad_y, abs=1)   # unten bündig
    gaps = [b.y - (a.y + a.h) for a, b in zip(L.blocks, L.blocks[1:])]
    assert max(gaps) - min(gaps) < 1e-6 and gaps[0] >= .4 * L.u


def test_today_row_is_tallest_and_past_rows_shorter():
    L = make((1920, 1080), date(2026, 11, 21), "typical")
    rows = {r.day: r for b in L.blocks for r in b.rows}
    now, past, fut = rows[date(2026, 11, 21)], rows[date(2026, 11, 17)], rows[date(2026, 11, 24)]
    assert now.now and past.past
    assert now.h == pytest.approx(fut.h * 1.35, rel=.01) and past.h == pytest.approx(fut.h * .8, rel=.01)


def test_emergency_anchor_on_absurdly_short_screen():
    L = make((1920, 300), date(2026, 11, 27), "full")
    assert L.weeks == 1 and L.one_line
