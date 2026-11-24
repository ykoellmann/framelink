"""
Framelink config web UI — mobile-optimized Flask PWA, LAN-only.
Access: http://bilderrahmen.local:5000

Writes config.yaml for persistent settings changes.
Sends IPC commands to the display service via /tmp/frame-cmd.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from flask import Flask, jsonify, render_template, request, send_from_directory
from pydantic import ValidationError

from .. import ipc
from ..config import CalendarConfig, Config, load_config, config as _startup_config
from ..sync import calendar_sync
from ..sync.cache import load_queue, load_metadata, cache_size_mb, images_dir, calendar_path
from ..sync.registry import list_calendar_sources

log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")

_CONFIG_PATH = Path(os.environ.get("FRAMELINK_CONFIG", "/etc/framelink/config.yaml"))
_CMD_FILE = ipc.cmd_file()
_SYNC_SERVICE = "framelink-sync.service"


def _write_cmd(cmd: str) -> None:
    try:
        _CMD_FILE.write_text(cmd)
    except OSError as e:
        log.warning("IPC write failed: %s", e)


def _current_config() -> Config:
    return load_config(_CONFIG_PATH)


def _save_config(cfg: Config) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(yaml.dump(json.loads(cfg.model_dump_json()), allow_unicode=True))
    _write_cmd("reload-config")


# ─── PWA Manifest & Service Worker ───────────────────────────────────────────

@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Framelink",
        "short_name": "Framelink",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#111111",
        "theme_color": "#1a1a2e",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}],
    })


@app.route("/sw.js")
def service_worker():
    return send_from_directory(app.static_folder, "sw.js",
                               mimetype="application/javascript")


# ─── Main page ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── API: System status ───────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    queue = load_queue()
    meta = load_metadata()
    photos = sum(1 for f in images_dir().iterdir() if f.suffix == ".jpg")
    return jsonify({
        "queue_slots": len(queue),
        "cached_photos": photos,
        "cache_size_mb": round(cache_size_mb(), 1),
        "timestamp": datetime.now().isoformat(),
    })


# ─── API: Remote control ──────────────────────────────────────────────────────

@app.route("/api/remote/<cmd>", methods=["POST"])
def api_remote(cmd: str):
    allowed = {"next", "pause", "reload-queue", "reload-calendar"}
    if cmd not in allowed:
        return jsonify({"error": "unknown command"}), 400
    _write_cmd(cmd)
    return jsonify({"ok": True, "cmd": cmd})


_CURRENT_FILE = ipc.current_file()

@app.route("/api/remote/current")
def api_current():
    """Return metadata for the photo currently shown."""
    meta = load_metadata()
    slot = None
    if _CURRENT_FILE.exists():
        try:
            import json as _json
            slot = _json.loads(_CURRENT_FILE.read_text())
        except Exception:
            pass
    if slot is None:
        queue = load_queue()
        slot = queue[0] if queue else None
    if not slot:
        return jsonify(None)
    guids = [slot["guid"]] if slot["type"] == "single" else slot["guids"]
    _skip = {"best_checksum"}
    photos = [
        {k: v for k, v in meta[g].to_dict().items() if k not in _skip}
        for g in guids if g in meta
    ]
    return jsonify({"type": slot["type"], "photos": photos})


@app.route("/api/remote/exclude", methods=["POST"])
def api_exclude():
    body = request.get_json(force=True)
    guid = body.get("guid")
    if not guid:
        return jsonify({"error": "guid required"}), 400
    _write_cmd(f"exclude:{guid}")
    return jsonify({"ok": True})


# ─── API: Albums ─────────────────────────────────────────────────────────────

@app.route("/api/albums")
def api_albums():
    meta = load_metadata()
    cfg = _current_config()
    excluded = set(cfg.filters.excluded_albums)
    by_token: dict[str, dict] = {}
    for photo in meta.values():
        t = photo.token
        if t not in by_token:
            by_token[t] = {
                "token": t,
                "album_name": photo.album_name,
                "owner": photo.display_owner,
                "photo_count": 0,
                "enabled": t not in excluded,
            }
        by_token[t]["photo_count"] += 1
    return jsonify(list(by_token.values()))


# ─── API: Config — Overlay ────────────────────────────────────────────────────

@app.route("/api/config/overlay", methods=["GET", "POST"])
def api_overlay():
    cfg = _current_config()
    if request.method == "GET":
        return jsonify(cfg.overlay.model_dump())
    body = request.get_json(force=True)
    updated = cfg.overlay.model_copy(update=body)
    cfg = cfg.model_copy(update={"overlay": updated})
    _save_config(cfg)
    return jsonify({"ok": True})


# ─── API: Config — Rotation / Transition ─────────────────────────────────────

@app.route("/api/config/display", methods=["GET", "POST"])
def api_display():
    cfg = _current_config()
    if request.method == "GET":
        return jsonify({
            "rotation": cfg.rotation.model_dump(),
            "transition": cfg.transition.model_dump(),
            "layout": cfg.layout.model_dump(),
        })
    body = request.get_json(force=True)
    update = {}
    if "rotation" in body:
        update["rotation"] = cfg.rotation.model_copy(update=body["rotation"])
    if "transition" in body:
        update["transition"] = cfg.transition.model_copy(update=body["transition"])
    if "layout" in body:
        update["layout"] = cfg.layout.model_copy(update=body["layout"])
    cfg = cfg.model_copy(update=update)
    _save_config(cfg)
    return jsonify({"ok": True})


# ─── API: Config — Schedule ───────────────────────────────────────────────────

@app.route("/api/config/schedule", methods=["GET", "POST"])
def api_schedule():
    cfg = _current_config()
    if request.method == "GET":
        return jsonify(cfg.schedule.model_dump())
    body = request.get_json(force=True)
    updated = cfg.schedule.model_copy(update=body)
    cfg = cfg.model_copy(update={"schedule": updated})
    _save_config(cfg)
    return jsonify({"ok": True})


# ─── API: Config — Filters ────────────────────────────────────────────────────

@app.route("/api/config/filters", methods=["GET", "POST"])
def api_filters():
    cfg = _current_config()
    if request.method == "GET":
        return jsonify(cfg.filters.model_dump())
    body = request.get_json(force=True)
    update: dict = {}
    if "excluded_photos" in body:
        update["excluded_photos"] = body["excluded_photos"]
    if "excluded_albums" in body:
        update["excluded_albums"] = body["excluded_albums"]
    if update:
        updated = cfg.filters.model_copy(update=update)
        cfg = cfg.model_copy(update={"filters": updated})
        _save_config(cfg)
    return jsonify({"ok": True})


# ─── API: Calendar ────────────────────────────────────────────────────────────

def _sync_calendar(cfg: Config) -> None:
    try:
        if calendar_sync.run_once(cfg):
            _write_cmd("reload-calendar")
    except Exception:
        log.exception("Calendar sync from web UI failed")


def _start_calendar_sync(cfg: Config) -> None:
    # Own thread: the registry can be slow and the request must not wait for it.
    threading.Thread(target=_sync_calendar, args=(cfg,), daemon=True).start()


def _registry_call(cfg: Config, method: str, path: str, **kw) -> httpx.Response:
    """Call the registry with the frame's key (never returned to the browser); raises httpx.HTTPError."""
    resp = httpx.request(
        method, f"{cfg.registry.url.rstrip('/')}{path}",
        headers={"X-API-Key": cfg.registry.api_key}, timeout=5, **kw,
    )
    resp.raise_for_status()
    return resp


