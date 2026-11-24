"""framelink-bench: Leiste und Foto-Vorstufen messen, Beispielbilder schreiben.

Liefert PNGs der Leiste (alle Stile, Mockup-Daten) und eine einfache Nebeneinander-Vorschau je Fotoformat
sowie report.json mit Zeiten je Stufe und Spitzen-RSS. Das echte Zusammensetzen (display/compose.py) gehört
nicht dazu; die Vorschau stellt Foto links (eingepasst) und Leiste rechts nur grob dar.
"""
import argparse
import io
import json
import platform
import resource
import sys
import time
from datetime import date
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from framelink_frame.sidebar import render as sidebar_render
from framelink_frame.sidebar.data import build_data
from framelink_frame.sidebar.layout import build_layout
from framelink_frame.sidebar.paint import paint
from framelink_frame.sidebar.theme import THEMES

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "calendar_mockup.json"
# Seitenverhältnis, Anzahl Fotos (2 = Hochformat-Paar), Name
FORMATS = {"4x3": (4 / 3, 1), "3x2": (3 / 2, 1), "16x9": (16 / 9, 1), "pair": (3 / 4, 2), "portrait": (3 / 4, 1), "square": (1, 1)}
DAYS = ["2026-11-21", "2026-11-25", "2026-11-27", "2026-11-30"]


def rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if sys.platform == "darwin" else r / 1024


