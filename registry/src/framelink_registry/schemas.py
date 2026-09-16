from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class AlbumCreate(BaseModel):
    url: str  # full iCloud shared-album URL


class AlbumRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    token: str
    album_name: str | None
    owner_first: str | None
    owner_last: str | None
    photo_count: int | None
    added_at: datetime
    last_checked: datetime | None
    frame_id: str | None


class AlbumList(BaseModel):
    albums: list[AlbumRead]
    total: int


class AlbumMetadataRefresh(BaseModel):
    """Returned after a manual or scheduled metadata refresh."""
    model_config = {"from_attributes": True}

    id: str
    album_name: str | None
    photo_count: int | None
    last_checked: datetime | None
