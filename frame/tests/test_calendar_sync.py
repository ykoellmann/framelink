import json
from datetime import date

import httpx
import pytest
import respx

from framelink_frame.config import Config, load_config
from framelink_frame.sync import cache, calendar_sync, registry

BASE = "http://registry.test"
ENTRIES = f"{BASE}/api/calendar/entries"


def make_cfg(**calendar) -> Config:
    return Config.model_validate({
        "registry": {"url": BASE, "api_key": "k"},
        "calendar": {"enabled": True, "ids": ["a", "b"], **calendar},
    })


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(calendar_sync, "today_in", lambda tz: date(2026, 11, 21))   # a Saturday


def test_window_is_last_monday_minus_a_week_to_eight_weeks_ahead():
    # Saturday 2026-11-21 -> Monday 2026-11-16
    assert calendar_sync.window(date(2026, 11, 21)) == (date(2026, 11, 9), date(2027, 1, 11))
    assert calendar_sync.window(date(2026, 11, 16))[0] == date(2026, 11, 9)   # Monday itself
    assert calendar_sync.window(date(2026, 11, 22))[0] == date(2026, 11, 9)   # Sunday


@respx.mock
def test_run_once_writes_payload_and_skips_unchanged(cache_dir):
    route = respx.get(ENTRIES).respond(json={
        "from": "2026-11-09", "to": "2027-01-11", "tz": "Europe/Berlin",
        "generated_at": "2026-11-21T10:00:00Z",
        "calendars": [{"id": "a", "name": "Familie"}],
        "entries": [{"id": "a:1:2026-11-24", "title": "Kaffee", "start": "2026-11-24"}],
    })
    cfg = make_cfg()

    assert calendar_sync.run_once(cfg) is True
    sent = route.calls[0].request
    assert sent.headers["X-API-Key"] == "k"
    assert dict(sent.url.params) == {"from": "2026-11-09", "to": "2027-01-11", "ids": "a,b"}

    saved = json.loads(cache.calendar_path().read_text())
    assert "generated_at" not in saved and saved["ids"] == ["a", "b"]
    assert saved["entries"][0]["title"] == "Kaffee"

    mtime = cache.calendar_path().stat().st_mtime_ns
    assert calendar_sync.run_once(cfg) is False          # same content
    assert cache.calendar_path().stat().st_mtime_ns == mtime


@respx.mock
def test_registry_failure_keeps_old_file_and_main_exits_1(cache_dir, monkeypatch):
    cache.save_calendar({"entries": [{"title": "old"}]})
    respx.get(ENTRIES).respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        calendar_sync.run_once(make_cfg())
    assert cache.load_calendar() == {"entries": [{"title": "old"}]}

    monkeypatch.setattr(calendar_sync, "_startup_config", make_cfg())
    with pytest.raises(SystemExit) as exc:
        calendar_sync.main()
    assert exc.value.code == 1


@respx.mock(assert_all_mocked=True)
@pytest.mark.parametrize("cal", [{"ids": []}, {"enabled": False}])
def test_nothing_selected_writes_empty_payload_without_http(cache_dir, cal):
    cache.save_calendar({"entries": [{"title": "stale"}]})
    assert calendar_sync.run_once(make_cfg(**cal)) is True
    data = cache.load_calendar()
    assert data["entries"] == [] and data["ids"] == []


@respx.mock
def test_list_calendar_sources_accepts_list_or_wrapped():
    cfg = make_cfg()
    rows = [{"id": "a", "name": "Familie"}]
    respx.get(f"{BASE}/api/calendar/sources").respond(json=rows)
    assert registry.list_calendar_sources(cfg) == rows
    respx.get(f"{BASE}/api/calendar/sources").respond(json={"sources": rows, "total": 1})
    assert registry.list_calendar_sources(cfg) == rows


def test_calendar_config_defaults_and_yaml_roundtrip(tmp_path):
    assert Config().calendar.enabled is False and Config().calendar.ids == []
    p = tmp_path / "c.yaml"
    p.write_text("calendar:\n  enabled: true\n  ids: [x]\n  horizon_weeks: 3\n  edge: mirror\n")
    cal = load_config(p).calendar
    assert (cal.enabled, cal.ids, cal.horizon_weeks, cal.edge) == (True, ["x"], 3, "mirror")
    for bad in ("horizon_weeks: 1", "horizon_weeks: 5", "style: neon"):
        p.write_text(f"calendar:\n  {bad}\n")
        with pytest.raises(Exception):
            load_config(p)
