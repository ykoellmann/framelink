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
- Python 3.11+
- `libsdl2-dev` (pygame without X11)
- `avahi-daemon` (for `frame.local` mDNS)

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/framelink
cd framelink
```

### 2. Deploy the registry

```bash
cd registry
cp .env.example .env
# Edit .env: set FRAMELINK_API_KEY to a random secret
docker compose up -d
```

Expose the registry via a reverse proxy or Cloudflare Tunnel so the frame Pi can reach it at `https://<your-registry-host>`.

Verify:
```bash
curl https://<your-registry-host>/health
# {"status":"ok"}
```

### 3. Set up the frame Pi

```bash
# On the Pi Zero 2W as root:
sudo bash frame/install.sh
```

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
```

### 4. Add albums

See **[docs/sharing-guide.md](docs/sharing-guide.md)** for step-by-step instructions (iOS and Android).

---

## Configuration

Full example: [frame/config.yaml.example](frame/config.yaml.example)

### Registry (`registry/.env`)

| Variable | Default | Description |
|---|---|---|
| `FRAMELINK_API_KEY` | *(required)* | Shared secret for `X-API-Key` header |
| `FRAMELINK_DATABASE_URL` | `sqlite:///./data/framelink.db` | SQLite or PostgreSQL connection string |
| `FRAMELINK_METADATA_REFRESH_INTERVAL_MINUTES` | `60` | How often to refresh album metadata from iCloud |

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
```

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
