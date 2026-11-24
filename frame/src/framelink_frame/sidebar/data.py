"""Einträge der Registry -> Tagesliste, Urlaubsspuren und Farben (wie im Mockup)."""
from dataclasses import dataclass, field
from datetime import date, timedelta

DOW = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
DOW_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MON = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
MON_LONG = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]

# Registry-Typ -> (Kürzel wie im Mockup, Farbtoken); Urlaub bekommt die Farbe aus der Rotation
KINDS = {"holiday": ("h", "hol"), "birthday": ("b", "bday"), "appointment": ("e", "evt"), "observance": ("o", "obs"),
         "vacation": ("v", None), "school_holiday": ("f", "fer")}
ORDER = {"h": 0, "b": 1, "e": 2, "o": 3}
LOOKBACK, LOOKAHEAD = 7, 7 * 9  # Tage vor dem Montag / nach dem Montag, die wir überhaupt einlesen


@dataclass(frozen=True)
class Item:
    kind: str    # h b e o v f
    text: str
    color: str   # Farbtoken: hol bday evt obs fer r1..r4


@dataclass
class Span:
    a: date
    b: date      # inklusiv
    kind: str    # v (Urlaub, Streifen) | f (Ferien, Tönung)
    title: str
    lane: int = 0
    color: str = "fer"

    def covers(self, d: date) -> bool:
        return self.a <= d <= self.b


@dataclass
class CalData:
    today: date
    monday: date
    days: dict = field(default_factory=dict)   # date -> tuple[Item]
    spans: list = field(default_factory=list)  # nach (Start, Ende, Titel) sortiert

    def items(self, d: date) -> tuple:
        return self.days.get(d, ())

    def is_holiday(self, d: date) -> bool:
        return any(i.kind == "h" for i in self.items(d))

    def in_school_holiday(self, d: date) -> bool:
        return any(s.kind == "f" and s.covers(d) for s in self.spans)

    def strips_on(self, d: date) -> list:
        return [s for s in self.spans if s.kind == "v" and s.covers(d)]

    def today_items(self) -> list:
        """Heutige Termine, danach laufende Urlaube/Ferien."""
        run = [Item(s.kind, s.title, s.color) for s in self.spans if s.covers(self.today)]
        return list(self.items(self.today)) + run

    def lanes_in(self, first: date, weeks: int) -> int:
        last = first + timedelta(days=7 * weeks - 1)
        return max([0] + [s.lane + 1 for s in self.spans if s.kind == "v" and s.a <= last and s.b >= first])

    def pills_in(self, week: date) -> list:
        """Eintrag erscheint im Block, in dem er beginnt, oder im ersten sichtbaren, wenn er davor begann."""
        end = week + timedelta(days=6)
        return [s for s in self.spans if s.a <= end and s.b >= week and (s.a >= week or week == self.monday)]


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _label(e: dict) -> str:
    title = " ".join(str(e.get("title") or "").split())
    t = e.get("time")
    return f"{title} {t}" if t and not e.get("all_day", False) else title


def build_data(entries: list, today: date) -> CalData:
    mon = monday_of(today)
    lo, hi = mon - timedelta(days=LOOKBACK), mon + timedelta(days=LOOKAHEAD)
    days: dict = {}
    spans = []
    for e in entries or []:
        try:
            a = date.fromisoformat(str(e["start"])[:10])
            b = max(a, date.fromisoformat(str(e.get("end") or e["start"])[:10]))
        except (KeyError, ValueError):
            continue
        k, col = KINDS.get(e.get("kind"), KINDS["appointment"])
        text = _label(e)
        if not text or b < lo or a > hi:
            continue
        if k in "vf":
            spans.append(Span(a, b, k, text, color=col or "r1"))
            continue
        d = max(a, lo)
        while d <= min(b, hi):
            days.setdefault(d, []).append((ORDER[k], str(e.get("time") or ""), text, Item(k, text, col)))
            d += timedelta(days=1)
    out = {d: tuple(x[3] for x in sorted(v, key=lambda x: x[:3])) for d, v in days.items()}
    spans.sort(key=lambda s: (s.a, s.b, s.kind, s.title))
    _assign_lanes(spans)
    return CalData(today, mon, out, spans)


def _assign_lanes(spans: list) -> None:
    """Überlappende Urlaube: eigene Spur (höchstens 4) und rotierende Farbe r1..r4, wie im Mockup."""
    rot = 0
    vac = [s for s in spans if s.kind == "v"]
    for i, s in enumerate(vac):
        ov = [o for o in vac[:i] if o.b >= s.a and o.a <= s.b]
        lane = 0
        while any(o.lane == lane for o in ov) and lane < 3:
            lane += 1
        k = rot % 4
        while len(ov) < 4 and any(o.color == f"r{k + 1}" for o in ov):
            k = (k + 1) % 4
        s.lane, s.color = lane, f"r{k + 1}"
        rot = k + 1


def iso_week(d: date) -> int:
    return d.isocalendar()[1]
