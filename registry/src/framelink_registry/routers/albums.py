from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_api_key
from ..database import get_db
from ..icloud import extract_token, fetch_album_metadata, is_invite_url
from ..models import Album
from ..schemas import AlbumCreate, AlbumList, AlbumMetadataRefresh, AlbumRead

router = APIRouter(
    prefix="/api/albums",
    tags=["albums"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=AlbumRead, status_code=status.HTTP_201_CREATED)
async def add_album(body: AlbumCreate, db: AsyncSession = Depends(get_db)) -> Album:
    """Register a new iCloud shared album by URL."""
    token = extract_token(body.url)
    if not token:
        if is_invite_url(body.url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This looks like an invitation link (share.icloud.com). "
                    "Framelink requires the public-website link instead: "
                    "open the album in iOS Photos → Personen → "
                    "'Öffentliche Website' einschalten → diesen Link verwenden. "
                    "The public link starts with https://www.icloud.com/photos/#A… or #B…"
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Could not extract album token from URL. "
                "Expected a public-website iCloud shared-album link "
                "(https://www.icloud.com/photos/#TOKEN)."
            ),
        )

    # Duplicate check
    if await db.scalar(select(Album).where(Album.token == token)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Album is already registered.",
        )

    # Fetch live metadata from iCloud before persisting
    try:
        meta = await fetch_album_metadata(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"iCloud metadata fetch failed: {exc}",
        ) from exc

    album = Album(token=token, last_checked=datetime.now(timezone.utc), **meta)
    db.add(album)
    await db.commit()
    await db.refresh(album)
    return album


@router.get("", response_model=AlbumList)
async def list_albums(db: AsyncSession = Depends(get_db)) -> AlbumList:
    """Return all registered albums, newest first."""
    rows = (await db.scalars(select(Album).order_by(Album.added_at.desc()))).all()
    return AlbumList(albums=list(rows), total=len(rows))


@router.get("/{album_id}", response_model=AlbumRead)
async def get_album(album_id: str, db: AsyncSession = Depends(get_db)) -> Album:
    album = await db.get(Album, album_id)
    if not album:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found.")
    return album


@router.post("/{album_id}/refresh", response_model=AlbumMetadataRefresh)
async def refresh_album(album_id: str, db: AsyncSession = Depends(get_db)) -> Album:
    """Manually trigger a metadata refresh for one album."""
    album = await db.get(Album, album_id)
    if not album:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found.")

    try:
        meta = await fetch_album_metadata(album.token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"iCloud metadata fetch failed: {exc}",
        ) from exc

    for key, value in meta.items():
        setattr(album, key, value)
    album.last_checked = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(album)
    return album


@router.delete("/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_album(album_id: str, db: AsyncSession = Depends(get_db)) -> None:
    album = await db.get(Album, album_id)
    if not album:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Album not found.")
    await db.delete(album)
    await db.commit()
