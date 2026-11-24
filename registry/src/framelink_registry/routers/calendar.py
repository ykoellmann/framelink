from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_api_key
from ..calendar_ics import IcsError, classify, fetch_ics, parse_ics, url_host
from ..config import settings
from ..database import get_db
from ..jobs import refresh_all_calendars, refresh_source
from ..models import CalendarSource
from ..schemas import CalendarSourceCreate, CalendarSourceRead, CalendarSourceUpdate



router = APIRouter(
    prefix="/api/calendar",
    tags=["calendar"],
    dependencies=[Depends(require_api_key)],
)

MAX_SPAN_DAYS = 400
# Display order within a day: holidays first, observances last
_KIND_ORDER = {k: i for i, k in enumerate(
    ["holiday", "birthday", "appointment", "observance", "vacation", "school_holiday"])}


def _read(s: CalendarSource) -> CalendarSourceRead:
    return CalendarSourceRead(**{
        **{f: getattr(s, f) for f in (
            "id", "name", "kind", "color", "added_at", "last_fetched", "last_ok", "last_error")},
        "url_host": url_host(s.url),
    })


async def _get_or_404(db: AsyncSession, source_id: str) -> CalendarSource:
    source = await db.get(CalendarSource, source_id)
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Calendar source not found.")
    return source


@router.get("/sources", response_model=list[CalendarSourceRead])
async def list_sources(db: AsyncSession = Depends(get_db)) -> list[CalendarSourceRead]:
    rows = await db.scalars(select(CalendarSource).order_by(CalendarSource.added_at))
    return [_read(s) for s in rows]


@router.post("/sources", response_model=CalendarSourceRead, status_code=status.HTTP_201_CREATED)
async def add_source(body: CalendarSourceCreate, db: AsyncSession = Depends(get_db)) -> CalendarSourceRead:
    if await db.scalar(select(CalendarSource).where(CalendarSource.url == body.url)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Calendar is already registered.")

    # Validate the address by fetching it once before persisting
    tz = ZoneInfo(settings.timezone)
    try:
        entries = parse_ics(
            await fetch_ics(body.url), tz, datetime.now(tz).date(),
            settings.calendar_window_back_days, settings.calendar_window_ahead_days,
        )
    except IcsError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Calendar fetch failed: {exc}") from exc

    now = datetime.now(timezone.utc)
    source = CalendarSource(
        **body.model_dump(), entries=entries, last_fetched=now, last_ok=now
    )
    db.add(source)
    await db.commit()
    return _read(source)


@router.patch("/sources/{source_id}", response_model=CalendarSourceRead)
async def update_source(
    source_id: str, body: CalendarSourceUpdate, db: AsyncSession = Depends(get_db)
) -> CalendarSourceRead:
    source = await _get_or_404(db, source_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key != "color":
            continue  # name/kind are not nullable
        setattr(source, key, value)
    await db.commit()
    return _read(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)) -> None:
    await db.delete(await _get_or_404(db, source_id))
    await db.commit()


@router.post("/sources/{source_id}/refresh", response_model=CalendarSourceRead)
async def refresh_one(source_id: str, db: AsyncSession = Depends(get_db)) -> CalendarSourceRead:
    await _get_or_404(db, source_id)
    try:
        await refresh_source(source_id)
    except IcsError as exc:  # old entries stay, last_error is stored
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Calendar fetch failed: {exc}") from exc
    db.expire_all()
    return _read(await _get_or_404(db, source_id))


@router.post("/refresh")
async def refresh_all() -> dict:
    ok, failed = await refresh_all_calendars()
    return {"updated": ok, "failed": failed}


@router.get("/entries")
async def entries(
    from_: date = Query(alias="from"),
    to: date = Query(),
    ids: str = Query(min_length=1, description="Comma-separated source ids (required)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if to < from_ or (to - from_).days > MAX_SPAN_DAYS:
        raise HTTPException(
            422, f"'to' must be on/after 'from', max {MAX_SPAN_DAYS} days"
        )
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    sources = (await db.scalars(select(CalendarSource).where(CalendarSource.id.in_(wanted)))).all()

    f, t = from_.isoformat(), to.isoformat()
    out = []
    for s in sources:
        for e in s.entries:
            if e["end"] < f or e["start"] > t:
                continue
            out.append({
                "id": f'{s.id}:{e["uid"]}:{e["start"]}', "cal": s.id, "title": e["title"],
                "kind": classify(s.kind, e), "start": e["start"], "end": e["end"],
                "all_day": e["all_day"], "time": e["time"], "end_time": e["end_time"],
                "color": s.color,
            })
    out.sort(key=lambda e: (e["start"], _KIND_ORDER[e["kind"]], e["title"]))

    return {
        "from": f, "to": t, "tz": settings.timezone,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calendars": [
            {"id": s.id, "name": s.name, "kind": s.kind, "color": s.color,
             "last_ok": s.last_ok.isoformat() if s.last_ok else None, "error": s.last_error}
            for s in sources
        ],
        "entries": out,
    }
