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
