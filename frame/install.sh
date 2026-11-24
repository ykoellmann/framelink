#!/usr/bin/env bash
# Framelink frame installer — run as root on a Raspberry Pi Zero 2W
# Raspberry Pi OS Lite 64-bit (Bookworm) recommended
#
# Install or update from the latest GitHub release (no clone needed):
#   curl -fsSL https://github.com/ykoellmann/framelink/releases/latest/download/install.sh | sudo bash
#   curl -fsSL …/install.sh | sudo FRAMELINK_VERSION=v0.2.0 bash     # a specific version
# Later updates: sudo framelink-update [vX.Y.Z]
#
# From a clone (developers):
#   sudo bash frame/install.sh
#   sudo bash frame/install.sh --no-cec        # skip cec-utils
#   sudo bash frame/install.sh --no-systemd    # do not touch systemd (container tests)
#   sudo bash frame/install.sh --dev           # install into the clone's own folder (no /opt)
#
# Environment: FRAMELINK_VERSION (default "latest"), FRAMELINK_RELEASE_BASE (default the
# GitHub releases URL; a file:// URL works for offline tests).

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/framelink"
CONFIG_DIR="/etc/framelink"
DATA_DIR="/var/lib/framelink/cache"
VENV="$INSTALL_DIR/venv"
SERVICE_USER="framelink"
RELEASE_BASE="${FRAMELINK_RELEASE_BASE:-https://github.com/ykoellmann/framelink/releases}"
VERSION="${FRAMELINK_VERSION:-latest}"
# Empty when the script is piped from curl: it then has no files next to it and downloads the release first.
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

ARGS=("$@")
OPT_NO_CEC=0
OPT_NO_SYSTEMD=0
OPT_DEV=0
for arg in "$@"; do
  case $arg in
    --no-cec)     OPT_NO_CEC=1 ;;
    --no-systemd) OPT_NO_SYSTEMD=1 ;;
    --dev)        OPT_DEV=1; INSTALL_DIR="$SCRIPT_DIR"; VENV="$SCRIPT_DIR/.venv" ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo -e "\033[1;34m[framelink]\033[0m $*"; }
success() { echo -e "\033[1;32m[framelink]\033[0m $*"; }
warn()    { echo -e "\033[1;33m[framelink]\033[0m $*"; }
die()     { echo -e "\033[1;31m[framelink] ERROR:\033[0m $*" >&2; exit 1; }

require_root() {
  [[ $EUID -eq 0 ]] || die "Run as root: sudo bash install.sh"
}

# Run a systemctl command unless --no-systemd was given
sctl() { [[ $OPT_NO_SYSTEMD -eq 1 ]] || systemctl "$@"; }

# ── Preflight ─────────────────────────────────────────────────────────────────
require_root

# ── Standalone start (curl | bash, or a lone install.sh): fetch the release, run its install.sh ──
# Everything below this block needs the files that ship in the release archive (wheel, systemd units, config example).
if [[ -z "$SCRIPT_DIR" || ! -d "$SCRIPT_DIR/systemd" ]]; then
  command -v curl >/dev/null 2>&1 || {
    apt-get update -qq && apt-get install -y --no-install-recommends curl ca-certificates
  }
  if [[ "$VERSION" == "latest" ]]; then
    URL="$RELEASE_BASE/latest/download/framelink-frame.tar.gz"
  else
    URL="$RELEASE_BASE/download/$VERSION/framelink-frame.tar.gz"
  fi
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  info "Downloading $URL"
  curl -fsSL "$URL" -o "$WORK/framelink-frame.tar.gz" || die "Download failed: $URL"
  tar -xzf "$WORK/framelink-frame.tar.gz" -C "$WORK"
  [[ -f "$WORK/framelink-frame/install.sh" ]] || die "Release archive has an unexpected layout"
  # stdin from /dev/null: this script itself may be coming in on stdin (curl | bash)
  bash "$WORK/framelink-frame/install.sh" ${ARGS[@]+"${ARGS[@]}"} </dev/null
  exit $?
fi

