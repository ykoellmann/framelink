"""Zeichnet ein Layout mit Pillow. Kleine Formen werden 4x überabgetastet; alles wird per Alpha-over gesetzt."""
from functools import lru_cache
from math import ceil

from PIL import Image, ImageDraw

from . import fonts
from .layout import Layout, Row, Block
from .theme import Theme, mix, with_alpha

SS = 4  # Überabtastung für Rundungen


@lru_cache(maxsize=512)
def _mask(w: int, h: int, r4: int, corners: tuple) -> Image.Image:
    if r4 <= 0 or not any(corners):
        return Image.new("L", (w, h), 255)
    big = Image.new("L", (w * SS, h * SS), 0)
    r4 = min(r4, w * SS // 2, h * SS // 2)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=r4, fill=255, corners=corners)
    return big.resize((w, h), Image.LANCZOS)


@lru_cache(maxsize=256)
def _alpha_table(a: int) -> tuple:
    return tuple(v * a // 255 for v in range(256))


def _blit(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """alpha_composite mit Beschnitt an den Rändern von dst."""
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + src.width, dst.width), min(y + src.height, dst.height)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + src.width, y + src.height):
        src = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    dst.alpha_composite(src, (x0, y0))


def _over(dst: Image.Image, x: int, y: int, mask: Image.Image, rgba: tuple) -> None:
    a = rgba[3]
    if a == 0:
        return
    if a < 255:
        mask = mask.point(_alpha_table(a))
    solid = Image.new("RGBA", mask.size, (*rgba[:3], 255))
    solid.putalpha(mask)
    _blit(dst, solid, x, y)


def rect(dst, x, y, w, h, rgba, r=0.0, corners=(True, True, True, True)):
    w, h = max(1, round(w)), max(1, round(h))
    _over(dst, round(x), round(y), _mask(w, h, round(r * SS), tuple(corners)), rgba)


def dot(dst, cx, cy, d, rgba):
    d = max(1, round(d))
    _over(dst, round(cx - d / 2), round(cy - d / 2), _mask(d, d, d * SS // 2, (True,) * 4), rgba)


def text(dst, x, base, s, font, rgba):
    """Text mit linker Grundlinienkante bei (x, base)."""
    if not s:
        return
    asc, desc = font.getmetrics()
    w, h = ceil(font.getlength(s)) + 4, asc + desc + 4
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).text((2, 2 + asc), s, font=font, fill=255, anchor="ls")
    _over(dst, round(x) - 2, round(base) - asc - 2, m, rgba)


def _tx(dst, x, cy, s, family, weight, px, rgba, lh=1.0):
    """Text mittig auf cy (wie eine CSS-Zeilenbox der Höhe lh*px)."""
    f = fonts.get(family, weight, px)
    text(dst, x, fonts.baseline(f, cy - lh * px / 2, lh * px), s, f, rgba)


def _badge(dst, x, cy, label, w, px, bg, fg):
    """Kleine Pille "+n": Inter 600 in `px`, Höhe 1,4 em."""
    h = 1.4 * px
    rect(dst, x, cy - h / 2, w, h, bg, r=h / 2)
    f = fonts.get("inter", 600, px)
    text(dst, x + w / 2 - f.getlength(label) / 2, fonts.baseline(f, cy - h / 2, h), label, f, fg)


def _header(img, L: Layout, t: Theme):
    h = L.header
    bf = fonts.get("grotesk", 700, h.big_px)
    x, base = h.big_x, fonts.baseline(bf, h.big_top, h.big_px)
    for ch in h.big:
        text(img, x + (h.big_cell - bf.getlength(ch)) / 2, base, ch, bf, t.fg)
        x += h.big_cell + h.big_ls
    f = fonts.get("grotesk", 600, h.dow_px)
    text(img, h.dow_x, fonts.baseline(f, h.dow_top, 1.1 * h.dow_px), h.dow, f, t.fg)
    f = fonts.get("inter", 400, h.sub_px)
    text(img, h.dow_x, fonts.baseline(f, h.sub_top, 1.3 * h.sub_px), h.sub, f, t.dim)
    f, px = fonts.get("inter", 600, h.today_px), h.today_px
    for it in h.today:
        cy = it.top + h.today_lh / 2
        base = fonts.baseline(f, it.top, h.today_lh)
        dot(img, it.x + .275 * px, base - .295 * px, .55 * px, t.colors[it.color])
        text(img, it.x + px, base, it.text, f, t.fg)
    if h.badge:
        _badge(img, h.badge_x, h.badge_top + h.today_lh / 2, h.badge, h.badge_w, .8 * px, t.tint, t.dim)


def _row(img, r: Row, L: Layout, t: Theme):
    u, rw, rh = L.u, max(1, round(r.w)), max(1, round(r.h))
    lay = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    ox, oy = r.x, r.y
    if r.now:
        rect(lay, 0, 0, rw, rh, t.fg, r=.3 * u)
    else:
        if r.zb:
            rect(lay, 0, 0, rw, rh, t.zb, r=.3 * u)
        elif r.we:
            rect(lay, 0, 0, rw, rh, t.tint, r=.3 * u)
        if r.fer:
            rect(lay, 0, 0, rw, rh, with_alpha(t.colors["fer"], .17), r=.3 * u)
    sw, rad = .4 * u, min(.3 * u, .2 * u)
    for s in r.strips:
        top, bot = (.15 * u if s.first else 0), (rh - .15 * u if s.last else rh)
        rect(lay, .3 * u + s.lane * .55 * u, top, sw, bot - top, t.colors[s.color], r=rad,
             corners=(s.first, s.first, s.last, s.last))
    ink = t.inv if r.now else t.fg
    # Wochentag und Tageszahl, mittig zur ersten Textzeile
    cy = r.cy - oy
    wpx = .88 * r.fs
    _tx(lay, r.wd_x - ox, cy, r.wd, "inter", 600 if r.wk else 500, wpx, t.inv if r.now else (t.fg if r.wk else t.dim), 1.1)
    npx = 1.1 * r.fs
    nf = fonts.get("grotesk", 600, npx)
    ncol = t.inv if r.now else (t.colors["hol"] if r.sun or r.hol else t.fg)
    base = fonts.baseline(nf, cy - npx / 2, npx)
    cell = max(nf.getlength(c) for c in "0123456789")
    x = r.num_x - ox
    for ch in r.num:
        text(lay, x + (cell - nf.getlength(ch)) / 2, base, ch, nf, ncol)
        x += cell
    # Termine
    f = fonts.get("inter", 500, r.fs)
    for i, ln in enumerate(r.lines):
        top = r.text_top - oy + i * r.lh
        base = fonts.baseline(f, top, r.lh)
        tx = r.text_x - ox
        if r.now:
            dot(lay, tx + .275 * r.fs, base - .295 * r.fs, .55 * r.fs + .24 * r.fs, t.inv)
        dot(lay, tx + .275 * r.fs, base - .295 * r.fs, .55 * r.fs, t.colors[ln.color])
        text(lay, tx + r.fs, base, ln.text, f, ink)
        if r.more and i == len(r.lines) - 1:
            _badge(lay, tx + r.fs + ln.width + .6 * r.fs, top + r.lh / 2, f"+{r.more}", r.more_w, .8 * r.fs,
                   with_alpha(t.inv, .22) if r.now else t.tint, t.inv if r.now else t.dim)
    if r.past:
        lay.putalpha(lay.getchannel("A").point(_alpha_table(round(.38 * 255))))
    _blit(img, lay, round(r.x), round(r.y))


def _block(img, b: Block, L: Layout, t: Theme):
    cy = b.kw_cy
    _tx(img, b.kw_x, cy, b.kw, "inter", 500, b.head_px, t.dim)
    if b.range_text:
        _tx(img, b.range_x, cy, b.range_text, "inter", 500, b.head_px, t.dim)
    pf_px = None
    for p in b.pills:
        c = t.colors[p.color]
        k = .45 if p.past else 1.0
        rect(img, p.x, p.y, p.w, p.h, with_alpha((*c[:3], round(.24 * 255)), k), r=p.h / 2)
        pf_px = .8 * p.h
        _tx(img, p.x + .48 * p.h, p.y + p.h / 2, p.text, "inter", 500, pf_px, with_alpha(mix(c, t.fg, .65), k), 1.25)
    rect(img, b.kw_x, b.rule_y, b.rule_w, 1, t.line2)
    for r in b.rows:
        _row(img, r, L, t)


def paint(L: Layout, theme: Theme) -> Image.Image:
    """RGBA-Bild der Leiste in `L.size`. Bei Glas ist der Hintergrund die halbtransparente Tönung."""
    img = Image.new("RGBA", L.size, theme.panel)
    if theme.edge:
        rect(img, 0, 0, 1, L.size[1], theme.edge)
    _header(img, L, theme)
    for b in L.blocks:
        _block(img, b, L, theme)
    return img
