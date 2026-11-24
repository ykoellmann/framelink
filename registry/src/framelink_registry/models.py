import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Token extracted from the iCloud shared-album URL (everything after #)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    # Metadata fetched from iCloud
    album_name: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_first: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_last: Mapped[str | None] = mapped_column(String, nullable=True)
    photo_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optional: restrict album to a specific frame (NULL = visible on all frames)
    frame_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)


class CalendarSource(Base):
    __tablename__ = "calendar_sources"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Normalized https:// URL — a secret for public iCloud calendars, never returned by the API
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # auto | appointment | birthday | holiday | observance | vacation | school_holiday
    kind: Mapped[str] = mapped_column(String, nullable=False, default="auto")
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    # Raw parsed entries; classified at query time
    entries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
