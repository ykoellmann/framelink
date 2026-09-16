"""
Local disk cache helpers for the frame sync service.

Layout on disk:
    <cache_dir>/
        framelink.db           — SQLite: photo metadata, albums, view history
        queue.json             — current display queue (list of slots)
        images/
            <guid>.jpg         — downloaded photos

queue.json is written by the sync service and read by the display service.
Photo metadata lives in framelink.db (see db.py).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import config
from .icloud import PhotoMeta

log = logging.getLogger(__name__)

_QUEUE_FILE = "queue.json"
_IMAGES_DIR = "images"

# A slot is either {"type": "single", "guid": "..."} or
# {"type": "pair", "guids": ["...", "..."]} (portrait pair)
Slot = dict


def _cache_dir() -> Path:
    d = config.sync.cache_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def images_dir() -> Path:
    d = _cache_dir() / _IMAGES_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def image_path(guid: str) -> Path:
    return images_dir() / f"{guid}.jpg"


def is_downloaded(guid: str) -> bool:
    return image_path(guid).exists()


def cache_size_mb() -> float:
    total = sum(f.stat().st_size for f in images_dir().iterdir() if f.is_file())
    return total / 1_048_576


# ---------------------------------------------------------------------------
# Queue store (written by sync service, read by display service)
# ---------------------------------------------------------------------------

def load_queue() -> list[Slot]:
    path = _cache_dir() / _QUEUE_FILE
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        log.exception("Failed to load queue — display will get empty queue")
        return []


def save_queue(slots: list[Slot]) -> None:
    path = _cache_dir() / _QUEUE_FILE
    path.write_text(json.dumps(slots, indent=2))
    log.info("Queue saved: %d slot(s)", len(slots))


# ---------------------------------------------------------------------------
# Image management
# ---------------------------------------------------------------------------

def evict_stale_images(active_guids: set[str]) -> int:
    """Delete image files not in active_guids. Returns number of files removed."""
    removed = 0
    for f in images_dir().iterdir():
        if f.suffix == ".jpg" and f.stem not in active_guids:
            f.unlink()
            log.debug("Evicted stale image: %s", f.name)
            removed += 1
    if removed:
        log.info("Evicted %d stale image(s) from cache", removed)
    return removed


# ---------------------------------------------------------------------------
# Metadata shim — kept for overlay.py compatibility
# ---------------------------------------------------------------------------

def load_metadata() -> dict[str, PhotoMeta]:
    """Load all photo metadata from SQLite. Returns {guid: PhotoMeta}."""
    try:
        from . import db
        db.init_db()
        return {p.guid: p for p in db.get_all_photos()}
    except Exception:
        log.exception("Failed to load metadata from DB")
        return {}
