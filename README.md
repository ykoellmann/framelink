# Framelink

Raspberry Pi Bilderrahmen für die Familie. Ein Fernseher zeigt automatisch Fotos aus iCloud-Alben aller Familienmitglieder — ohne Apple-Account auf dem Gerät, ohne dauerhaften Cloudflare-Tunnel auf dem Frame-Pi.

```
iPhone (Familie)
    │  iOS Shortcut → Album-URL teilen
    ▼
Homelab Pi 5  ── registry/  (FastAPI + SQLite/PostgreSQL, Docker)
    │  GET /api/albums
    ▼
Frame Pi Zero 2W  ── frame/  (sync + pygame + Flask PWA)
    │
    ▼
HDMI-TV in der Küche
```

---

## Architektur

### Tier 1 — Registry (Homelab Pi 5)

FastAPI-Service in Docker. Speichert iCloud Shared-Album-Tokens und ihre Metadaten (Album-Name, Ersteller, Fotoanzahl). Kein Apple-Login, keine Credentials — nur die öffentlichen Album-URLs.

**Datenbank:** konfigurierbar via `FRAMELINK_DATABASE_URL`:
- `sqlite:///./data/framelink.db` — Standard, zero-Setup
- `postgresql://user:pw@localhost/framelink` — bestehende PostgreSQL-Instanz

### Tier 2 — Frame (Pi Zero 2W)

Vier systemd-Komponenten:

| Service | Was er tut |
|---|---|
| `framelink-sync.timer` | Holt Album-Tokens von der Registry, fetcht Metadaten von iCloud, baut Queue, lädt nur benötigte Bilder |
| `framelink-display` | pygame auf KMS/DRM-Framebuffer (kein X11), Fade-Transitions, Portrait-Pairing, Metadata-Overlay |
| `framelink-webui` | Flask PWA auf Port 5000, im LAN erreichbar als `http://bilderrahmen.local:5000` |
| CEC (cron) | TV per `cec-client` ein-/ausschalten nach Zeitplan |

---

## Voraussetzungen

### Registry (Homelab Pi 5)
- Docker + Docker Compose
- Optional: laufende PostgreSQL-Instanz

### Frame (Pi Zero 2W)
- Raspberry Pi OS Lite (64-bit, Bookworm)
- Python 3.11+
- `libsdl2-dev`, `libsdl2-image-dev` (für pygame ohne X11)
- `cec-utils` (für TV-Steuerung, optional)
- `avahi-daemon` (für `bilderrahmen.local`)

---

## Setup

### 1. Repository klonen

```bash
git clone https://github.com/koellmann/framelink
cd framelink
```

### 2. Registry deployen (Homelab Pi)

```bash
cd registry
cp .env.example .env
# .env editieren: FRAMELINK_API_KEY setzen
# Optional: FRAMELINK_DATABASE_URL auf PostgreSQL zeigen

docker compose up -d
```

Prüfen:
```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Cloudflare Tunnel (oder eigenes Reverse Proxy) auf Port 8000 einrichten,
sodass der Frame-Pi die Registry unter `https://bilderrahmen-api.koellmann.dev` erreicht.

### 3. Frame-Pi einrichten

Das Setup-Skript erledigt alles:

```bash
# Auf dem Pi Zero 2W als root:
curl -sSf https://raw.githubusercontent.com/koellmann/framelink/main/frame/install.sh | bash

# Oder lokal (nach git clone):
sudo bash frame/install.sh
```

Was das Skript macht: siehe [frame/install.sh](frame/install.sh).

Nach dem Setup `config.yaml` befüllen:

```bash
sudo nano /etc/framelink/config.yaml
```

Dann Services starten:

```bash
sudo systemctl enable --now framelink-display framelink-webui framelink-sync.timer
```

### 4. iOS Shortcut einrichten

1. Shortcut erstellen: **URL aus Share Sheet empfangen → HTTP-POST**
   - URL: `https://bilderrahmen-api.koellmann.dev/api/albums`
   - Header: `X-API-Key: <dein-key>`
   - Body (JSON): `{"url": "<Shortcut Input>"}`
2. Shortcut per iMessage an alle Familienmitglieder teilen

### 5. Erstes Album hinzufügen

> **Wichtig:** Es gibt zwei verschiedene Sharing-Modi in iCloud. Framelink benötigt den
> **"Öffentliche Website"**-Link, nicht den normalen Einladungslink.

| Link-Typ | URL-Format | Framelink-kompatibel? |
|---|---|---|
| Öffentliche Website | `www.icloud.com/photos/#A…` oder `#B…` | **Ja** |
| Einladungslink (Share-Button) | `share.icloud.com/photos/…` | Nein — erfordert Apple-ID-Login |

