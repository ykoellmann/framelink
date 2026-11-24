FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/ykoellmann/framelink" \
      org.opencontainers.image.description="Framelink registry: album and calendar API for the photo frames"

WORKDIR /app

# Non-root user. /app/data is created and chowned *before* VOLUME so that a new
# named volume inherits the ownership (Docker copies the image folder's rights).
RUN useradd --system --uid 1000 --home-dir /app framelink \
    && mkdir -p /app/data \
    && chown framelink:framelink /app/data

# Install the package (not editable) with its dependencies from pyproject.toml.
# The source is needed for the build, so this layer is rebuilt on code changes.
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir ".[postgres]"

# Alembic reads alembic.ini and alembic/ from the working directory.
COPY alembic.ini ./
COPY alembic/ alembic/

USER framelink
VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["sh", "-c", "alembic upgrade head && uvicorn framelink_registry.main:app --host 0.0.0.0 --port 8000"]