def _upstream_error(exc: httpx.HTTPError):
    detail = "Registry nicht erreichbar"
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            d = exc.response.json().get("detail")
        except Exception:
            d = None
        detail = d if isinstance(d, str) else f"Registry antwortet mit {exc.response.status_code}"
    log.warning("Registry call failed: %s", exc)
    return jsonify({"error": detail}), 502


def _set_calendar(cfg: Config, new: CalendarConfig) -> None:
    old = cfg.calendar
    _save_config(cfg.model_copy(update={"calendar": new}))
    if (old.ids, old.enabled) != (new.ids, new.enabled):
        _start_calendar_sync(cfg.model_copy(update={"calendar": new}))


@app.route("/api/calendar")
def api_calendar():
    cfg = _current_config()
    selected = set(cfg.calendar.ids)
    try:
        calendars = [
            {"id": s["id"], "name": s["name"], "kind": s["kind"], "color": s.get("color"),
             "url_host": s.get("url_host"), "last_ok": s.get("last_ok"),
             "error": s.get("last_error", s.get("error")), "selected": s["id"] in selected}
            for s in list_calendar_sources(cfg)
        ]
        registry_ok = True
    except Exception as e:  # saved ids stay untouched
        log.warning("Registry unreachable: %s", e)
        calendars, registry_ok = [], False
    try:
        mtime = calendar_path().stat().st_mtime
    except OSError:
        mtime = None
    return jsonify({"config": cfg.calendar.model_dump(), "calendars": calendars,
                    "registry_ok": registry_ok, "calendar_mtime": mtime})


@app.route("/api/config/calendar", methods=["POST"])
def api_config_calendar():
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON-Objekt erwartet"}), 400
    cfg = _current_config()
    try:
        new = CalendarConfig.model_validate({**cfg.calendar.model_dump(), **body})
    except ValidationError as e:
        msg = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        return jsonify({"error": msg}), 400
    _set_calendar(cfg, new)
    return jsonify({"ok": True, "config": new.model_dump()})


@app.route("/api/calendar/sources", methods=["POST"])
def api_calendar_add():
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON-Objekt erwartet"}), 400
    payload = {k: body[k] for k in ("name", "url", "kind", "color") if body.get(k)}
    try:
        resp = _registry_call(_current_config(), "POST", "/api/calendar/sources", json=payload)
    except httpx.HTTPError as e:
        return _upstream_error(e)
    return jsonify(resp.json()), 201


@app.route("/api/calendar/sources/<source_id>", methods=["DELETE"])
def api_calendar_delete(source_id: str):
    cfg = _current_config()
    try:
        _registry_call(cfg, "DELETE", f"/api/calendar/sources/{source_id}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:   # already gone: still clean up the local selection
            return _upstream_error(e)
    except httpx.HTTPError as e:
        return _upstream_error(e)
    if source_id in cfg.calendar.ids:
        ids = [i for i in cfg.calendar.ids if i != source_id]
        _set_calendar(cfg, cfg.calendar.model_copy(update={"ids": ids}))
    return jsonify({"ok": True})


# ─── API: Sync ────────────────────────────────────────────────────────────────

@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Trigger a manual sync via systemd (install.sh adds the matching sudoers rule).
    Without systemd (Docker image) the sync loop is asked through a trigger file instead."""
    import shutil
    import subprocess
    if not shutil.which("systemctl"):
        try:
            ipc.sync_trigger_file().touch()
            return jsonify({"ok": True})
        except OSError as e:
            return jsonify({"error": str(e)}), 500
    try:
        subprocess.run(
            ["sudo", "-n", "/bin/systemctl", "start", _SYNC_SERVICE],
            check=True, timeout=5,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # LAN-only: listen only on local interfaces, not 0.0.0.0
    host = os.environ.get("FRAMELINK_WEBUI_HOST", "0.0.0.0")
    port = int(os.environ.get("FRAMELINK_WEBUI_PORT", "5000"))
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
