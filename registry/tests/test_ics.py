from datetime import date
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from framelink_registry.calendar_ics import (
    IcsError, classify, clean_title, fetch_ics, normalize_url, parse_ics,
)

TZ = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 11, 20)  # window 2026-11-06 .. 2027-02-18


def ics(*events: str) -> bytes:
    body = "\r\n".join(f"BEGIN:VEVENT\r\n{e.strip()}\r\nEND:VEVENT" for e in events)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n{body}\r\nEND:VCALENDAR\r\n".encode()


def parse(*events: str, today=TODAY):
    return parse_ics(ics(*events), TZ, today)


def test_all_day_single_multi_and_no_dtend():
    single, multi, nodtend = parse(
        "UID:a\nDTSTART;VALUE=DATE:20261121\nDTEND;VALUE=DATE:20261122\nSUMMARY:Single",
        "UID:b\nDTSTART;VALUE=DATE:20261123\nDTEND;VALUE=DATE:20261126\nSUMMARY:Multi",
        "UID:c\nDTSTART;VALUE=DATE:20261130\nSUMMARY:NoEnd",
    )
    assert (single["start"], single["end"], single["all_day"], single["time"]) == ("2026-11-21", "2026-11-21", True, None)
    assert (multi["start"], multi["end"]) == ("2026-11-23", "2026-11-25")  # exclusive DTEND -> inclusive
    assert (nodtend["start"], nodtend["end"]) == ("2026-11-30", "2026-11-30")


def test_timezones_tzid_utc_floating_and_windows_tzid():
    e = {x["title"]: x for x in parse(
        "UID:1\nDTSTART;TZID=Europe/Berlin:20261121T093000\nDTEND;TZID=Europe/Berlin:20261121T103000\nSUMMARY:Berlin",
        "UID:2\nDTSTART:20261122T080000Z\nSUMMARY:Utc",
        "UID:3\nDTSTART:20261123T140000\nSUMMARY:Floating",
        "UID:4\nDTSTART;TZID=W. Europe Standard Time:20261124T080000\nDTEND;TZID=W. Europe Standard Time:20261124T090000\nSUMMARY:Windows",
    )}
    assert (e["Berlin"]["time"], e["Berlin"]["end_time"], e["Berlin"]["all_day"]) == ("09:30", "10:30", False)
    assert e["Utc"]["time"] == "09:00" and e["Utc"]["end_time"] is None  # UTC+1 in November
    assert e["Floating"]["time"] == "14:00"
    assert (e["Windows"]["start"], e["Windows"]["time"]) == ("2026-11-24", "08:00")


def test_late_utc_rolls_to_next_local_day():
    (e,) = parse("UID:1\nDTSTART:20261121T233000Z\nDTEND:20261122T003000Z\nSUMMARY:Night")
    assert (e["start"], e["end"], e["time"]) == ("2026-11-22", "2026-11-22", "00:30")


def test_yearly_birthday_recurs_into_window():
    (e,) = parse("UID:1\nDTSTART;VALUE=DATE:19900105\nRRULE:FREQ=YEARLY\nSUMMARY:Oma")
    assert (e["start"], e["yearly"]) == ("2027-01-05", True)


def test_weekly_count_and_exdate():
    got = parse(
        "UID:1\nDTSTART;TZID=Europe/Berlin:20261111T180000\nDTEND;TZID=Europe/Berlin:20261111T190000\n"
        "RRULE:FREQ=WEEKLY;COUNT=4\nEXDATE;TZID=Europe/Berlin:20261125T180000\nSUMMARY:Chor"
    )
    assert [e["start"] for e in got] == ["2026-11-11", "2026-11-18", "2026-12-02"]
    assert not got[0]["yearly"]


def test_recurrence_id_moved_instance():
    got = parse(
        "UID:1\nDTSTART;TZID=Europe/Berlin:20261110T100000\nRRULE:FREQ=WEEKLY;COUNT=3\nSUMMARY:Weekly",
        "UID:1\nRECURRENCE-ID;TZID=Europe/Berlin:20261117T100000\n"
        "DTSTART;TZID=Europe/Berlin:20261118T150000\nSUMMARY:Moved",
    )
    assert [(e["title"], e["start"], e["time"]) for e in got] == [
        ("Weekly", "2026-11-10", "10:00"), ("Moved", "2026-11-18", "15:00"), ("Weekly", "2026-11-24", "10:00"),
    ]


def test_weekly_keeps_local_time_across_dst_change():
    got = parse_ics(ics(
        "UID:1\nDTSTART;TZID=Europe/Berlin:20261020T100000\nDTEND;TZID=Europe/Berlin:20261020T110000\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\nSUMMARY:Standup"
    ), TZ, date(2026, 10, 20))
    assert [(e["start"], e["time"]) for e in got] == [
        ("2026-10-20", "10:00"), ("2026-10-27", "10:00"), ("2026-11-03", "10:00")]  # DST ended 2026-10-25


