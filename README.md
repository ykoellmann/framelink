# Framelink

A self-hosted Raspberry Pi photo frame that pulls from iCloud Shared Albums — no Apple account on the device, no persistent cloud tunnel on the frame, no proprietary apps.

```
iPhone (family)
    │  share iCloud album → iOS Shortcut → Registry API
    ▼
Homelab server  ── registry/  (FastAPI + SQLite, Docker)
    │  GET /api/albums
    ▼
Pi Zero 2W  ── frame/  (sync + pygame display + Flask web UI)
    │
    ▼
HDMI TV / monitor
```

---

## How it works

Family members create iCloud Shared Albums, enable the **Public Website** option (no Apple ID required to view), and share the link via a one-tap iOS Shortcut. The registry stores album tokens; the frame Pi fetches photo metadata directly from iCloud, downloads only the photos it needs for the current rotation window, and displays them with fade transitions and a metadata overlay.

Key design choices:
- **No Apple credentials on the Pi** — uses public iCloud shared album URLs only
- **Stateless anti-repetition** — SQLite view history + time-decay scoring, no resets needed
- **Portrait pairing** — two portrait photos shown side-by-side as a ~16:9 composition
- **Seasonal weighting** — photos from the same time of year are shown more often, with soft 5-day transitions at month boundaries

---

## Architecture

### Tier 1 — Registry (home server)

FastAPI service in Docker. Stores iCloud Shared Album tokens and their metadata (album name, owner, photo count). No Apple login — just HTTP requests with the public album token.

**Database:** configurable via `FRAMELINK_DATABASE_URL`:
- `sqlite:///./data/framelink.db` — default, zero setup
- `postgresql://user:pw@localhost/framelink` — existing PostgreSQL instance

### Tier 2 — Frame (Pi Zero 2W)

Four systemd components:

| Service | What it does |
|---|---|
| `framelink-sync.timer` | Fetches album tokens from the registry, syncs photo metadata from iCloud, builds the display queue, downloads only needed images |
| `framelink-display` | pygame on KMS/DRM framebuffer (no X11), fade transitions, portrait pairing, metadata overlay |
| `framelink-webui` | Flask PWA on port 5000, LAN-accessible at `http://frame.local:5000` |

---

## Requirements

### Registry (home server)
- Docker + Docker Compose

### Frame (Pi Zero 2W)
- Raspberry Pi OS Lite 64-bit (Bookworm)
- Everything else (Python, SDL2, avahi for `frame.local`) is installed by the installer

---

## Setup

### 1. Deploy the registry (Docker)

The registry runs from a ready-made image, `ghcr.io/ykoellmann/framelink-registry` (amd64 and arm64). You only need the Compose file and a `.env`, no clone:

```bash
mkdir framelink-registry && cd framelink-registry
curl -fsSLO https://raw.githubusercontent.com/ykoellmann/framelink/main/registry/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/ykoellmann/framelink/main/registry/.env.example -o .env
# Edit .env: set FRAMELINK_API_KEY to a random secret (openssl rand -hex 32)
docker compose up -d
```

- Pin a version with `FRAMELINK_REGISTRY_TAG=1.2.3` in `.env` (default `latest`).
- Update: `docker compose pull && docker compose up -d` (database migrations run at start).
- Build from source instead (in a clone): `cd registry && docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`.

Expose the registry via a reverse proxy or Cloudflare Tunnel so the frame Pi can reach it at `https://<your-registry-host>`.

Verify:
```bash
curl https://<your-registry-host>/health
# {"status":"ok"}
```

### 2. Set up the frame Pi

On the Pi Zero 2W, one command installs the latest release (user, Python environment, systemd services, config template):

```bash
curl -fsSL https://github.com/ykoellmann/framelink/releases/latest/download/install.sh | sudo bash
```

- Prefer to read the script first? `curl -fsSLO https://github.com/ykoellmann/framelink/releases/latest/download/install.sh`, look at it, then `sudo bash install.sh`.
- A specific version: `curl -fsSL …/install.sh | sudo FRAMELINK_VERSION=v1.2.3 bash`.
- Update later: `sudo framelink-update` (or `sudo framelink-update v1.2.3`). The config is kept, running services restart.
- From a clone (developers): `sudo bash frame/install.sh`.

