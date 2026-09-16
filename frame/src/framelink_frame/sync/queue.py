"""
Display queue builder.

Takes the full pool of photo metadata, applies filters, scores each photo
by a time-decay formula, then samples and produces a list of "slots" where
each slot is either:
  - a single landscape/square photo
  - a portrait pair (two 9:16 photos shown side-by-side as ~16:9)

Portrait pairing priority (configurable):
  same_album_same_day > same_album > any > solo-with-blurred-fill

Score formula (no reset ever needed):
  score = hours_since_last_shown / (1 + view_count)^0.6
  → never-shown photos get score ≈ 1_000_000 (highest priority)
  → as time passes without showing, score naturally rises again
"""
from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timezone, timedelta

from ..config import config, LayoutConfig, FiltersConfig
from .cache import Slot
from .icloud import PhotoMeta

log = logging.getLogger(__name__)

PORTRAIT_THRESHOLD = 1.0   # height/width > this → portrait
DOWNLOAD_INTERVAL_MINUTES = 120.0  # target: keep 2 h of display pre-cached


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def calculate_score(
    view_count: int,
    last_seen_at: datetime | None,
    now: datetime,
) -> float:
    """
    Higher score = more likely to be shown next.
    Never-shown photos have the highest possible score.
    Photos shown long ago rank above recently shown ones.
    """
    if last_seen_at is None:
        hours_since = 1_000_000.0
    else:
        hours_since = max(0.0, (now - last_seen_at).total_seconds() / 3600)
    return hours_since / (1 + view_count) ** 0.6


def needed_cache_size(interval_minutes: float) -> int:
    """
    Number of photos to keep downloaded so that 2 hours of display is
    pre-cached without hitting the network.  Doubled to account for portrait
    pairs (each slot may need 2 photos).
    """
    slots = math.ceil(DOWNLOAD_INTERVAL_MINUTES / max(interval_minutes, 0.01))
    return slots * 2


# ---------------------------------------------------------------------------
# Queue builder
# ---------------------------------------------------------------------------

def build_queue(
    photos: dict[str, PhotoMeta],
    view_history: dict[str, tuple[int, datetime | None]] | None = None,
    max_slots: int | None = None,
) -> list[Slot]:
    """
    Filter, score-sample, pair, and return a display queue.

    photos       — full photo pool {guid: PhotoMeta}
    view_history — {guid: (view_count, last_seen_at)} from DB; None = no history
    max_slots    — cap on number of returned slots; None = no cap
    """
    pool = list(photos.values())
    pool = _apply_filters(pool, config.filters)
    pool = _apply_exclusions(pool, set(config.filters.excluded_photos))

    if not pool:
        log.warning("Queue builder: pool is empty after filters")
        return []

    # Score-based sampling — pick a working set large enough for portrait
    # pairing, then truncate to max_slots after building slots.
    if max_slots is not None and len(pool) > max_slots * 2:
        now = datetime.now(timezone.utc)
        vh = view_history or {}
        weights = []
        for p in pool:
            vc, last_seen = vh.get(p.guid, (0, None))
            weights.append(calculate_score(vc, last_seen, now))

        # Sample max_slots * 2 distinct photos (enough for pairing overhead)
        sample_n = min(max_slots * 2, len(pool))
        pool = _weighted_sample(pool, weights, sample_n)

    slots = _pair_portraits(pool, config.layout)

    order = config.rotation.order
    if order == "random":
        pass  # weighted sampling already provides variety; preserve score order
    elif order == "chronological":
        slots.sort(key=_slot_date(photos))
    # album_grouped: pairs are already grouped by album from _pair_portraits

    if max_slots is not None:
        slots = slots[:max_slots]

    log.info(
        "Queue built: %d slot(s) from %d photo(s) (order=%s)",
        len(slots), len(pool), order,
    )
    return slots