# Release mode = a built wheel sits next to this script (the release archive); otherwise we are in a clone.
shopt -s nullglob
WHEELS=("$SCRIPT_DIR"/framelink_frame-*.whl)
shopt -u nullglob
FROM_RELEASE=0
[[ ${#WHEELS[@]} -gt 0 && $OPT_DEV -eq 0 ]] && FROM_RELEASE=1

# An existing installation is updated in place: config is kept, services are restarted at the end.
UPDATING=0
[[ -x "$VENV/bin/framelink-display" ]] && UPDATING=1

info "Framelink frame installer starting"
info "Install dir : $INSTALL_DIR"
info "Config dir  : $CONFIG_DIR"
info "Data dir    : $DATA_DIR"

# Detect architecture
ARCH=$(uname -m)
[[ "$ARCH" == "aarch64" || "$ARCH" == "armv7l" || "$OPT_DEV" -eq 1 ]] \
  || warn "Unexpected arch: $ARCH — continuing anyway"

# ── System packages ───────────────────────────────────────────────────────────
info "Installing system packages…"
apt-get update -qq

PKGS=(
  python3 python3-venv python3-pip
  # SDL2 for pygame without X11 (KMS/DRM backend)
  libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev
  # Image processing
  libjpeg-dev libpng-dev
  # mDNS (bilderrahmen.local)
  avahi-daemon
  # Network
  curl
  # The web UI's "sync now" button starts the sync via sudo (rule installed below)
  sudo
)

if [[ $OPT_NO_CEC -eq 0 ]]; then
  PKGS+=(cec-utils)
fi

apt-get install -y --no-install-recommends "${PKGS[@]}"
success "System packages installed"

# ── Service user ──────────────────────────────────────────────────────────────
if ! id "$SERVICE_USER" &>/dev/null; then
  info "Creating user $SERVICE_USER…"
  useradd --system --no-create-home --shell /usr/sbin/nologin \
    --groups video,audio "$SERVICE_USER"
  success "User $SERVICE_USER created"
else
  info "User $SERVICE_USER already exists"
  # Ensure video group membership
  usermod -aG video "$SERVICE_USER" 2>/dev/null || true
fi

# ── Directories ───────────────────────────────────────────────────────────────
info "Creating directories…"
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$DATA_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

# ── Python venv + package ─────────────────────────────────────────────────────
info "Creating Python venv at $VENV…"
python3 -m venv "$VENV"

info "Installing framelink-frame…"
"$VENV/bin/pip" install --quiet --upgrade pip
if [[ $FROM_RELEASE -eq 1 ]]; then
  info "From release wheel ${WHEELS[0]##*/}"
  "$VENV/bin/pip" install --quiet --upgrade "${WHEELS[0]}[display,webui]"
else
  "$VENV/bin/pip" install --quiet -e "$SCRIPT_DIR[display,webui]"
fi
success "Python package installed"

# ── Config file ───────────────────────────────────────────────────────────────
CONFIG_FILE="$CONFIG_DIR/config.yaml"
if [[ ! -f "$CONFIG_FILE" ]]; then
  info "Installing default config to $CONFIG_FILE…"
  cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_FILE"
  warn "Edit $CONFIG_FILE before starting services:"
  warn "  registry.url     — URL your registry is reachable at"
  warn "  registry.api_key — matching FRAMELINK_API_KEY from the registry"
else
  info "Config already exists at $CONFIG_FILE — not overwriting"
fi
# The web UI runs as $SERVICE_USER and saves settings here, so the group needs write access.
# Applied on every run so existing installs (which had 640) are fixed too.
chmod 660 "$CONFIG_FILE"
chown root:"$SERVICE_USER" "$CONFIG_FILE"

# ── Env file (API key passthrough) ────────────────────────────────────────────
ENV_FILE="$CONFIG_DIR/env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'EOF'
# Environment for framelink systemd services
FRAMELINK_CONFIG=/etc/framelink/config.yaml
# Override the web UI port if needed:
# FRAMELINK_WEBUI_PORT=5000
EOF
  chmod 640 "$ENV_FILE"
  chown root:"$SERVICE_USER" "$ENV_FILE"
fi

# ── systemd units ─────────────────────────────────────────────────────────────
info "Installing systemd units…"
UNIT_DIR="/etc/systemd/system"
UNITS=(framelink-sync.service framelink-sync.timer framelink-calendar.service framelink-calendar.timer framelink-display.service framelink-webui.service)

for unit in "${UNITS[@]}"; do
  src="$SCRIPT_DIR/systemd/$unit"
  dst="$UNIT_DIR/$unit"
  if [[ ! -f "$src" ]]; then
    warn "Unit file not found: $src — skipping"
    continue
  fi
  # Patch ExecStart to point at the installed venv
  sed "s|/opt/framelink/venv|$VENV|g" "$src" > "$dst"
  chmod 644 "$dst"
done

sctl daemon-reload
success "systemd units installed"

# ── avahi hostname ────────────────────────────────────────────────────────────
HOSTNAME_FILE="/etc/hostname"
CURRENT_HOST=$(cat "$HOSTNAME_FILE" 2>/dev/null || echo "")
if [[ "$CURRENT_HOST" != "bilderrahmen" ]]; then
  info "Setting hostname to 'bilderrahmen' (→ bilderrahmen.local on mDNS)…"
  echo "bilderrahmen" > "$HOSTNAME_FILE"
  hostnamectl set-hostname bilderrahmen 2>/dev/null || true
  # Update /etc/hosts
  sed -i "s/127\.0\.1\.1.*/127.0.1.1\tbilderrahmen/" /etc/hosts 2>/dev/null || true
fi
sctl enable --now avahi-daemon 2>/dev/null || true

# ── CEC helper scripts ────────────────────────────────────────────────────────
if [[ $OPT_NO_CEC -eq 0 ]] && command -v cec-client &>/dev/null; then
  info "Installing CEC helper scripts…"
  cat > /usr/local/bin/framelink-tv-on <<'EOF'
#!/bin/bash
echo "on 0" | cec-client -s -d 1
EOF
  cat > /usr/local/bin/framelink-tv-off <<'EOF'
#!/bin/bash
echo "standby 0" | cec-client -s -d 1
EOF
  chmod +x /usr/local/bin/framelink-tv-on /usr/local/bin/framelink-tv-off
  success "CEC helpers installed: framelink-tv-on / framelink-tv-off"
  info "Add to crontab (crontab -e) to auto-control TV:"
  info "  0 8  * * * /usr/local/bin/framelink-tv-on"
  info "  0 22 * * * /usr/local/bin/framelink-tv-off"
fi

# ── Sudoers for web UI sync trigger ──────────────────────────────────────────
SUDOERS_FILE="/etc/sudoers.d/framelink"
if [[ ! -f "$SUDOERS_FILE" ]]; then
  mkdir -p /etc/sudoers.d
  echo "$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl start framelink-sync.service" \
    > "$SUDOERS_FILE"
  chmod 440 "$SUDOERS_FILE"
  info "Sudoers rule added: $SERVICE_USER can start framelink-sync"
fi

# ── Update command (release installs only) ───────────────────────────────────
if [[ $FROM_RELEASE -eq 1 ]]; then
  cat > /usr/local/bin/framelink-update <<EOF
#!/usr/bin/env bash
# Update Framelink to the latest release, or to a given one: framelink-update [vX.Y.Z]
set -euo pipefail
[[ \$EUID -eq 0 ]] || exec sudo -E "\$0" "\$@"
BASE="\${FRAMELINK_RELEASE_BASE:-$RELEASE_BASE}"
VERSION="\${1:-\${FRAMELINK_VERSION:-latest}}"
if [[ "\$VERSION" == latest ]]; then URL="\$BASE/latest/download/install.sh"; else URL="\$BASE/download/\$VERSION/install.sh"; fi
curl -fsSL "\$URL" | FRAMELINK_VERSION="\$VERSION" FRAMELINK_RELEASE_BASE="\$BASE" bash
EOF
  chmod +x /usr/local/bin/framelink-update
  info "Update later with: sudo framelink-update"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
if [[ $UPDATING -eq 1 ]]; then
  # Running services pick up the new code; the calendar timer is new for installs that predate it.
  sctl try-restart framelink-display framelink-webui 2>/dev/null || true
  if systemctl is-enabled --quiet framelink-sync.timer 2>/dev/null && [[ $OPT_NO_SYSTEMD -eq 0 ]]; then
    systemctl enable --now framelink-calendar.timer 2>/dev/null || true
  fi
  success "Update complete (config kept)."
else
  success "Installation complete."
  echo
  echo "  Next steps:"
  echo "  1. Edit config:   sudo nano $CONFIG_FILE"
  echo "  2. Start services:"
  echo "     sudo systemctl enable --now framelink-display framelink-webui framelink-sync.timer framelink-calendar.timer"
  echo "  3. Check logs:    journalctl -u framelink-display -f"
  echo "  4. Web UI:        http://bilderrahmen.local:5000"
fi
echo
if [[ "$CURRENT_HOST" != "bilderrahmen" ]]; then
  warn "Hostname changed — reboot recommended: sudo reboot"
fi
