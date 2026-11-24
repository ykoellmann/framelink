"""
Frame configuration — loaded from config.yaml (path via FRAMELINK_CONFIG env var,
default: /etc/framelink/config.yaml).

Every field has a sane default so the frame boots with minimal config.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class RegistryConfig(BaseModel):
    url: str = "http://localhost:8000"
    api_key: str = "changeme"
    # database_url lives only on the registry side


class OverlayFieldsConfig(BaseModel):
    album_name: bool = True
    owner: bool = True
    date: bool = True
    location: bool = True


class OverlayConfig(BaseModel):
    enabled: bool = True
    fields: OverlayFieldsConfig = Field(default_factory=OverlayFieldsConfig)
    position: Literal["bottom", "top"] = "bottom"
    opacity: float = 0.6


class TransitionConfig(BaseModel):
    style: Literal["fade", "cut"] = "fade"
    duration_ms: int = 1000


class RotationConfig(BaseModel):
    interval_minutes: float = 30
    order: Literal["random", "chronological", "album_grouped"] = "random"


class LayoutConfig(BaseModel):
    portrait_pairing: bool = True
    portrait_pair_preference: Literal[
        "same_album_same_day", "same_album", "any"
    ] = "same_album_same_day"
    fill_mode: Literal["blurred", "black"] = "blurred"


class ActivePeriod(BaseModel):
    start: str = "08:00"  # HH:MM
    end: str = "22:00"


class ScheduleConfig(BaseModel):
    active_periods: list[ActivePeriod] = Field(
        default_factory=lambda: [ActivePeriod()]
    )


class DateFilterConfig(BaseModel):
    mode: Literal["all", "recent", "seasonal"] = "all"
    recent_years: int | None = None
    seasonal: "SeasonalConfig" = Field(default_factory=lambda: SeasonalConfig())


class SeasonalConfig(BaseModel):
    enabled: bool = False
    weight: float = 0.7       # how much out-of-season photos are down-weighted
    window_months: int = 2    # half-window around today's day-of-year (in months)
    transition_days: int = 5  # soft transition zone at window edges


class FiltersConfig(BaseModel):
    date_range: DateFilterConfig = Field(default_factory=DateFilterConfig)
    excluded_photos: list[str] = Field(default_factory=list)   # iCloud photo GUIDs
    excluded_albums: list[str] = Field(default_factory=list)   # iCloud album tokens


class SyncConfig(BaseModel):
    auto: bool = True
    interval_minutes: int | None = None  # None = auto-calculated (120 min)
    cache_dir: Path = Path("/var/lib/framelink/cache")


class GeocodingConfig(BaseModel):
    enabled: bool = True
    user_agent: str = "framelink/0.1"


class CalendarConfig(BaseModel):
    enabled: bool = False   # False = full-screen photos as before
    ids: list[str] = Field(default_factory=list)   # registry calendar ids shown on this frame (opt-in)
    timezone: str = "Europe/Berlin"   # decides what "today" is; keep equal to the registry's FRAMELINK_TIMEZONE
    style: Literal["dark", "glass", "light"] = "dark"
    horizon_weeks: int = Field(4, ge=2, le=4)   # at most this many weeks; fewer if they do not fit
    multi_line: bool = True
    edge: Literal["hard", "soft", "softer", "mirror"] = "softer"


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class Config(BaseModel):
    registry: RegistryConfig = Field(default_factory=RegistryConfig)
    overlay: OverlayConfig = Field(default_factory=OverlayConfig)
    transition: TransitionConfig = Field(default_factory=TransitionConfig)
    rotation: RotationConfig = Field(default_factory=RotationConfig)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    geocoding: GeocodingConfig = Field(default_factory=GeocodingConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)

    @model_validator(mode="after")
    def compute_sync_interval(self) -> "Config":
        """Set sync interval to 120 min when auto mode is on and no manual value."""
        if self.sync.auto and self.sync.interval_minutes is None:
            self.sync.interval_minutes = 120
        return self


def _period_minutes(p: ActivePeriod) -> int:
    sh, sm = map(int, p.start.split(":"))
    eh, em = map(int, p.end.split(":"))
    return max(0, (eh * 60 + em) - (sh * 60 + sm))


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_PATH = Path("/etc/framelink/config.yaml")


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or Path(os.environ.get("FRAMELINK_CONFIG", str(_DEFAULT_PATH)))
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text()) or {}
    else:
        raw = {}
    return Config.model_validate(raw)


# Module-level singleton — re-load by calling load_config() with an explicit path
config: Config = load_config()
