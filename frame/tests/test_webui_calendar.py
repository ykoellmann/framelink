import threading

import httpx
import pytest
import respx
import yaml

from framelink_frame.webui import main as webui

REG = "http://registry.test"
KEY = "sekret-key-123"
SRC = {"id": "c1", "name": "Familie", "kind": "auto", "color": "#ff0000", "url_host": "p01.icloud.com",
       "added_at": "2026-01-01T00:00:00Z", "last_fetched": None, "last_ok": "2026-11-20T10:00:00Z", "last_error": None}


@pytest.fixture
def client(tmp_path, monkeypatch, cache_dir):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump({"registry": {"url": REG, "api_key": KEY}, "calendar": {"ids": ["c1", "gone"]}}))
    monkeypatch.setattr(webui, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(webui, "_CMD_FILE", tmp_path / "cmd")   # never touch /tmp/frame-cmd
    runs, done = [], threading.Event()

    def fake_run_once(c):
        runs.append(list(c.calendar.ids))
        done.set()
        return False
    monkeypatch.setattr(webui.calendar_sync, "run_once", fake_run_once)
    c = webui.app.test_client()
    c.cfg_path, c.runs, c.synced = cfg, runs, done
    return c


def saved(client):
    return yaml.safe_load(client.cfg_path.read_text())["calendar"]


@respx.mock
def test_get_lists_registry_calendars_with_selection(client):
    respx.get(f"{REG}/api/calendar/sources").respond(json=[SRC])
    d = client.get("/api/calendar").get_json()
    assert d["registry_ok"] is True
    assert d["calendars"][0]["selected"] is True and d["calendars"][0]["url_host"] == "p01.icloud.com"
    assert d["calendar_mtime"] is None
    assert KEY not in client.get("/api/calendar").get_data(as_text=True)


@respx.mock
def test_registry_down_keeps_saved_ids(client):
    respx.get(f"{REG}/api/calendar/sources").mock(side_effect=httpx.ConnectError("boom"))
    d = client.get("/api/calendar").get_json()
    assert d["registry_ok"] is False and d["calendars"] == []
    assert d["config"]["ids"] == ["c1", "gone"] and saved(client)["ids"] == ["c1", "gone"]
    assert KEY not in str(d)


@pytest.mark.parametrize("body", [{"style": "neon"}, {"horizon_weeks": 9}, {"ids": "x"}, [1]])
def test_invalid_body_is_400_and_not_saved(client, body):
    r = client.post("/api/config/calendar", json=body)
    assert r.status_code == 400 and "error" in r.get_json()
    assert saved(client) == {"ids": ["c1", "gone"]}     # file untouched


def test_partial_update_saved_and_sync_only_when_ids_or_enabled_change(client):
    assert client.post("/api/config/calendar", json={"style": "glass"}).get_json()["ok"]
    assert saved(client)["style"] == "glass" and saved(client)["ids"] == ["c1", "gone"]
    assert not client.synced.wait(0.2)                      # style change: no sync
    client.post("/api/config/calendar", json={"ids": ["c1"], "enabled": True})
    assert client.synced.wait(2) and client.runs == [["c1"]]
    assert saved(client)["enabled"] is True


@respx.mock
def test_add_proxy_forwards_key_and_returns_502_on_upstream_error(client):
    route = respx.post(f"{REG}/api/calendar/sources").respond(201, json=SRC)
    r = client.post("/api/calendar/sources", json={"name": "F", "url": "webcal://x/y.ics", "kind": "auto", "evil": 1})
    assert r.status_code == 201 and r.get_json()["id"] == "c1"
    assert route.calls[0].request.headers["X-API-Key"] == KEY
    assert b"evil" not in route.calls[0].request.content

    route.respond(502, json={"detail": "Calendar fetch failed: nope"})
    r = client.post("/api/calendar/sources", json={"name": "F", "url": "webcal://x/y.ics"})
    assert r.status_code == 502 and "nope" in r.get_json()["error"] and KEY not in r.get_data(as_text=True)

    route.mock(side_effect=httpx.ConnectTimeout("slow"))
    assert client.post("/api/calendar/sources", json={"name": "F", "url": "https://x"}).status_code == 502


@respx.mock
def test_delete_removes_id_from_selection(client):
    respx.delete(f"{REG}/api/calendar/sources/c1").respond(204)
    assert client.delete("/api/calendar/sources/c1").get_json() == {"ok": True}
    assert saved(client)["ids"] == ["gone"]
    assert client.synced.wait(2)


@respx.mock
def test_delete_upstream_failure_is_502_and_keeps_selection(client):
    respx.delete(f"{REG}/api/calendar/sources/c1").respond(500)
    assert client.delete("/api/calendar/sources/c1").status_code == 502
    assert saved(client)["ids"] == ["c1", "gone"]


def test_reload_calendar_is_an_allowed_remote_command(client):
    assert client.post("/api/remote/reload-calendar").get_json()["ok"]
    assert client.post("/api/remote/rm-rf").status_code == 400
