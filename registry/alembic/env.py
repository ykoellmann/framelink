"""Alembic async migration environment.

Works with both SQLite (aiosqlite) and PostgreSQL (asyncpg) — the driver
is taken from the app's Settings so no URL needs to be set in alembic.ini.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Import the app's config and metadata so Alembic knows the URL and models
from framelink_registry.config import settings
from framelink_registry.database import Base  # noqa: F401 — registers all models
import framelink_registry.models  # noqa: F401 — ensure models are imported

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live connection)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # needed for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against the live database (default)."""
    connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}
    engine = create_async_engine(settings.database_url, connect_args=connect_args)

    async with engine.connect() as conn:
        await conn.run_sync(
            lambda sync_conn: context.configure(
                connection=sync_conn,
                target_metadata=target_metadata,
                render_as_batch=True,  # needed for SQLite ALTER TABLE support
            )
        )
        async with conn.begin():
            await conn.run_sync(lambda _: context.run_migrations())

    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
