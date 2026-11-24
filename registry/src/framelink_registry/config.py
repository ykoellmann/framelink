import re
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FRAMELINK_",
        case_sensitive=False,
    )

    # Database — accepts plain sqlite:/// or postgresql:// and upgrades to the
    # async driver automatically so callers don't have to know the driver name.
    database_url: str = "sqlite+aiosqlite:///./data/framelink.db"

    # Shared secret sent by clients in the X-API-Key header
    api_key: str = "changeme"

    # How often the background job refreshes album metadata from iCloud (minutes)
    metadata_refresh_interval_minutes: int = 60

    # Calendar sidebar: timezone for timed events / "today", refresh cadence,
    # and the window (days before/after today) that gets stored per source.
    timezone: str = "Europe/Berlin"
    calendar_refresh_interval_minutes: int = 30
    calendar_window_back_days: int = 14
    calendar_window_ahead_days: int = 90

    def model_post_init(self, __context) -> None:  # noqa: ANN001
        url = self.database_url
        if url.startswith("sqlite:///") and "+aiosqlite" not in url:
            object.__setattr__(
                self, "database_url", url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
            )
        elif re.match(r"^postgresql(\+\w+)?://", url) and "asyncpg" not in url and "psycopg" not in url:
            object.__setattr__(
                self, "database_url", re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", url)
            )


settings = Settings()