Edit the config:
```bash
sudo nano /etc/framelink/config.yaml
```

Minimal config:
```yaml
registry:
  url: "https://<your-registry-host>"
  api_key: "your-secret-key"
```

Start services:
```bash
sudo systemctl enable --now framelink-display framelink-webui framelink-sync.timer
# optional, for the calendar sidebar (see docs/calendar.md):
sudo systemctl enable --now framelink-calendar.timer
```

### 3. Add albums

See **[docs/sharing-guide.md](docs/sharing-guide.md)** for step-by-step instructions (iOS and Android).

---

## Frame as a Docker image (experimental)

For hardware other than a Pi Zero 2W there is an image, `ghcr.io/ykoellmann/framelink-frame` (amd64 and arm64), with a Compose file that runs three services from it: `display`, `webui` and `sync` (the sync service replaces the systemd timers).

**Not recommended for the Pi Zero 2W, and not tested on a real screen.** The image builds and the services start. Whether pygame can drive a display with `SDL_VIDEODRIVER=kmsdrm` from inside a container is unverified. The supported way to run the frame is the native install above.

```bash
mkdir framelink-frame && cd framelink-frame
curl -fsSLO https://raw.githubusercontent.com/ykoellmann/framelink/main/frame/docker-compose.yml
mkdir config && chown 1000 config      # the containers run as uid 1000; the web UI saves config.yaml here
docker compose up -d                   # the first start copies an example config.yaml into ./config
# edit config/config.yaml: registry.url and registry.api_key
```

- Pin a version with `FRAMELINK_FRAME_TAG=v1.2.3`; update with `docker compose pull && docker compose up -d`.
- Build from source (in a clone, `frame/`): `docker compose -f docker-compose.yml -f docker-compose.build.yml up --build`.
- The `display` service needs `/dev/dri` and the host's `video` and `render` groups; if it cannot open the device, put the numeric group ids into the Compose file (`ls -ln /dev/dri`).
- In the container the screen is not switched off outside the active hours (a black picture is shown) and the CEC helper scripts are not available.

---

## Configuration

Full example: [frame/config.yaml.example](frame/config.yaml.example)

### Registry (`registry/.env`)

| Variable | Default | Description |
|---|---|---|
| `FRAMELINK_API_KEY` | *(required)* | Shared secret for `X-API-Key` header |
| `FRAMELINK_DATABASE_URL` | `sqlite:///./data/framelink.db` | SQLite or PostgreSQL connection string |
| `FRAMELINK_METADATA_REFRESH_INTERVAL_MINUTES` | `60` | How often to refresh album metadata from iCloud |
| `FRAMELINK_TIMEZONE` | `Europe/Berlin` | Timezone for calendar events and "today"; should match the frames |
| `FRAMELINK_CALENDAR_REFRESH_INTERVAL_MINUTES` | `30` | How often calendar (ICS) sources are re-fetched |
| `FRAMELINK_CALENDAR_WINDOW_BACK_DAYS` | `14` | Days before today kept per calendar |
| `FRAMELINK_CALENDAR_WINDOW_AHEAD_DAYS` | `90` | Days after today kept per calendar |

### Frame (`/etc/framelink/config.yaml`)

```yaml
rotation:
  interval_minutes: 30   # how long each photo/pair is shown

schedule:
  active_periods:
    - start: "08:00"
      end: "22:00"       # screen turns off outside this window

filters:
  date_range:
    mode: seasonal       # all | recent | seasonal
    seasonal:
      enabled: true
      weight: 0.7        # out-of-season photos shown at 30% probability
      window_months: 2   # ±2 months around today's day-of-year
      transition_days: 5 # soft transition at window edges

overlay:
  enabled: true
  position: bottom       # bottom | top
  fields:
    album_name: true
    owner: true
    date: true

calendar:                # sidebar with a date header and a 2-4 week timeline, see docs/calendar.md
  enabled: false         # false = full-screen photos as before
  ids: []                # registry calendar ids shown on this frame (choose them in the web UI)
  timezone: Europe/Berlin   # must match the registry's FRAMELINK_TIMEZONE
  style: dark            # dark | glass | light
  horizon_weeks: 4       # 2-4; fewer weeks are shown automatically if they do not fit
  multi_line: true       # up to 2 lines per day instead of 1 line + "+n"
  edge: softer           # photo edge toward free space: hard | soft | softer | mirror
```