def sample_photo(aspect: float, long_side: int, seed: int) -> Image.Image:
    """Weicher Farbverlauf mit hellem Fleck, als JPEG-Ersatz für ein Foto."""
    w, h = (long_side, round(long_side / aspect)) if aspect >= 1 else (round(long_side * aspect), long_side)
    small = Image.linear_gradient("L").resize((64, 64)).rotate(90 * (seed % 4))
    r = ImageChops.invert(small).point(lambda v: 40 + v * 160 // 255)
    img = Image.merge("RGB", (r, small.point(lambda v: 70 + v // 2), small.point(lambda v: 150 - v // 3)))
    ImageDraw.Draw(img).ellipse((18, 12, 46, 40), fill=(255, 205, 140))
    return img.filter(ImageFilter.GaussianBlur(3)).resize((w, h), Image.BICUBIC)


def timed(report: dict, key: str, fn):
    t = time.perf_counter()
    out = fn()
    report[key] = round((time.perf_counter() - t) * 1000, 1)
    return out


def contain(img: Image.Image, w: int, h: int) -> Image.Image:
    s = min(w / img.width, h / img.height)
    return img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)


def photo_stages(jpeg: list, pane: tuple, rep: dict) -> Image.Image:
    """Dekodieren (mit draft), Einpassen, weichgezeichneter Hintergrund (in 1/8-Auflösung). Gibt die Fläche zurück."""
    pw, ph = pane
    imgs = []
    for data in jpeg:
        def dec():
            im = Image.open(io.BytesIO(data))
            im.draft("RGB", (pw, ph))
            return im.convert("RGB")
        imgs.append(timed(rep, "decode_ms", dec) if not imgs else dec())
    fits = timed(rep, "scale_ms", lambda: [contain(im, pw, ph) if len(imgs) == 1 else contain(im, pw // 2 - 8, ph) for im in imgs])
    ref = imgs[0]

    def bg():
        sw, sh = max(1, pw // 8), max(1, ph // 8)
        s = max(sw / ref.width, sh / ref.height) * 1.15
        sm = ref.resize((max(sw, round(ref.width * s)), max(sh, round(ref.height * s))), Image.BILINEAR)
        l, t = (sm.width - sw) // 2, (sm.height - sh) // 2
        sm = sm.crop((l, t, l + sw, t + sh)).filter(ImageFilter.GaussianBlur(3 * pw / 100 / 8))
        return ImageEnhance.Brightness(sm.resize((pw, ph), Image.BILINEAR)).enhance(.7)
    pane_img = timed(rep, "background_ms", bg)
    x0 = (pw - sum(f.width for f in fits) - 8 * (len(fits) - 1)) // 2
    for f in fits:
        pane_img.paste(f, (x0, (ph - f.height) // 2))
        x0 += f.width + 8
    return pane_img


def preview(pane_img: Image.Image, side: Image.Image, style: str, size: tuple) -> Image.Image:
    """Foto links, Leiste rechts. Glas: Hintergrund unter der Leiste weichzeichnen (vereinfachtes backdrop-filter)."""
    w, h = size
    sw = side.width
    full = Image.new("RGB", size, (11, 12, 14))
    full.paste(pane_img, (0, 0))
    if style == "glass":
        bgc = pane_img.resize((sw, h)) if pane_img.height != h else pane_img.crop((pane_img.width - sw, 0, pane_img.width, h))
        bgc = ImageEnhance.Color(bgc.filter(ImageFilter.GaussianBlur(1.8 * w / 100))).enhance(1.3)
        full.paste(bgc, (w - sw, 0))
    full.paste(side, (w - sw, 0), side)
    return full


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="bench-out", help="Zielordner für PNGs und report.json")
    ap.add_argument("--size", default="1920x1080", help="Bildschirmgröße, z. B. 1280x720")
    ap.add_argument("--photos", help="Ordner mit eigenen JPEGs statt der Beispielbilder")
    ap.add_argument("--long-side", type=int, default=4000, help="Längere Seite der Beispielfotos (Pixel)")
    ap.add_argument("--repeat", type=int, default=3, help="Wiederholungen für die Leistenzeiten")
    a = ap.parse_args(argv)
    W, H = map(int, a.size.lower().split("x"))
    side_w = round(W * .25)
    pane = (W - side_w, H)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = {"python": sys.version.split()[0], "platform": platform.platform(), "pillow": Image.__version__,
              "screen": [W, H], "sidebar": {}, "photos": {}}

    # 1) Leiste: Mockup-Daten, alle Stile, vier Tage, plus Varianten
    variants = [(d, s, 4, True, "zebra") for d in DAYS for s in THEMES]
    variants += [(DAYS[3], "dark", 3, True, "zebra"), (DAYS[3], "dark", 4, False, "zebra"), (DAYS[3], "dark", 4, True, "we")]
    for day, style, hz, ml, rows in variants:
        today = date.fromisoformat(day)
        name = f"sidebar_{style}_{day[5:]}_h{hz}_{'multi' if ml else 'one'}_{rows}"
        rep = {}
        cold = []
        for _ in range(a.repeat):
            t = time.perf_counter()
            lay = build_layout(build_data(fx["entries"], today), (side_w, H), hz, ml, rows)
            t1 = time.perf_counter()
            img = paint(lay, THEMES[style])
            cold.append(((t1 - t) * 1000, (time.perf_counter() - t1) * 1000))
        sidebar_render._CACHE.clear()
        t = time.perf_counter(); sidebar_render.render_sidebar(fx["entries"], today, (side_w, H), style=style, horizon=hz, multi_line=ml, rows=rows)
        rep["cold_ms"] = round((time.perf_counter() - t) * 1000, 1)
        t = time.perf_counter(); sidebar_render.render_sidebar(fx["entries"], today, (side_w, H), style=style, horizon=hz, multi_line=ml, rows=rows)
        rep["warm_ms"] = round((time.perf_counter() - t) * 1000, 3)
        rep["layout_ms"] = round(min(c[0] for c in cold), 1)
        rep["paint_ms"] = round(min(c[1] for c in cold), 1)
        rep.update(weeks=lay.weeks, scale=lay.sc, one_line=lay.one_line, min_height_u=round(lay.height / lay.u, 2),
                   budget_u=round(lay.budget / lay.u, 2))
        report["sidebar"][name] = rep
        img.save(out / f"{name}.png")

    # 2) Fotoformate: Vorstufen messen, Vorschau mit Leiste
    if a.photos:
        files = sorted(p for p in Path(a.photos).iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
        sources = {p.stem: ([p.read_bytes()], 1) for p in files}
    else:
        sources = {}
        for i, (name, (asp, n)) in enumerate(FORMATS.items()):
            blobs = []
            for k in range(n):
                buf = io.BytesIO()
                sample_photo(asp, a.long_side, i + k).save(buf, "JPEG", quality=90)
                blobs.append(buf.getvalue())
            sources[name] = (blobs, n)
    for name, (blobs, _) in sources.items():
        rep = {"jpeg_kb": round(sum(len(b) for b in blobs) / 1024)}
        pane_img = photo_stages(blobs, pane, rep)
        rep["peak_rss_mb"] = round(rss_mb(), 1)
        report["photos"][name] = rep
        for style in THEMES:
            side = sidebar_render.render_sidebar(fx["entries"], date.fromisoformat(DAYS[0]), (side_w, H), style=style)
            preview(pane_img, side, style, (W, H)).save(out / f"preview_{name}_{style}.png")

    report["peak_rss_mb"] = round(rss_mb(), 1)
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(list(out.glob('*.png')))} PNGs und report.json in {out} (Spitzen-RSS {report['peak_rss_mb']} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
