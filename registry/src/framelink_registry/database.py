from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# SQLite needs check_same_thread=False; PostgreSQL doesn't know/want that arg
_connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}

engine = create_async_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # FastAPI dependency
    async with AsyncSessionLocal() as session:
        yield session
