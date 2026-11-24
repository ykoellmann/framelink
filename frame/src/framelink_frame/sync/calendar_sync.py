"""
Framelink calendar sync — run by its own systemd timer (or directly for testing).

Fetches the entries of the calendars selected for this frame from the registry
and stores them in calendar.json for the display. It is deliberately separate
from the photo sync: that one aborts when the registry is unreachable or no
albums exist, and can run for minutes.

Usage:
    framelink-calendar          (from installed entry point)
    python -m framelink_frame.sync.calendar_sync
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import Config, config as _startup_config
from .cache import save_calendar
from .registry import fetch_calendar_entries

log = logging.getLogger(__name__)


def today_in(tz_name: str) -> date:
    """Today's date in the configured time zone (the Pi itself usually runs on UTC)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        log.warning("Unknown time zone %r — using UTC", tz_name)
        tz = timezone.utc
    return datetime.now(tz).date()


def window(today: date) -> tuple[date, date]:
    """Monday of last week .. Monday of this week + 8 weeks: ~4 weeks shown plus a buffer for offline days."""
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday + timedelta(days=56)


def run_once(cfg: Config | None = None) -> bool:
    """Refresh calendar.json. Returns True if it changed. Raises httpx.HTTPError if the registry fails."""
    cfg = cfg or _startup_config
    cal = cfg.calendar
    start, end = window(today_in(cal.timezone))

    if not cal.enabled or not cal.ids:
        # Nothing selected: store an empty result so entries of deselected calendars disappear.
        data = {"from": start.isoformat(), "to": end.isoformat(), "tz": cal.timezone,
                "calendars": [], "entries": [], "ids": []}
    else:
        data = fetch_calendar_entries(cfg, cal.ids, start, end)
        data.pop("generated_at", None)   # changes on every call and would force a re-render
        data["ids"] = list(cal.ids)
    return save_calendar(data)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        changed = run_once()
    except Exception:
        log.exception("Calendar sync failed — keeping the previous calendar.json")
        sys.exit(1)
    log.info("Calendar sync done (%s)", "updated" if changed else "unchanged")


if __name__ == "__main__":
    main()
