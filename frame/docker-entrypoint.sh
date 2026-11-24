#!/bin/sh
# Usage: docker-entrypoint.sh display | webui | sync | <any other command, e.g. framelink-bench --help>
set -e

: "${FRAMELINK_CONFIG:=/config/config.yaml}"
: "${FRAMELINK_IPC_DIR:=/ipc}"
export FRAMELINK_CONFIG FRAMELINK_IPC_DIR

# First start: drop the example config where the user can edit it (never overwrites)
if [ ! -e "$FRAMELINK_CONFIG" ] && [ -d "$(dirname "$FRAMELINK_CONFIG")" ] && [ -w "$(dirname "$FRAMELINK_CONFIG")" ]; then
    cp /usr/share/framelink/config.yaml.example "$FRAMELINK_CONFIG"
    echo "Created $FRAMELINK_CONFIG from the example; set registry.url and registry.api_key" >&2
fi
mkdir -p "$FRAMELINK_IPC_DIR"

case "$1" in
    display) exec framelink-display ;;
    webui)   exec framelink-webui ;;
    sync)    exec framelink-sync-loop ;;
    *)       exec "$@" ;;
esac
