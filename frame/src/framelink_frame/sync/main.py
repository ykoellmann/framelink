"""
Framelink sync service — run by a systemd timer (or directly for testing).

Flow:
  1. Fetch album list from the registry
  2. Upsert albums into local DB
  3. Refresh metadata from iCloud for stale albums (>24 h since last sync)
  4. Build display queue using time-decay score-based selection
  5. Download images for queue slots not yet cached
  6. Evict stale images from disk
  7. Write queue.json for the display service
  8. Signal display service to reload queue

Usage:
    framelink-sync          (from installed entry point)
    python -m framelink_frame.sync.main
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import httpx

from ..config import config
from . import db
from .cache import image_path, is_downloaded, save_queue, evict_stale_images, cache_size_mb
from .icloud import fetch_album_photos, resolve_download_urls
from .queue import build_queue, active_guids, needed_cache_size
from .registry import fetch_albums

log = logging.getLogger(__name__)

_CMD_FILE = Path("/tmp/frame-cmd")


def _send_cmd(cmd: str) -> None:
    try:
        _CMD_FILE.write_text(cmd)
    except OSError as e:
        log.warning("Could not write IPC command %r: %s", cmd, e)


def _download_photo(guid: str, url: str) -> bool:
    """Download one photo to the local image cache. Returns True on success."""
    dest = image_path(guid)
    try:
        with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    fh.write(chunk)
        return True
    except Exception:
        log.exception("Download failed for guid=%s", guid)
        if dest.exists():
            dest.unlink()
        return False


def run_sync() -> None:
    start = time.monotonic()
    log.info("=== Sync started ===")

    db.init_db()

    # ------------------------------------------------------------------ 1+2
    # Fetch albums from registry, upsert into DB
    # ------------------------------------------------------------------
    try:
        albums = fetch_albums()
    except Exception:
        log.exception("Could not reach registry — aborting sync")
        sys.exit(1)

    if not albums:
        log.info("No albums registered — nothing to sync")
        return

    for album in albums:
        db.upsert_album(
            album.token, album.album_name, album.owner_first, album.owner_last
        )

    # ------------------------------------------------------------------ 3
    # Refresh metadata from iCloud for albums not synced in the last 24 h
    # ------------------------------------------------------------------
    stale_tokens = db.get_albums_needing_sync(older_than_hours=24.0)
    log.info("%d album(s) need metadata refresh", len(stale_tokens))

    albums_by_token = {a.token: a for a in albums}
    for token in stale_tokens:
        album = albums_by_token.get(token)
        if not album:
            continue
        try:
            photos = fetch_album_photos(
                token=album.token,
                album_name=album.album_name,
                owner_first=album.owner_first,
                owner_last=album.owner_last,
            )
            db.upsert_photos(photos)
            db.mark_album_synced(token)
            log.info("Metadata refreshed: album %s (%d photos)", token[:8], len(photos))
        except Exception:
            log.exception("Failed to refresh metadata for album %s — skipping", token[:8])

    # ------------------------------------------------------------------ 4
    # Build display queue using score-based selection
    # ------------------------------------------------------------------
    cache_size = needed_cache_size(config.rotation.interval_minutes)
    max_slots  = max(1, cache_size // 2)

    all_photos = {p.guid: p for p in db.get_all_photos()}
    history    = db.get_view_history()

    log.info(
        "Selecting up to %d slot(s) (%d photos) from pool of %d",
        max_slots, cache_size, len(all_photos),
    )

    slots = build_queue(all_photos, view_history=history, max_slots=max_slots)
    needed = active_guids(slots)

    # ------------------------------------------------------------------ 5
    # Download missing images
    # ------------------------------------------------------------------
    missing = [g for g in needed if not is_downloaded(g)]
    log.info(
        "Queue needs %d photo(s); %d cached, %d to download",
        len(needed), len(needed) - len(missing), len(missing),
    )

    if missing:
        by_token: dict[str, list[str]] = {}
        for guid in missing:
            p = all_photos.get(guid)
            if p:
                by_token.setdefault(p.token, []).append(guid)

        download_ok = download_fail = 0
        for token, guids in by_token.items():
            try:
                token_photos = [all_photos[g] for g in guids if g in all_photos]
                urls = resolve_download_urls(token, token_photos)
            except Exception:
                log.exception("Could not resolve download URLs for token %s", token[:8])
                continue

            for guid in guids:
                url = urls.get(guid)
                if not url:
                    log.warning("No download URL for guid=%s", guid)
                    continue
                if _download_photo(guid, url):
                    db.set_local_path(guid, str(image_path(guid)))
                    download_ok += 1
                else:
                    download_fail += 1

        log.info("Downloads: %d ok, %d failed", download_ok, download_fail)

    # ------------------------------------------------------------------ 6
    # Evict images and DB local_path entries no longer in the queue
    # ------------------------------------------------------------------
    evict_stale_images(needed)
    db.evict_stale_local_paths(needed)

    # ------------------------------------------------------------------ 7+8
    # Write queue, signal display service
    # ------------------------------------------------------------------
    save_queue(slots)

    elapsed = time.monotonic() - start
    log.info(
        "=== Sync done in %.1fs — %d slot(s), %.1f MB cached ===",
        elapsed, len(slots), cache_size_mb(),
    )

    _send_cmd("reload-queue")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_sync()


if __name__ == "__main__":
    main()
