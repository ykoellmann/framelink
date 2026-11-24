import json
from datetime import date, timedelta
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "calendar_mockup.json"


def mockup() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def entry(kind, title, start, end=None, **kw):
    start = start if isinstance(start, str) else start.isoformat()
    end = end or start
    return dict(kind=kind, title=title, start=start, end=end if isinstance(end, str) else end.isoformat(),
                all_day=kw.pop("all_day", True), time=kw.pop("time", None), **kw)


def density(name: str, today: date) -> list:
    """Einträge verschiedener Dichte rund um `today`."""
    mon = today - timedelta(days=today.weekday())
    days = [mon + timedelta(days=i) for i in range(-7, 60)]
    if name == "empty":
        return []
    if name == "typical":
        return mockup()["entries"]
    if name == "full":  # jeder Tag mit drei Einträgen
        return [entry(k, f"{k} {d.day}", d) for d in days for k in ("holiday", "appointment", "observance")]
    if name == "vacations":  # vier überlappende Urlaube plus Ferien
        return [entry("vacation", f"Urlaub {i} mit langem Namen", mon + timedelta(days=i), mon + timedelta(days=9 + i)) for i in range(5)] + \
               [entry("school_holiday", "Ferien", mon - timedelta(days=3), mon + timedelta(days=12))]
    if name == "long":
        t = "Sehr langer Titel einer Veranstaltung ohne jede Rücksicht auf die Spaltenbreite " * 2
        return [entry("appointment", t + str(i), d) for i, d in enumerate(days)] + \
               [entry("vacation", t, mon, mon + timedelta(days=20))]
    if name == "today6":
        return [entry(k, f"Heute {i}", today) for i, k in enumerate(["holiday", "birthday", "appointment", "appointment", "observance", "appointment"])] + \
               [entry("vacation", "Heute im Urlaub", today - timedelta(days=1), today + timedelta(days=2)),
                entry("school_holiday", "Heute Ferien", today - timedelta(days=2), today + timedelta(days=4))]
    raise KeyError(name)
