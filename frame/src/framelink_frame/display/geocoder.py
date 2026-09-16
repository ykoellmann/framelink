"""
Reverse geocoding via Nominatim (OpenStreetMap).
Results are cached on disk — at ~30 photos/day we stay well under the 1 req/s limit.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from ..config import config

log = logging.getLogger(__name__)

_CACHE_FILE = Path("/var/lib/framelink/geocache.json")
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_ROUND = 2          # round coords to ~1km grid for cache hits
_LAST_REQUEST: list[float] = [0.0]  # module-level rate-limit state


def _cache_key(lat: float, lon: float) -> str:
    return f"{round(lat, _ROUND)},{round(lon, _ROUND)}"


def _load_cache() -> dict[str, str]:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text())
    except Exception:
        log.exception("Failed to load geocache")
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception:
        log.exception("Failed to save geocache")


_CACHE: dict[str, str] = {}
_CACHE_LOADED = False


def _ensure_loaded() -> None:
    global _CACHE, _CACHE_LOADED
    if not _CACHE_LOADED:
        _CACHE = _load_cache()
        _CACHE_LOADED = True


def reverse_geocode(lat: float, lon: float) -> str | None:
    """Return a human-readable place name for (lat, lon), or None on failure."""
    if not config.geocoding.enabled:
        return None

    _ensure_loaded()
    key = _cache_key(lat, lon)

    if key in _CACHE:
        return _CACHE[key]

    # Nominatim rate limit: max 1 req/s
    elapsed = time.monotonic() - _LAST_REQUEST[0]
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    try:
        resp = httpx.get(
            _NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 10},
            headers={"User-Agent": config.geocoding.user_agent},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        _LAST_REQUEST[0] = time.monotonic()
    except Exception:
        log.warning("Geocoding failed for %.4f,%.4f", lat, lon)
        return None

    address = data.get("address", {})
    # Build a short place string: "Stadt, Land" or just "Stadt"
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
        or ""
    )
    country = address.get("country_code", "").upper()
    place = ", ".join(filter(None, [city, country])) or data.get("display_name", "")

    _CACHE[key] = place
    _save_cache(_CACHE)
    log.debug("Geocoded (%.4f,%.4f) → %s", lat, lon, place)
    return place or None
