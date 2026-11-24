# EXPERIMENTAL: Framelink frame image. Not tested on a Raspberry Pi Zero 2W; whether pygame can
# drive the screen via kmsdrm from inside a container is unverified. See docker-compose.yml.
FROM python:3.12-slim

# libdrm/libgbm: KMS/DRM output; libegl1: needed by SDL's kmsdrm backend; tzdata: for TZ and the calendar time zone
RUN apt-get update \
 && apt-get install -y --no-install-recommends libdrm2 libgbm1 libegl1 tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[display,webui]"

COPY config.yaml.example /usr/share/framelink/config.yaml.example
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# "render" has no fixed gid on the host; compose adds the host's group by name or number
RUN groupadd -f video && groupadd -f render \
 && useradd --create-home --uid 1000 --groups video,render framelink \
 && mkdir -p /config /ipc /var/lib/framelink/cache \
 && chown framelink /config /ipc /var/lib/framelink /var/lib/framelink/cache \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV FRAMELINK_CONFIG=/config/config.yaml \
    FRAMELINK_IPC_DIR=/ipc
USER framelink
WORKDIR /home/framelink
EXPOSE 5000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["display"]
