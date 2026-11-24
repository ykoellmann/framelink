"""
Background jobs for the Framelink Registry.

refresh_all_albums: runs on a configurable interval, refreshes iCloud metadata
(album name, photo count, owner) for every registered album. One failing album
is logged and skipped — the rest of the batch is unaffected.
"""
from __future__ import annotations
import logging
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .calendar_ics import IcsError, fetch_ics, parse_ics
from .config import settings
from .database import AsyncSessionLocal
from .icloud import fetch_album_metadata
from .models import Album, CalendarSource

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


async def refresh_source(source_id: str) -> None:
    """Fetch and re-parse one calendar source. On failure the old entries are kept,
    last_error is set and IcsError is re-raised."""
    async with AsyncSessionLocal() as db:
        source = await db.get(CalendarSource, source_id)
        if source is None:
            return
        url = source.url

    now = datetime.now(timezone.utc)
    try:
        data = await fetch_ics(url)
        tz = ZoneInfo(settings.timezone)
        # Parsing is CPU-bound; keep it off the event loop.
        entries = await asyncio.to_thread(
            parse_ics,
            data,
            tz,
            datetime.now(tz).date(),
            settings.calendar_window_back_days,
            settings.calendar_window_ahead_days,
        )
        error = None
    except Exception as exc:  # keep old entries, remember why
        log.warning("calendar source %s failed: %s", source_id, exc)
        entries, error = None, str(exc) or type(exc).__name__

    async with AsyncSessionLocal() as db:
        obj = await db.get(CalendarSource, source_id)
        if obj is None:
            return  # deleted in the meantime
        obj.last_fetched = now
        if error is None:
            obj.entries, obj.last_ok, obj.last_error = entries, now, None
        else:
            obj.last_error = error
        await db.commit()
    if error is not None:
        raise IcsError(error)


async def refresh_all_calendars() -> tuple[int, int]:
    """Refresh every calendar source; one failure never stops the rest. Returns (ok, failed)."""
    async with AsyncSessionLocal() as db:
        ids = (await db.scalars(select(CalendarSource.id))).all()

    ok = fail = 0
    for source_id in ids:
        try:
            await refresh_source(source_id)
            ok += 1
        except Exception:
            log.exception("refresh_all_calendars: failed to refresh source %s", source_id)
            fail += 1
    log.info("refresh_all_calendars: done — %d updated, %d failed", ok, fail)
    return ok, fail