The calendar is off by default; existing frames look exactly as before until it is enabled.
The timer `framelink-calendar.timer` runs `framelink-calendar` 45 s after boot and then every 30 min.

---

## Web UI

LAN access: `http://frame.local:5000`

Install as an app on iPhone/Android: browser → Share → "Add to Home Screen".

| Tab | Function |
|---|---|
| Remote | Next photo, pause, permanently hide current photo |
| Display | Overlay fields, rotation interval, transition style |
| Albums | Enable/disable individual albums |
| Schedule | Active time periods |
| Calendar | Switch the sidebar on/off, choose calendars, style and weeks, add or delete calendars |
| System | Cache status, manual sync trigger |

---

## IPC — Display ↔ Sync ↔ Web UI

All three processes communicate via `/tmp/frame-cmd` (atomic text file):

| Command | Meaning |
|---|---|
| `reload-queue` | Reload queue from disk (after sync) |
| `reload-config` | Reload config.yaml (propagates immediately to display) |
| `next` | Skip to next slot immediately |
| `pause` | Toggle pause |
| `exclude:<guid>` | Permanently hide a photo |
| `reload-calendar` | Re-read `calendar.json` and redraw |

---

## Calendar sidebar

A 25 % wide sidebar next to the photos with the big date and a timeline of the next 2-4 weeks. Calendars are public ICS/webcal feeds; the registry fetches and parses them, the frame only downloads a small JSON. Setup, supported calendar types and time zone: **[docs/calendar.md](docs/calendar.md)**.

### Upgrading an existing installation

1. **Registry first:** `docker compose pull && docker compose up -d`; the migration `0002` runs at start. Old frames keep working.
2. **Then each frame:** `sudo framelink-update` (an installation that predates this command: run the one-line installer from *Setup* again). It installs the calendar timer and enables it when the photo sync timer is enabled; display and web UI restart.
3. Add and select calendars in the web UI (tab *Calendar*) and switch the sidebar on.

Rollback: set `calendar.enabled: false` (frame) or `alembic downgrade 0001` (registry).

---

## iCloud Shared Album API

Framelink uses the public iCloud Shared Album API (reverse-engineered, no official Apple support):

1. Extract token from URL fragment (`#…`)
2. Derive cluster ID from token prefix
3. `POST https://p{cluster}-sharedstreams.icloud.com/{token}/sharedstreams/webstream`
4. On HTTP 330: follow redirect, retry POST
5. Download URLs via `POST …/webasseturls`

No Apple account, no login, no 2FA.

> **Note:** Apple strips GPS coordinates from Shared Album photos before distribution. Location metadata is not available.

---

## Development

Releases, the CI workflows and the GHCR images: **[docs/releasing.md](docs/releasing.md)**.

```bash
# Registry
cd registry && python -m venv .venv && source .venv/bin/activate
pip install -e ".[postgres]"
FRAMELINK_API_KEY=dev uvicorn framelink_registry.main:app --reload
# → http://localhost:8000/docs

# Frame display (windowed, resizable)
cd frame && source .venv/bin/activate
FRAMELINK_CONFIG=config.yaml.example FRAMELINK_WINDOWED=1 python -m framelink_frame.display.main

# Web UI
FRAMELINK_CONFIG=config.yaml.example python -m framelink_frame.webui.main
```

---

## Hardware

| Part | Approx. cost |
|---|---|
| Raspberry Pi Zero 2W | €20 |
| MicroSD 16 GB (A1) | €8 |
| USB-C power supply 3A | €10 |
| Mini-HDMI → HDMI adapter | €3 |
| **Total** | **~€41** |

---

## Known limitations

- The iCloud Shared Album API is not officially documented and may change without notice.
- pygame on KMS/DRM (without X11) needs validation on Pi Zero 2W — fallback: `fbi` with pre-rendered images.
- GPS/location data is stripped by Apple when photos are added to Shared Albums and cannot be recovered.

---

## License

MIT
