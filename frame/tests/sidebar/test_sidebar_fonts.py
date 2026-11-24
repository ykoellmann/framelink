import pytest

from framelink_frame.sidebar import fonts

GLYPHS = "ÄÖÜäöüß€–·"


@pytest.mark.parametrize("family,weight", [(f, w) for f, ws in fonts.FILES.items() for w in ws])
def test_bundled_font_renders_german_glyphs(family, weight):
    path = fonts.FONT_DIR / fonts.FILES[family][weight]
    assert path.exists(), f"{path} fehlt"
    font = fonts.get(family, weight, 40)
    assert font.path == str(path)  # echte Datei, nicht der Pillow-Ersatz
    notdef = bytes(font.getmask("￿"))
    for ch in GLYPHS:
        m = font.getmask(ch)
        assert m.getbbox(), f"{ch!r} leer in {path.name}"
        assert bytes(m) != notdef, f"{ch!r} fehlt in {path.name}"


def test_ofl_license_bundled():
    assert (fonts.FONT_DIR / "OFL.txt").exists()


def test_ellipsize_fits_and_keeps_short_text():
    f = fonts.get("inter", 500, 20)
    assert fonts.ellipsize(f, "Kurz", 500) == ("Kurz", f.getlength("Kurz"))
    text, w = fonts.ellipsize(f, "Ein ziemlich langer Termintitel", 120)
    assert text.endswith("…") and w <= 120 and f.getlength(text) == w
    assert fonts.ellipsize(f, "Lang genug zum Kürzen", 3) == ("", 0.0)