def test_all_day_rrule():
    got = parse("UID:1\nDTSTART;VALUE=DATE:20261123\nDTEND;VALUE=DATE:20261124\nRRULE:FREQ=DAILY;COUNT=3\nSUMMARY:Daily")
    assert [e["start"] for e in got] == ["2026-11-23", "2026-11-24", "2026-11-25"]
    assert all(e["all_day"] and e["end"] == e["start"] for e in got)


def test_cancelled_skipped_and_broken_component_isolated():
    got = parse(
        "UID:1\nDTSTART;VALUE=DATE:20261121\nSTATUS:CANCELLED\nSUMMARY:Cancelled",
        "UID:2\nDTSTART:garbage\nSUMMARY:Broken",
        "UID:3\nDTSTART;VALUE=DATE:20261122\nSUMMARY:Good",
        "UID:4\nSUMMARY:No start at all",
    )
    assert [e["title"] for e in got] == ["Good"]


def test_window_edges():
    got = parse(
        "UID:1\nDTSTART;VALUE=DATE:20261101\nDTEND;VALUE=DATE:20261106\nSUMMARY:EndedBefore",  # last day Nov 5
        "UID:2\nDTSTART;VALUE=DATE:20261101\nDTEND;VALUE=DATE:20261108\nSUMMARY:Overlaps",  # last day Nov 7
        "UID:3\nDTSTART;VALUE=DATE:20270218\nSUMMARY:LastDay",
        "UID:4\nDTSTART;VALUE=DATE:20270219\nSUMMARY:TooLate",
    )
    assert [(e["title"], e["start"]) for e in got] == [("Overlaps", "2026-11-01"), ("LastDay", "2027-02-18")]


def test_emoji_removed():
    assert clean_title("🎂 Geburtstag ❤️ Oma 👨‍👩‍👧 1️⃣ 🇩🇪") == "Geburtstag Oma 1"
    assert clean_title("Zahnarzt – Müller € ä") == "Zahnarzt – Müller € ä"
    (e,) = parse("UID:1\nDTSTART;VALUE=DATE:20261121\nSUMMARY:🎉 Party 🎉")
    assert e["title"] == "Party"


def test_not_ics_rejected():
    with pytest.raises(IcsError):
        parse_ics(b"<html>nope</html>", TZ, TODAY)


def test_max_entries(monkeypatch):
    monkeypatch.setattr("framelink_registry.calendar_ics.MAX_ENTRIES", 3)
    got = parse("UID:1\nDTSTART;VALUE=DATE:20261121\nRRULE:FREQ=DAILY;COUNT=10\nSUMMARY:Daily")
    assert len(got) == 3


def test_classify():
    def e(**kw):
        return {"all_day": True, "start": "2026-11-21", "end": "2026-11-21", "yearly": False, "title": "x", **kw}

    for kind in ("appointment", "birthday", "holiday", "observance", "vacation", "school_holiday"):
        assert classify(kind, e(end="2026-11-25", yearly=True)) == kind  # explicit source kind wins
    assert classify("auto", e(end="2026-11-25")) == "vacation"
    assert classify("auto", e(yearly=True)) == "birthday"
    assert classify("auto", e(title="Opas GEBURTSTAG")) == "birthday"
    assert classify("auto", e()) == "appointment"
    assert classify("auto", e(all_day=False, time="10:00")) == "appointment"


def test_normalize_url():
    assert normalize_url("webcal://p01-caldav.icloud.com/x.ics") == "https://p01-caldav.icloud.com/x.ics"
    assert normalize_url(" WEBCALS://h/x ") == "https://h/x"
    assert normalize_url("http://h/x") == "http://h/x"
    for bad in ("file:///etc/passwd", "ftp://h/x", "javascript:alert(1)", "https://", "x"):
        with pytest.raises(ValueError):
            normalize_url(bad)


@respx.mock
async def test_fetch_ics_ok_and_errors():
    respx.get("https://h/ok.ics").respond(200, content=b"abc")
    assert await fetch_ics("webcal://h/ok.ics") == b"abc"

    respx.get("https://h/404.ics").respond(404)
    with pytest.raises(IcsError, match="404"):
        await fetch_ics("https://h/404.ics")

    respx.get("https://h/big.ics").respond(200, content=b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(IcsError, match="5 MB"):
        await fetch_ics("https://h/big.ics")

    respx.get("https://h/down.ics").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(IcsError):
        await fetch_ics("https://h/down.ics")

    with pytest.raises(IcsError):
        await fetch_ics("file:///etc/passwd")
