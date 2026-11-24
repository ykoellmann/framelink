"""Layout der Leiste. Alle Maße in Pixeln; Texte werden gemessen und gekürzt, nichts läuft über.

`u` = Bildschirmbreite / 100 = Leistenbreite / 25 (Maßsystem des Mockups, dort `cqw`).
Reihenfolge der Kandidaten: mehr Wochen vor mehrzeilig vor größerer Schrift, zuletzt ein Notanker.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from . import fonts
from .data import DOW, DOW_LONG, MON, MON_LONG, CalData, iso_week

P = {4: (1.4, 1.0), 3: (1.9, 1.25), 2: (2.9, 1.6)}   # Wochen -> (Zeilenhöhe rh, Schrift rf) in u; 1 Woche nutzt P[2]
SC = {4: (1.0,), 3: (1.0, .92), 2: (1.0, .92, .85, .78), 1: (.78, .6, .45, .3)}
LH = 1.15  # Zeilenbox eines Termins in rf


@dataclass(frozen=True)
class Line:
    text: str
    width: float     # gemessene Breite ohne Punkt
    max_w: float     # verfügbare Breite ohne Punkt
    kind: str
    color: str


@dataclass(frozen=True)
class Strip:
    lane: int
    color: str
    first: bool
    last: bool


@dataclass(frozen=True)
class Row:
    day: date
    x: float; y: float; w: float; h: float
    now: bool; past: bool; sun: bool; hol: bool; wk: bool; zb: bool; we: bool; fer: bool
    wd: str; num: str
    rf: float; fs: float; lh: float
    wd_x: float; num_x: float; text_x: float; text_w: float
    cy: float            # Mitte der ersten Textzeile
    text_top: float
    lines: tuple
    more: int            # "+n" am Ende der letzten Zeile
    more_w: float
    strips: tuple


@dataclass(frozen=True)
class Pill:
    text: str
    x: float; y: float; w: float; h: float
    text_w: float
    color: str
    past: bool


@dataclass(frozen=True)
class Block:
    y: float; h: float
    kw: str; kw_x: float; kw_cy: float; head_px: float
    range_text: str; range_x: float
    pills: tuple
    rule_y: float; rule_w: float
    rows: tuple


@dataclass(frozen=True)
class TodayItem:
    text: str; x: float; top: float; w: float; color: str


@dataclass(frozen=True)
class Header:
    y: float; h: float
    big: str; big_x: float; big_top: float; big_px: float; big_cell: float; big_ls: float
    dow: str; dow_x: float; dow_top: float; dow_px: float
    sub: str; sub_top: float; sub_px: float
    today: tuple; today_px: float; today_lh: float
    badge: str; badge_x: float; badge_top: float; badge_w: float


@dataclass(frozen=True)
class Layout:
    size: tuple
    u: float
    budget: float        # verfügbare Höhe = Höhe - 2*1,4 u
    height: float        # tatsächlich belegt (Mindesthöhe, ohne verteilten Restplatz)
    weeks: int
    sc: float
    one_line: bool       # True: nur der wichtigste Eintrag plus "+n"
    lanes: int
    header: Header
    blocks: tuple
    pad_x: float; pad_y: float; inner_w: float


def tab_cell(font) -> float:
    """Breite einer tabellarischen Ziffer (Pillow BASIC kennt kein tnum)."""
    return max(font.getlength(c) for c in "0123456789")


def _header(data: CalData, u: float, x0: float, y0: float, inner_w: float) -> Header:
    big_px = 4.6 * u
    bf = fonts.get("grotesk", 700, big_px)
    cell, ls = tab_cell(bf), -.03 * big_px
    big = str(data.today.day)
    big_w = len(big) * (cell + ls)
    tx = x0 + big_w + 1.2 * u
    avail = inner_w - big_w - 1.2 * u
    dow_px, sub_px, t_px = 1.9 * u, 1.15 * u, 1.2 * u
    dow_lh, sub_lh, t_lh = 1.1 * dow_px, 1.3 * sub_px, 1.3 * t_px
    dow = fonts.ellipsize(fonts.get("grotesk", 600, dow_px), DOW_LONG[data.today.weekday()], avail)[0]
    d = data.today
    sub = fonts.ellipsize(fonts.get("inter", 400, sub_px),
                          f"{MON_LONG[d.month - 1]} {d.year} · KW {iso_week(data.monday)}", avail)[0]

    # heutige Einträge: Punkt + Titel, umbrechend, höchstens 3 Zeilen plus "+n"
    f = fonts.get("inter", 600, t_px)
    lines: list = [[], [], []]
    items, line, x, rest = data.today_items(), 0, 0.0, 0
    for i, it in enumerate(items):
        text, tw = fonts.ellipsize(f, it.text, avail - t_px)
        iw = t_px + tw
        if x and x + u + iw > avail:
            line, x = line + 1, 0.0
        if line >= 3:
            rest = len(items) - i
            break
        px = x + (u if x else 0)
        lines[line].append([text, px, iw, it.color])
        x = px + iw
    bw, btxt = 0.0, ""
    if rest:
        bf2 = fonts.get("inter", 600, .8 * t_px)
        while True:
            btxt = f"+{rest}"
            bw = bf2.getlength(btxt) + .8 * t_px
            last = lines[2]
            end = last[-1][1] + last[-1][2] if last else -u
            if not last or end + u + bw <= avail:
                break
            last.pop()
            rest += 1
    nl = sum(1 for ln in lines if ln)
    t_h = dow_lh + sub_lh + nl * t_lh
    hd_h = max(big_px, t_h)
    ty = y0 + (hd_h - t_h) / 2
    ty_list = ty + dow_lh + sub_lh
    today = tuple(TodayItem(t, tx + px, ty_list + li * t_lh, w, c)
                  for li, ln in enumerate(lines) for t, px, w, c in ln)
    bx = tx + ((lines[2][-1][1] + lines[2][-1][2] + u) if lines[2] else 0) if rest else 0.0
    return Header(y0, hd_h, big, x0, y0 + (hd_h - big_px) / 2, big_px, cell, ls,
                  dow, tx, ty, dow_px, sub, ty + dow_lh, sub_px,
                  today, t_px, t_lh, btxt if rest else "", bx, ty_list + 2 * t_lh, bw)


def _row(data: CalData, d: date, x: float, y: float, w: float, u: float, rh: float, rf: float,
         multi_line: bool, lanes: int, rows_mode: str) -> Row:
    now, past = d == data.today, d < data.today
    items = data.items(d)
    n = max(1, min(2, len(items))) if multi_line else 1
    lh = LH * rf
    h = (rh + (n - 1) * lh) * (1.35 if now else .8 if past else 1.0)
    fs = rf * (1.12 if now else 1.0)
    pad_l = .4 * u + lanes * .55 * u
    wd_x = x + pad_l
    num_x = wd_x + 2 * rf + .5 * u
    text_x = num_x + 1.9 * rf + .5 * u
    text_w = x + w - .4 * u - text_x
    f = fonts.get("inter", 500, fs)
    shown, rest = items[:n], max(0, len(items) - n)
    more_w = 0.0
    if rest:
        more_w = fonts.get("inter", 600, .8 * fs).getlength(f"+{rest}") + .8 * fs
    lines = []
    for i, it in enumerate(shown):
        mw = text_w - fs - (more_w + .6 * fs if rest and i == len(shown) - 1 else 0)
        text, tw = fonts.ellipsize(f, it.text, mw)
        lines.append(Line(text, tw, mw, it.kind, it.color))
    if n > 1:
        top = y + max(0.0, min((rh - lh) / 2, h - n * lh))   # wie im Mockup: erste Zeile oben
    else:
        top = y + (h - lh) / 2
    wk = d.weekday() >= 5 and rows_mode != "we"
    we = d.weekday() >= 5 and rows_mode == "we"
    strips = tuple(Strip(s.lane, s.color, d == s.a, d == s.b) for s in data.strips_on(d))
    return Row(d, x, y, w, h, now, past, d.weekday() == 6, data.is_holiday(d), wk,
               rows_mode == "zebra" and d.weekday() in (1, 3, 5), we, data.in_school_holiday(d),
               DOW[d.weekday()], str(d.day), rf, fs, lh, wd_x, num_x, text_x, text_w,
               top + lh / 2, top, tuple(lines), rest, more_w, strips)


def _block(data: CalData, week: date, u: float, x: float, y: float, w: float, rh: float, rf: float,
           multi_line: bool, lanes: int, rows_mode: str) -> Block:
    px = .88 * rf
    f = fonts.get("inter", 500, px)
    kw = f"KW {iso_week(week)}"
    kw_w = f.getlength(kw)
    src = data.pills_in(week)
    pills, rng, rng_w, ph = [], "", 0.0, 0.0
    if src:
        pf = fonts.get("inter", 500, .8 * rf)
        avail = w - kw_w - u
        lines: list = [[]]
        used = 0.0
        for s in src:
            text, tw = fonts.ellipsize(pf, s.title, avail - .96 * rf)
            pw = tw + .96 * rf
            if lines[-1] and used + .3 * u + pw > avail:
                lines.append([])
                used = 0.0
            used += pw + (.3 * u if lines[-1] else 0)
            lines[-1].append((s, text, tw, pw))
        ph = len(lines) * rf + (len(lines) - 1) * .2 * u
        ch = max(px, ph)
        for j, ln in enumerate(lines):
            total = sum(p[3] for p in ln) + .3 * u * (len(ln) - 1)
            cx = x + w - total
            for s, text, tw, pw in ln:
                pills.append(Pill(text, cx, y + (ch - ph) / 2 + j * (rf + .2 * u), pw, rf, tw, s.color, s.b < data.today))
                cx += pw + .3 * u
    else:
        ch = px
        a, b = week, week + timedelta(days=6)
        rng = f"{a.day}. {MON[a.month - 1]} – {b.day}. {MON[b.month - 1]}"
        rng_w = f.getlength(rng)
    rule_y = y + ch + .25 * u
    cur = rule_y + 1 + .2 * u
    rows = []
    for k in range(7):
        d = week + timedelta(days=k)
        now = d == data.today
        top_gap = .15 * u if now and k else 0.0   # als erste Zeile verschmilzt der obere Rand mit dem 0,2 u der Wochenzeile (CSS)
        r = _row(data, d, x, cur + top_gap, w, u, rh, rf, multi_line, lanes, rows_mode)
        rows.append(r)
        cur = r.y + r.h + (.15 * u if now else 0.0)
    return Block(y, cur - y, kw, x, y + ch / 2, px, rng, x + w - rng_w, tuple(pills), rule_y, w, tuple(rows))


def _make(data: CalData, size: tuple, weeks: int, sc: float, one_line: bool, multi_line: bool,
          rows_mode: str, spread: bool) -> Layout:
    w, h = size
    u = w / 25
    pad_x, pad_y = 1.5 * u, 1.4 * u
    inner = w - 2 * pad_x
    rh, rf = P[max(weeks, 2)][0] * sc * u, P[max(weeks, 2)][1] * sc * u
    ml = multi_line and not one_line
    hd = _header(data, u, pad_x, pad_y, inner)
    top = pad_y + hd.h + 1.2 * u
    lanes = data.lanes_in(data.monday, weeks)
    mondays = [data.monday + timedelta(days=7 * k) for k in range(weeks)]
    blocks = [_block(data, m, u, pad_x, 0, inner, rh, rf, ml, lanes, rows_mode) for m in mondays]
    height = hd.h + 1.2 * u + sum(b.h for b in blocks) + (weeks - 1) * .4 * u
    budget = h - 2 * pad_y
    if spread:
        extra = max(0.0, budget - height) / (weeks - 1) if weeks > 1 else 0.0
        y, out = top, []
        for m in mondays:
            b = _block(data, m, u, pad_x, y, inner, rh, rf, ml, lanes, rows_mode)
            out.append(b)
            y += b.h + .4 * u + extra
        blocks = out
    return Layout(size, u, budget, height, weeks, sc, one_line, lanes, hd, tuple(blocks), pad_x, pad_y, inner)


def build_layout(data: CalData, size: tuple, horizon: int = 4, multi_line: bool = True, rows_mode: str = "zebra") -> Layout:
    """Wählt Wochenzahl, Schriftgröße und ein-/mehrzeilig so, dass nichts überläuft, und verteilt den Restplatz."""
    horizon = max(2, min(4, int(horizon)))
    budget = size[1] - 2 * 1.4 * (size[0] / 25)
    for weeks in range(horizon, 1, -1):
        for one_line in ((False, True) if multi_line else (True,)):
            for sc in SC[weeks]:
                if _make(data, size, weeks, sc, one_line, multi_line, rows_mode, False).height <= budget:
                    return _make(data, size, weeks, sc, one_line, multi_line, rows_mode, True)
    for sc in SC[1]:  # Notanker: eine Woche, je Tag nur ein Eintrag
        if _make(data, size, 1, sc, True, multi_line, rows_mode, False).height <= budget:
            break
    return _make(data, size, 1, sc, True, multi_line, rows_mode, True)
