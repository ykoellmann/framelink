from datetime import date

from framelink_frame.display.main import calendar_update
from framelink_frame.sync import cache, calendar_sync

TZ = "Europe/Berlin"


def test_first_call_returns_a_stamp_even_without_a_file(cache_dir, monkeypatch):
    monkeypatch.setattr(calendar_sync, "today_in", lambda tz: date(2026, 11, 21))
    stamp, entries = calendar_update(None, TZ)
    assert stamp == (None, date(2026, 11, 21)) and entries == []
    assert calendar_update(stamp, TZ) is None            # nothing changed since


def test_new_file_and_new_day_both_trigger_a_redraw(cache_dir, monkeypatch):
    day = {"d": date(2026, 11, 21)}
    monkeypatch.setattr(calendar_sync, "today_in", lambda tz: day["d"])
    stamp, _ = calendar_update(None, TZ)

    cache.save_calendar({"entries": [{"title": "Kaffee", "start": "2026-11-24"}]})
    stamp2, entries = calendar_update(stamp, TZ)
    assert entries == [{"title": "Kaffee", "start": "2026-11-24"}] and stamp2 != stamp
    assert calendar_update(stamp2, TZ) is None

    day["d"] = date(2026, 11, 22)                         # midnight in the configured zone
    stamp3, entries3 = calendar_update(stamp2, TZ)
    assert stamp3[1] == date(2026, 11, 22) and entries3 == entries


def test_unchanged_calendar_payload_does_not_trigger_a_redraw(cache_dir, monkeypatch):
    monkeypatch.setattr(calendar_sync, "today_in", lambda tz: date(2026, 11, 21))
    payload = {"entries": [{"title": "x", "start": "2026-11-21"}]}
    cache.save_calendar(payload)
    stamp, _ = calendar_update(None, TZ)
    cache.save_calendar(payload)                          # the sync ran again, same content: file untouched
    assert calendar_update(stamp, TZ) is None
