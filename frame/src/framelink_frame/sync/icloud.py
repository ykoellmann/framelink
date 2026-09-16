"""
iCloud Shared Album API client for the frame sync service.

Fetches photo metadata (GUIDs, dimensions, dates, GPS) and resolves
download URLs via the webasseturls endpoint.

Protocol: same reverse-engineered API as the registry, but we need
the full photo list + download URLs here, not just the count.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _cluster(token: str) -> str:
    if token.startswith("A"):
        return str(int(token[1], 36)).zfill(2)
    if token.startswith("B"):
        val = _B62.index(token[1]) * 62 + _B62.index(token[2])
        return str(val).zfill(2)
    return "01"


def _base_url(token: str) -> str:
    return f"https://p{_cluster(token)}-sharedstreams.icloud.com/{token}/sharedstreams"


def _post(client: httpx.Client, url: str, body: dict) -> dict:
    """POST with automatic 330-redirect handling."""
    resp = client.post(url, json=body, headers={"Content-Type": "application/json"})
    if resp.status_code == 330:
        new_host = resp.json().get("X-Apple-MMe-Host")
        if not new_host:
            raise ValueError(f"iCloud 330 redirect missing X-Apple-MMe-Host: {resp.text}")
        # Rebuild base from the redirected host; keep the path suffix
        path = "/" + url.split("/", 3)[-1]  # /{token}/sharedstreams/...
        resp = client.post(
            f"https://{new_host}{path}",
            json=body,
            headers={"Content-Type": "application/json"},
        )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PhotoMeta:
    guid: str
    token: str                    # album this photo belongs to
    album_name: str | None
    owner_first: str | None
    owner_last: str | None
    width: int
    height: int
    captured_at: datetime | None
    lat: float | None = None
    lon: float | None = None
    # Checksum of the best-quality derivative, used to look up download URLs
    best_checksum: str | None = None
    # Filled in later by the downloader
    local_path: str | None = None

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height else 1.0

    @property
    def display_owner(self) -> str:
        parts = filter(None, [self.owner_first, self.owner_last])
        return " ".join(parts) or "Unbekannt"

    def to_dict(self) -> dict:
        return {
            "guid": self.guid,
            "token": self.token,
            "album_name": self.album_name,
            "owner_first": self.owner_first,
            "owner_last": self.owner_last,
            "width": self.width,
            "height": self.height,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "lat": self.lat,
            "lon": self.lon,
            "best_checksum": self.best_checksum,
            "local_path": self.local_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PhotoMeta":
        captured_at = None
        if d.get("captured_at"):
            captured_at = datetime.fromisoformat(d["captured_at"])
        return cls(
            guid=d["guid"],
            token=d["token"],
            album_name=d.get("album_name"),
            owner_first=d.get("owner_first"),
            owner_last=d.get("owner_last"),
            width=d["width"],
            height=d["height"],
            captured_at=captured_at,
            lat=d.get("lat"),
            lon=d.get("lon"),
            best_checksum=d.get("best_checksum"),
            local_path=d.get("local_path"),
        )


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    # iCloud returns ISO-8601 strings, sometimes with fractional seconds
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_album_photos(
    token: str,
    album_name: str | None,
    owner_first: str | None,
    owner_last: str | None,
) -> list[PhotoMeta]:
    """
    Return metadata for all photos in one iCloud shared album.
    Does NOT download images — only fetches the webstream metadata.
    """
    base = _base_url(token)
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        data = _post(client, f"{base}/webstream", {"streamCtag": None})

    photos: list[PhotoMeta] = []
    for p in data.get("photos", []):
        # Skip videos — we only display still images
        if p.get("mediaAssetType") == "video":
            continue
        # Pick the largest available derivative for dimensions
        derivatives: dict = p.get("derivatives", {})
        best = _best_derivative(derivatives)
        width = int(best.get("width", 0)) if best else 0
        height = int(best.get("height", 0)) if best else 0
        best_checksum = best.get("checksum") if best else None

        # GPS from EXIF location fields
        lat = lon = None
        loc = p.get("location") or {}
        if loc.get("latitude") is not None:
            lat = float(loc["latitude"])
            lon = float(loc.get("longitude", 0.0))

        photos.append(
            PhotoMeta(
                guid=p["photoGuid"],
                token=token,
                album_name=album_name or p.get("caption"),
                owner_first=owner_first or p.get("contributorFirstName"),
                owner_last=owner_last or p.get("contributorLastName"),
                width=width,
                height=height,
                captured_at=_parse_date(p.get("dateCreated")),
                lat=lat,
                lon=lon,
                best_checksum=best_checksum,
            )
        )

    log.info("Album %s: %d photo(s) fetched", token[:8], len(photos))
    return photos


def _best_derivative(derivatives: dict) -> dict | None:
    """Return the largest (highest resolution) derivative dict."""
    if not derivatives:
        return None
    return max(
        derivatives.values(),
        key=lambda d: int(d.get("width", 0)) * int(d.get("height", 0)),
    )


def resolve_download_urls(token: str, photos: list[PhotoMeta]) -> dict[str, str]:
    """
    Resolve photo GUIDs to direct download URLs via the webasseturls endpoint.

    Sends photo GUIDs to webasseturls, which returns items keyed by derivative
    checksum. Maps each photo's best_checksum back to its GUID.

    Returns {guid: url}.
    """
    if not photos:
        return {}

    guids = [p.guid for p in photos]
    # Build checksum → guid mapping for the lookup
    checksum_to_guid: dict[str, str] = {
        p.best_checksum: p.guid
        for p in photos
        if p.best_checksum
    }

    base = _base_url(token)
    result: dict[str, str] = {}
    for chunk_photos in _chunks(photos, 50):
        chunk_guids = [p.guid for p in chunk_photos]
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            data = _post(client, f"{base}/webasseturls", {"photoGuids": chunk_guids})
        items: dict = data.get("items", {})
        for checksum, item in items.items():
            guid = checksum_to_guid.get(checksum)
            if not guid:
                continue
            url = _build_url(item)
            if url:
                result[guid] = url

    log.debug("Resolved %d/%d download URLs", len(result), len(guids))
    return result


def _build_url(item: dict) -> str | None:
    """Construct download URL from iCloud webasseturls response item."""
    host = item.get("url_location")
    path = item.get("url_path")
    if host and path:
        return f"https://{host}{path}"
    return None


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
