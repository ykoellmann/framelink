import os
import tempfile

# Must happen before the app is imported: settings/engine are module-level.
_tmp = tempfile.mkdtemp(prefix="framelink-test-")
os.environ["FRAMELINK_DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["FRAMELINK_API_KEY"] = "test-key"
os.environ["FRAMELINK_TIMEZONE"] = "Europe/Berlin"

import httpx  # noqa: E402
import pytest  # noqa: E402

from framelink_registry.database import Base, engine  # noqa: E402
from framelink_registry.main import app  # noqa: E402

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    # No lifespan: no scheduler, no iCloud/ICS access
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS
    ) as c:
        yield c
    await engine.dispose()
