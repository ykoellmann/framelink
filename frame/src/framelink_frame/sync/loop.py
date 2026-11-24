"""
Framelink sync loop — replaces the systemd timers in the Docker image.

Runs the photo sync every sync.interval_minutes and the calendar sync every 30 minutes. Dropping a
`sync-now` file into the IPC folder (web UI "sync" button) runs both at once. A failing sync is logged
and the loop carries on.

Usage:
    framelink-sync-loop
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from .. import ipc

log = logging.getLogger(__name__)

CALENDAR_INTERVAL_S = 30 * 60
POLL_S = 5


def _safe(name: str, fn) -> None:
    try:
        fn()
    except (Exception, SystemExit):   # run_sync() calls sys.exit(1) when the registry is unreachable
        log.exception("%s failed — will retry at the next interval", name)


def run_loop(photo_sync, calendar_sync, photo_interval_s: float, stop: threading.Event,
             calendar_interval_s: float = CALENDAR_INTERVAL_S, clock=time.monotonic) -> None:
    trigger = ipc.sync_trigger_file()
    next_photo = next_calendar = clock()   # both run right away
    while not stop.is_set():
        now = clock()
        triggered = trigger.exists()
        if triggered:
            trigger.unlink(missing_ok=True)
            log.info("sync-now requested")
        if triggered or now >= next_calendar:
            _safe("Calendar sync", calendar_sync)
            next_calendar = clock() + calendar_interval_s
        if triggered or now >= next_photo:
            _safe("Photo sync", photo_sync)
            next_photo = clock() + photo_interval_s
        stop.wait(POLL_S)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from ..config import config
    from .calendar_sync import run_once
    from .main import run_sync

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())   # a running sync finishes first
    minutes = config.sync.interval_minutes or 120
    log.info("Sync loop started: photos every %s min, calendar every %d min",
             minutes, CALENDAR_INTERVAL_S // 60)
    run_loop(run_sync, run_once, minutes * 60, stop)


if __name__ == "__main__":
    main()
