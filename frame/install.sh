#!/usr/bin/env bash
# Framelink frame installer — run as root on a Raspberry Pi Zero 2W
# Raspberry Pi OS Lite 64-bit (Bookworm) recommended
#
# Usage:
#   sudo bash install.sh
#   sudo bash install.sh --no-cec        # skip cec-utils
#   sudo bash install.sh --dev           # install into current directory (no /opt)

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/framelink"
CONFIG_DIR="/etc/framelink"
DATA_DIR="/var/lib/framelink/cache"
VENV="$INSTALL_DIR/venv"
SERVICE_USER="framelink"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OPT_NO_CEC=0
OPT_DEV=0
for arg in "$@"; do
  case $arg in
    --no-cec) OPT_NO_CEC=1 ;;
    --dev)    OPT_DEV=1; INSTALL_DIR="$SCRIPT_DIR"; VENV="$SCRIPT_DIR/.venv" ;;
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

# ── Preflight ─────────────────────────────────────────────────────────────────
require_root

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
"$VENV/bin/pip" install --quiet -e "$SCRIPT_DIR[display,webui]"
success "Python package installed"

# ── Config file ───────────────────────────────────────────────────────────────
CONFIG_FILE="$CONFIG_DIR/config.yaml"
if [[ ! -f "$CONFIG_FILE" ]]; then
  info "Installing default config to $CONFIG_FILE…"
  cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_FILE"
  chmod 640 "$CONFIG_FILE"
  chown root:"$SERVICE_USER" "$CONFIG_FILE"
  warn "Edit $CONFIG_FILE before starting services:"
  warn "  registry.url     — URL your registry is reachable at"
  warn "  registry.api_key — matching FRAMELINK_API_KEY from the registry"
else
  info "Config already exists at $CONFIG_FILE — not overwriting"
fi

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
UNITS=(framelink-sync.service framelink-sync.timer framelink-display.service framelink-webui.service)

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

systemctl daemon-reload
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
systemctl enable --now avahi-daemon 2>/dev/null || true

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
  echo "$SERVICE_USER ALL=(root) NOPASSWD: /bin/systemctl start framelink-sync.service" \
    > "$SUDOERS_FILE"
  chmod 440 "$SUDOERS_FILE"
  info "Sudoers rule added: $SERVICE_USER can start framelink-sync"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
success "Installation complete."
echo
echo "  Next steps:"
echo "  1. Edit config:   sudo nano $CONFIG_FILE"
echo "  2. Start services:"
echo "     sudo systemctl enable --now framelink-display framelink-webui framelink-sync.timer"
echo "  3. Check logs:    journalctl -u framelink-display -f"
echo "  4. Web UI:        http://bilderrahmen.local:5000"
echo
if [[ "$CURRENT_HOST" != "bilderrahmen" ]]; then
  warn "Hostname changed — reboot recommended: sudo reboot"
fi
