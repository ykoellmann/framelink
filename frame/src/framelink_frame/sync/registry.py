"""
HTTP client for the Framelink Registry API.
Fetches the list of registered album tokens so the frame knows what to sync.
"""
from __future__ import annotations

import logging

import httpx

from ..config import config

log = logging.getLogger(__name__)


class RegistryAlbum:
    __slots__ = ("id", "token", "album_name", "owner_first", "owner_last", "photo_count", "frame_id")

    def __init__(self, data: dict) -> None:
        self.id: str = data["id"]
        self.token: str = data["token"]
        self.album_name: str | None = data.get("album_name")
        self.owner_first: str | None = data.get("owner_first")
        self.owner_last: str | None = data.get("owner_last")
        self.photo_count: int | None = data.get("photo_count")
        self.frame_id: str | None = data.get("frame_id")

    @property
    def display_owner(self) -> str:
        parts = filter(None, [self.owner_first, self.owner_last])
        return " ".join(parts) or "Unbekannt"


def fetch_albums() -> list[RegistryAlbum]:
    """
    Return all albums from the registry, filtered to those applicable
    to this frame (frame_id == None or matches FRAMELINK_FRAME_ID env).
    """
    url = f"{config.registry.url.rstrip('/')}/api/albums"
    try:
        resp = httpx.get(
            url,
            headers={"X-API-Key": config.registry.api_key},
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("Registry fetch failed: %s", exc)
        raise

    albums = [RegistryAlbum(a) for a in resp.json().get("albums", [])]
    log.info("Registry returned %d album(s)", len(albums))
    return albums


# The calendar functions take the config explicitly: the web UI re-reads config.yaml
# on every request, so the module-level singleton would be stale there.

def _registry_get(cfg, path: str, **params) -> httpx.Response:
    resp = httpx.get(
        f"{cfg.registry.url.rstrip('/')}{path}",
        headers={"X-API-Key": cfg.registry.api_key},
        params=params or None,
        timeout=15,
    )
    resp.raise_for_status()
    return resp


def list_calendar_sources(cfg) -> list[dict]:
    """All calendars the registry knows (id, name, kind, color, url_host, last_ok, error)."""
    data = _registry_get(cfg, "/api/calendar/sources").json()
    return data if isinstance(data, list) else data.get("sources", [])


def fetch_calendar_entries(cfg, ids: list[str], start, end) -> dict:
    """Entries of the given calendar ids between two dates (inclusive), as the registry returns them."""
    return _registry_get(
        cfg, "/api/calendar/entries",
        **{"from": start.isoformat(), "to": end.isoformat(), "ids": ",".join(ids)},
    ).json()
