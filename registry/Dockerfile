FROM python:3.12-slim

WORKDIR /app

# 1. Install dependencies separately for layer caching
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.29" \
    "sqlalchemy[asyncio]>=2.0" \
    "alembic>=1.13" \
    "pydantic-settings>=2.2" \
    "aiosqlite>=0.20" \
    "httpx>=0.27" \
    "apscheduler>=3.10" \
    "psycopg[async]>=3.1"

# 2. Copy source and install the package itself
COPY src/ src/
RUN pip install --no-cache-dir -e .

# 3. Copy remaining files (alembic config, etc.)
COPY . .

# Persistent volume for SQLite (unused when DATABASE_URL points to PostgreSQL)
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn framelink_registry.main:app --host 0.0.0.0 --port 8000"]
