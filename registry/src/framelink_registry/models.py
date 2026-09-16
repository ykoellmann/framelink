import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime
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