**Schritt für Schritt:**
1. iOS Fotos-App → geteiltes Album öffnen
2. Oben rechts auf **Personen** tippen
3. Ganz unten: **"Öffentliche Website"** → einschalten
4. Unter "Öffentliche Website" auf **"Link teilen"** tippen
5. Diesen `www.icloud.com/photos/#...`-Link an den Framelink-Shortcut weitergeben

Der Frame holt sich beim nächsten Sync-Intervall automatisch die Bilder.

---

## Konfiguration

### Registry

Umgebungsvariablen (`.env` oder `docker-compose.yml`):

| Variable | Default | Beschreibung |
|---|---|---|
| `FRAMELINK_API_KEY` | *(Pflicht)* | Shared Secret für `X-API-Key` Header |
| `FRAMELINK_DATABASE_URL` | `sqlite:///./data/framelink.db` | SQLite oder PostgreSQL |
| `FRAMELINK_METADATA_REFRESH_INTERVAL_MINUTES` | `60` | Wie oft Metadaten von iCloud neu geladen werden |

### Frame

`/etc/framelink/config.yaml` — vollständiges Beispiel in [frame/config.yaml.example](frame/config.yaml.example).

Wichtigste Felder:

```yaml
registry:
  url: "https://bilderrahmen-api.koellmann.dev"
  api_key: "dein-key"

rotation:
  interval_minutes: 30   # Wie lange ein Bild/Paar sichtbar bleibt

schedule:
  active_periods:
    - start: "08:00"
      end: "22:00"

sync:
  max_cached_photos: 200
```

---

## Web-UI

Erreichbar im LAN: `http://bilderrahmen.local:5000`

Auf dem iPhone als App installieren: Safari → Teilen → "Zum Home-Bildschirm".

| Tab | Funktion |
|---|---|
| Remote | Nächstes Foto, Pause, aktuelles Foto dauerhaft ausblenden |
| Anzeige | Overlay-Felder, Wechselintervall, Übergang |
| Alben | Übersicht aller registrierten Alben |
| Zeitplan | Aktive Zeiten (TV-Steuerung per CEC) |
| System | Cache-Status, manueller Sync |

---

## IPC — Display ↔ Sync ↔ Web-UI

Alle drei Prozesse kommunizieren über `/tmp/frame-cmd` (atomare Textdatei):

| Kommando | Bedeutung |
|---|---|
| `reload-queue` | Queue neu laden (nach Sync) |
| `next` | Sofort nächsten Slot zeigen |
| `pause` | Pause umschalten |
| `exclude:<guid>` | Foto dauerhaft aus Queue entfernen |

---

## iCloud API

Framelink nutzt die öffentliche iCloud Shared Album API (reverse-engineered, kein offizieller Apple-Support):

1. Token aus URL extrahieren (`#`-Fragment)
2. Cluster-ID aus Token-Präfix ableiten
3. `POST https://p{cluster}-sharedstreams.icloud.com/{token}/sharedstreams/webstream`
4. Bei HTTP 330: Redirect auf neuen Host, erneut POST
5. Download-URLs per `POST .../webasseturls`

Kein Apple-Account, kein Login, kein 2FA.

---

## Entwicklung

```bash
# Registry lokal starten
cd registry
python -m venv .venv && source .venv/bin/activate
pip install -e ".[postgres]"
FRAMELINK_API_KEY=dev uvicorn framelink_registry.main:app --reload
# → http://localhost:8000/docs

# Frame-Sync lokal testen (braucht laufende Registry)
cd frame
python -m venv .venv && source .venv/bin/activate
pip install -e ".[webui]"
FRAMELINK_CONFIG=frame/config.yaml.example framelink-sync

# Web-UI lokal
FRAMELINK_CONFIG=frame/config.yaml.example framelink-webui
# → http://localhost:5000
```

### Datenbank-Migrationen

```bash
cd registry
# Neue Migration generieren (nach Model-Änderungen):
alembic revision --autogenerate -m "beschreibung"
# Migrieren:
alembic upgrade head
```

---

## Hardware

| Teil | Bezugsquelle | Preis ca. |
|---|---|---|
| Raspberry Pi Zero 2 W | raspberrypi.com | 20 € |
| MicroSD 16 GB (A1) | – | 8 € |
| USB-C Netzteil 3A | – | 10 € |
| Mini-HDMI → HDMI Adapter | – | 3 € |
| **Gesamt** | | **~41 €** |

---

## Bekannte Einschränkungen

- Die iCloud Shared Album API ist nicht offiziell dokumentiert und kann sich ohne Vorwarnung ändern.
- `cec-utils` funktioniert nur, wenn der TV CEC unterstützt und aktiviert hat.
- pygame auf KMS/DRM (ohne X11) muss auf dem Pi Zero 2 W validiert werden — Fallback: `fbi` mit vorgerenderten Bildern.
- Nominatim (Reverse-Geocoding) hat ein Rate-Limit von 1 req/s; bei vielen neuen Fotos auf einmal dauert die erste Sync etwas länger.
