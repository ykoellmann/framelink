import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI

from .auth import require_api_key
from .config import settings
from .database import Base, engine
from .jobs import refresh_all_albums, refresh_all_calendars
from .routers import albums, calendar

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables exist on startup.
    # In production, run `alembic upgrade head` before starting the container.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start background metadata refresh
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        refresh_all_albums,
        trigger=IntervalTrigger(minutes=settings.metadata_refresh_interval_minutes),
        id="refresh_all_albums",
        replace_existing=True,
        # Run once immediately so the DB is fresh on first boot
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        refresh_all_calendars,
        trigger=IntervalTrigger(minutes=settings.calendar_refresh_interval_minutes),
        id="refresh_all_calendars",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
    log.info(
        "Metadata refresh scheduler started (interval: %d min)",
        settings.metadata_refresh_interval_minutes,
    )

    yield

    scheduler.shutdown(wait=False)
    log.info("Metadata refresh scheduler stopped")


app = FastAPI(
    title="Framelink Registry",
    description="Album registry for the Framelink Raspberry Pi photo frame system.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(albums.router)
app.include_router(calendar.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/refresh", tags=["meta"], dependencies=[Depends(require_api_key)])
async def trigger_refresh() -> dict:
    """Manually kick off a full metadata refresh for all albums (fire-and-forget)."""
    asyncio.create_task(refresh_all_albums())
    return {"status": "refresh triggered"}
