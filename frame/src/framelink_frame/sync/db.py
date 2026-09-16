"""
SQLite-backed photo metadata and view history store.

DB layout: <cache_dir>/framelink.db
  albums        — registered iCloud albums + last sync timestamp
  photos        — all photo metadata (local_path NULL = not downloaded)
  view_history  — per-guid display counter + last/first seen timestamps
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..config import config
from .icloud import PhotoMeta

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS albums (
    token TEXT PRIMARY KEY,
    album_name TEXT,
    owner_first TEXT,
    owner_last TEXT,
    last_metadata_sync TEXT
);

CREATE TABLE IF NOT EXISTS photos (
    guid TEXT PRIMARY KEY,
    token TEXT NOT NULL REFERENCES albums(token),
    album_name TEXT,
    owner_first TEXT,
    owner_last TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    captured_at TEXT,
    lat REAL,
    lon REAL,
    best_checksum TEXT,
    local_path TEXT,
    metadata_updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS view_history (
    guid TEXT PRIMARY KEY REFERENCES photos(guid),
    view_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT,
    created_at TEXT NOT NULL
);
"""


def _db_path() -> Path:
    d = config.sync.cache_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / "framelink.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    log.debug("DB ready at %s", _db_path())


def upsert_album(
    token: str,
    album_name: str | None,
    owner_first: str | None,
    owner_last: str | None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO albums (token, album_name, owner_first, owner_last)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(token) DO UPDATE SET
                album_name   = excluded.album_name,
                owner_first  = excluded.owner_first,
                owner_last   = excluded.owner_last
            """,
            (token, album_name, owner_first, owner_last),
        )


def upsert_photos(photos: list[PhotoMeta]) -> None:
    """Insert or update photo metadata, preserving any existing local_path."""
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            p.guid, p.token, p.album_name, p.owner_first, p.owner_last,
            p.width, p.height,
            p.captured_at.isoformat() if p.captured_at else None,
            p.lat, p.lon, p.best_checksum,
            p.local_path,  # NULL for freshly fetched photos
            now_iso,
        )
        for p in photos
    ]
    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO photos
                (guid, token, album_name, owner_first, owner_last,
                 width, height, captured_at, lat, lon, best_checksum,
                 local_path, metadata_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guid) DO UPDATE SET
                token               = excluded.token,
                album_name          = excluded.album_name,
                owner_first         = excluded.owner_first,
                owner_last          = excluded.owner_last,
                width               = excluded.width,
                height              = excluded.height,
                captured_at         = excluded.captured_at,
                lat                 = excluded.lat,
                lon                 = excluded.lon,
                best_checksum       = excluded.best_checksum,
                local_path          = COALESCE(photos.local_path, excluded.local_path),
                metadata_updated_at = excluded.metadata_updated_at
            """,
            rows,
        )
    log.debug("Upserted %d photo(s)", len(rows))


def get_all_photos() -> list[PhotoMeta]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM photos").fetchall()
    return [_row_to_photo(r) for r in rows]


def get_cached_photos() -> list[PhotoMeta]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM photos WHERE local_path IS NOT NULL"
        ).fetchall()
    return [_row_to_photo(r) for r in rows]


def set_local_path(guid: str, path: str | None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE photos SET local_path = ? WHERE guid = ?",
            (path, guid),
        )


def record_view(guid: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO view_history (guid, view_count, last_seen_at, created_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(guid) DO UPDATE SET
                view_count   = view_count + 1,
                last_seen_at = excluded.last_seen_at
            """,
            (guid, now_iso, now_iso),
        )


def get_view_history() -> dict[str, tuple[int, datetime | None]]:
    """Returns {guid: (view_count, last_seen_at)}."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT guid, view_count, last_seen_at FROM view_history"
        ).fetchall()
    result: dict[str, tuple[int, datetime | None]] = {}
    for row in rows:
        last = None
        if row["last_seen_at"]:
            try:
                last = datetime.fromisoformat(row["last_seen_at"])
            except ValueError:
                pass
        result[row["guid"]] = (row["view_count"], last)
    return result


def get_albums_needing_sync(older_than_hours: float) -> list[str]:
    """Return album tokens whose metadata is NULL or older than the threshold."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT token FROM albums
            WHERE last_metadata_sync IS NULL
               OR last_metadata_sync < ?
            """,
            (cutoff,),
        ).fetchall()
    return [row["token"] for row in rows]


def mark_album_synced(token: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE albums SET last_metadata_sync = ? WHERE token = ?",
            (datetime.now(timezone.utc).isoformat(), token),
        )


def evict_stale_local_paths(keep_guids: set[str]) -> int:
    """Set local_path = NULL for photos not in keep_guids. Returns count updated."""
    if not keep_guids:
        return 0
    placeholders = ",".join("?" * len(keep_guids))
    with _connect() as conn:
        cur = conn.execute(
            f"""
            UPDATE photos SET local_path = NULL
            WHERE local_path IS NOT NULL
              AND guid NOT IN ({placeholders})
            """,
            list(keep_guids),
        )
    count = cur.rowcount
    if count:
        log.info("Cleared local_path for %d evicted photo(s)", count)
    return count


def _row_to_photo(row: sqlite3.Row) -> PhotoMeta:
    captured_at = None
    if row["captured_at"]:
        try:
            captured_at = datetime.fromisoformat(row["captured_at"])
        except ValueError:
            pass
    return PhotoMeta(
        guid=row["guid"],
        token=row["token"],
        album_name=row["album_name"],
        owner_first=row["owner_first"],
        owner_last=row["owner_last"],
        width=row["width"],
        height=row["height"],
        captured_at=captured_at,
        lat=row["lat"],
        lon=row["lon"],
        best_checksum=row["best_checksum"],
        local_path=row["local_path"],
    )
