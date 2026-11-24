"""Farben je Stil (Abschnitt 2 der Design-Spezifikation)."""
from dataclasses import dataclass

RGBA = tuple[int, int, int, int]


def hexa(h: str, a: float = 1.0) -> RGBA:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), round(a * 255))


def mix(a: RGBA, b: RGBA, t: float) -> RGBA:
    """Wie color-mix(in srgb, a t, b): Anteil t von a, Rest b (deckend gemischt, Alpha von a)."""
    return (*(round(x * t + y * (1 - t)) for x, y in zip(a[:3], b[:3])), a[3])


def with_alpha(c: RGBA, a: float) -> RGBA:
    return (*c[:3], round(c[3] * a))


@dataclass(frozen=True)
class Theme:
    name: str
    panel: RGBA          # Hintergrund der Leiste (Glas: halbtransparente Tönung)
    edge: RGBA | None    # 1 px Linie links (nur Glas)
    fg: RGBA
    dim: RGBA
    inv: RGBA
    zb: RGBA
    tint: RGBA
    line2: RGBA
    colors: dict         # hol bday evt obs fer r1..r4


_DARK_COLORS = dict(hol=hexa("#ff6b5b"), bday=hexa("#ffc247"), evt=hexa("#4fd1c0"), obs=hexa("#9aa7bd"), fer=hexa("#e0b565"),
                    r1=hexa("#a98bff"), r2=hexa("#ff79c6"), r3=hexa("#5b9dff"), r4=hexa("#9bd84e"))
_DARK = dict(fg=hexa("#f4f2ee"), dim=hexa("#f4f2ee", .66), inv=hexa("#111"), zb=hexa("#000", .22),
             tint=hexa("#fff", .06), line2=hexa("#fff", .16), colors=_DARK_COLORS)

THEMES = {
    "dark": Theme("dark", panel=hexa("#111317"), edge=None, **_DARK),
    "glass": Theme("glass", panel=hexa("#0a0b0e", .5), edge=hexa("#fff", .14), **_DARK),
    "light": Theme("light", panel=hexa("#f6f7f9"), edge=None, fg=hexa("#14171b"), dim=hexa("#14171b", .64), inv=hexa("#fff"),
                   zb=hexa("#14171b", .05), tint=hexa("#14171b", .055), line2=hexa("#14171b", .16),
                   colors=dict(hol=hexa("#d63a2c"), bday=hexa("#d99a00"), evt=hexa("#0f9e8e"), obs=hexa("#7385a3"), fer=hexa("#b9861c"),
                               r1=hexa("#7a4fd6"), r2=hexa("#d6358f"), r3=hexa("#1f6fd6"), r4=hexa("#5a9a12"))),
}
