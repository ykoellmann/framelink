"""
Background jobs for the Framelink Registry.

refresh_all_albums: runs on a configurable interval, refreshes iCloud metadata
(album name, photo count, owner) for every registered album. One failing album
is logged and skipped — the rest of the batch is unaffected.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from .database import AsyncSessionLocal
from .icloud import fetch_album_metadata
from .models import Album

log = logging.getLogger(__name__)


async def refresh_all_albums() -> None:
    """Fetch fresh metadata from iCloud for every registered album."""
    async with AsyncSessionLocal() as db:
        albums = (await db.scalars(select(Album))).all()

    if not albums:
        log.debug("refresh_all_albums: no albums registered, nothing to do")
        return

    log.info("refresh_all_albums: refreshing %d album(s)", len(albums))
    ok = fail = 0

    for album in albums:
        try:
            meta = await fetch_album_metadata(album.token)
        except Exception:
            log.exception(
                "refresh_all_albums: failed to refresh album %s (token=%s)",
                album.id,
                album.token,
            )
            fail += 1
            continue

        async with AsyncSessionLocal() as db:
            obj = await db.get(Album, album.id)
            if obj is None:
                continue  # deleted in the meantime
            for key, value in meta.items():
                setattr(obj, key, value)
            obj.last_checked = datetime.now(timezone.utc)
            await db.commit()

        ok += 1

    log.info("refresh_all_albums: done — %d updated, %d failed", ok, fail)
