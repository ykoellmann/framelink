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
    weight: float = 0.7      # probability boost for in-season photos
    window_months: int = 2   # ±months around today's month


class FiltersConfig(BaseModel):
    date_range: DateFilterConfig = Field(default_factory=DateFilterConfig)
    excluded_photos: list[str] = Field(default_factory=list)  # iCloud photo GUIDs


class SyncConfig(BaseModel):
    auto: bool = True
    interval_minutes: int | None = None  # None = auto-calculated (120 min)
    cache_dir: Path = Path("/var/lib/framelink/cache")


class GeocodingConfig(BaseModel):
    enabled: bool = True
    user_agent: str = "framelink/0.1"


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