def _weighted_sample(
    population: list[PhotoMeta],
    weights: list[float],
    k: int,
) -> list[PhotoMeta]:
    """
    Weighted sampling without replacement using the Efraimidis-Spirakis
    reservoir algorithm: each item gets key = U^(1/w), pick top-k.
    """
    if k >= len(population):
        return population[:]
    keyed = [
        (random.random() ** (1.0 / max(w, 1e-10)), p)
        for p, w in zip(population, weights)
    ]
    keyed.sort(reverse=True)
    return [p for _, p in keyed[:k]]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _apply_filters(pool: list[PhotoMeta], filters: FiltersConfig) -> list[PhotoMeta]:
    mode = filters.date_range.mode
    if mode == "all":
        return pool

    now = datetime.now(timezone.utc)

    if mode == "recent":
        years = filters.date_range.recent_years or 3
        cutoff = now - timedelta(days=years * 365)
        pool = [p for p in pool if p.captured_at and p.captured_at >= cutoff]

    elif mode == "seasonal":
        sc = filters.date_range.seasonal
        if sc.enabled:
            pool = _seasonal_filter(pool, now, sc.window_months, sc.weight)

    return pool


def _seasonal_filter(
    pool: list[PhotoMeta], now: datetime, window: int, weight: float
) -> list[PhotoMeta]:
    result = []
    for p in pool:
        if not p.captured_at:
            result.append(p)
            continue
        diff = abs(p.captured_at.month - now.month)
        diff = min(diff, 12 - diff)
        in_season = diff <= window
        if in_season or random.random() > weight:
            result.append(p)
    return result


def _apply_exclusions(pool: list[PhotoMeta], excluded: set[str]) -> list[PhotoMeta]:
    if not excluded:
        return pool
    return [p for p in pool if p.guid not in excluded]


# ---------------------------------------------------------------------------
# Portrait pairing
# ---------------------------------------------------------------------------

def _pair_portraits(pool: list[PhotoMeta], layout: LayoutConfig) -> list[Slot]:
    if not layout.portrait_pairing:
        return [_single_slot(p) for p in pool]

    pref = layout.portrait_pair_preference
    portraits = [p for p in pool if _is_portrait(p)]
    landscapes = [p for p in pool if not _is_portrait(p)]

    slots: list[Slot] = []
    used: set[str] = set()

    for photo in portraits:
        if photo.guid in used:
            continue
        partner = _find_partner(photo, portraits, used, pref)
        if partner:
            slots.append({"type": "pair", "guids": [photo.guid, partner.guid]})
            used.add(photo.guid)
            used.add(partner.guid)
        else:
            slots.append(_single_slot(photo))
            used.add(photo.guid)

    for photo in landscapes:
        slots.append(_single_slot(photo))

    return slots


def _find_partner(
    photo: PhotoMeta,
    pool: list[PhotoMeta],
    used: set[str],
    pref: str,
) -> PhotoMeta | None:
    candidates = [p for p in pool if p.guid != photo.guid and p.guid not in used]

    def score(p: PhotoMeta) -> int:
        if pref == "same_album_same_day":
            if p.token == photo.token and _same_day(p, photo):
                return 3
            if p.token == photo.token:
                return 2
            return 1
        elif pref == "same_album":
            return 2 if p.token == photo.token else 1
        return 1  # "any"

    if not candidates:
        return None

    best_score = max(score(p) for p in candidates)
    best = [p for p in candidates if score(p) == best_score]
    return random.choice(best)


def _same_day(a: PhotoMeta, b: PhotoMeta) -> bool:
    if not a.captured_at or not b.captured_at:
        return False
    return a.captured_at.date() == b.captured_at.date()


def _is_portrait(p: PhotoMeta) -> bool:
    return p.height > p.width if p.width else False


def _single_slot(p: PhotoMeta) -> Slot:
    return {"type": "single", "guid": p.guid}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slot_date(photos: dict[str, PhotoMeta]):
    def key(slot: Slot):
        guids = [slot["guid"]] if slot["type"] == "single" else slot["guids"]
        dates = [photos[g].captured_at for g in guids if g in photos and photos[g].captured_at]
        return min(dates) if dates else datetime.min.replace(tzinfo=timezone.utc)
    return key


def active_guids(slots: list[Slot]) -> set[str]:
    result: set[str] = set()
    for slot in slots:
        if slot["type"] == "single":
            result.add(slot["guid"])
        else:
            result.update(slot["guids"])
    return result
