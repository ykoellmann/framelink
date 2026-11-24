"""
ICS fetching, parsing and classification for calendar sources.

Raw entries are stored per source (see CalendarSource.entries); `classify` runs
at query time so changing a source's kind needs no re-fetch.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events as rie

log = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
MAX_ENTRIES = 2000
FETCH_TIMEOUT = 15.0

KINDS = ("auto", "appointment", "birthday", "holiday", "observance", "vacation", "school_holiday")
SPAN_KINDS = ("vacation", "school_holiday")


class IcsError(Exception):
    """Fetching or parsing a calendar failed (message is safe to show to users)."""


def normalize_url(url: str) -> str:
    """webcal(s):// -> https://; only http(s) is allowed."""
    url = url.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in ("webcal", "webcals"):
        url = "https://" + url[len(parts.scheme) + 3 :]
    elif scheme not in ("http", "https"):
        raise ValueError("URL must start with http://, https:// or webcal://")
    if not urlsplit(url).hostname:
        raise ValueError("URL has no host")
    return url


def url_host(url: str) -> str:
    return urlsplit(url).hostname or ""


async def fetch_ics(url: str) -> bytes:
    """Download an ICS file (max 5 MB). Raises IcsError."""
    try:
        url = normalize_url(url)
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=FETCH_TIMEOUT, headers={"User-Agent": "framelink-registry"}
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                if int(resp.headers.get("content-length") or 0) > MAX_BYTES:
                    raise IcsError("calendar file is larger than 5 MB")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        raise IcsError("calendar file is larger than 5 MB")
                return bytes(buf)
    except IcsError:
        raise
    except httpx.HTTPStatusError as exc:
        raise IcsError(f"HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise IcsError(f"fetch failed: {exc}") from exc


# Emoji, pictographs, variation selectors, ZWJ, keycaps, tag chars — the bundled fonts lack them.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U000E0020-\U000E007F←-⇿⌀-⏿①-⓿"
    "■-➿⤀-⥿⬀-⯿〰〽㊗㊙︀-️‍⃣]"
)


def clean_title(title: str) -> str:
    return " ".join(_EMOJI.sub("", title).split())


def _occurrences(cal: icalendar.Calendar, start: date, end: date) -> list:
    try:
        return list(rie.of(cal, keep_recurrence_attributes=True, skip_bad_series=True).between(start, end))
    except Exception:
        log.warning("ICS: whole-calendar expansion failed, retrying per UID", exc_info=True)
    # Fallback: one mini-calendar per UID so a single broken series cannot sink the rest.
    zones = cal.walk("VTIMEZONE")
    groups: dict[str, list] = {}
    for n, ev in enumerate(cal.walk("VEVENT")):
        groups.setdefault(str(ev.get("UID") or n), []).append(ev)
    out: list = []
    for evs in groups.values():
        mini = icalendar.Calendar()
        for comp in (*zones, *evs):
            mini.add_component(comp)
        try:
            out.extend(rie.of(mini, keep_recurrence_attributes=True, skip_bad_series=True).between(start, end))
        except Exception:
            log.warning("ICS: skipping broken event %s", evs[0].get("UID"), exc_info=True)
    return out


def _normalize(ev, tz: ZoneInfo) -> dict | None:
    if str(ev.get("STATUS", "")).upper() == "CANCELLED":
        return None
    start, end = ev.start, ev.end
    rrule = ev.get("RRULE")
    yearly = bool(rrule) and "YEARLY" in [str(f).upper() for f in rrule.get("FREQ", [])]
    title = clean_title(str(ev.get("SUMMARY", ""))) or "(ohne Titel)"
    base = {"uid": str(ev.get("UID", "")), "title": title, "yearly": yearly}

    if not isinstance(start, datetime):  # all-day: DTEND is exclusive
        last = max(end - timedelta(days=1), start)
        return {**base, "start": start.isoformat(), "end": last.isoformat(),
                "all_day": True, "time": None, "end_time": None}

    # Floating times count as local; timed events only show on their start day.
    start = start.astimezone(tz) if start.tzinfo else start.replace(tzinfo=tz)
    end = end.astimezone(tz) if end.tzinfo else end.replace(tzinfo=tz)
    return {**base, "start": start.date().isoformat(), "end": start.date().isoformat(),
            "all_day": False, "time": start.strftime("%H:%M"),
            "end_time": end.strftime("%H:%M") if end != start else None}


def parse_ics(
    data: bytes, tz: ZoneInfo, today: date, back_days: int = 14, ahead_days: int = 90
) -> list[dict]:
    """Parse ICS bytes into raw entries overlapping [today-back, today+ahead]. Raises IcsError."""
    try:
        cal = icalendar.Calendar.from_ical(data)
    except Exception as exc:
        raise IcsError(f"not a valid ICS file: {exc}") from exc

    win_start, win_end = today - timedelta(days=back_days), today + timedelta(days=ahead_days)
    entries = []
    for ev in _occurrences(cal, win_start, win_end + timedelta(days=1)):
        try:
            entry = _normalize(ev, tz)
        except Exception:
            log.warning("ICS: skipping unreadable event %s", ev.get("UID"), exc_info=True)
            continue
        if entry and entry["end"] >= win_start.isoformat() and entry["start"] <= win_end.isoformat():
            entries.append(entry)
    entries.sort(key=lambda e: (e["start"], e["title"], e["uid"]))
    return entries[:MAX_ENTRIES]


def classify(source_kind: str, entry: dict) -> str:
    if source_kind != "auto":
        return source_kind
    if entry["all_day"] and entry["end"] > entry["start"]:
        return "vacation"
    if entry["yearly"] or "geburtstag" in entry["title"].lower():
        return "birthday"
    return "appointment"
