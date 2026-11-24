from __future__ import annotations
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .calendar_ics import normalize_url


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


SourceKind = Literal[
    "auto", "appointment", "birthday", "holiday", "observance", "vacation", "school_holiday"
]
HexColor = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class CalendarSourceCreate(BaseModel):
    name: str = Field(min_length=1)
    url: str
    kind: SourceKind = "auto"
    color: str | None = HexColor

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return normalize_url(v)


class CalendarSourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1)
    kind: SourceKind | None = None
    color: str | None = HexColor


class CalendarSourceRead(BaseModel):
    """Never includes the URL — only its host."""
    id: str
    name: str
    kind: SourceKind
    color: str | None
    url_host: str
    added_at: datetime
    last_fetched: datetime | None
    last_ok: datetime | None
    last_error: str | None
