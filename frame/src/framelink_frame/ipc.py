"""Paths of the small files the services use to talk to each other (default /tmp, overridable for containers)."""
import os
from pathlib import Path


def ipc_dir() -> Path:
    return Path(os.environ.get("FRAMELINK_IPC_DIR", "/tmp"))


def cmd_file() -> Path:
    return ipc_dir() / "frame-cmd"


def current_file() -> Path:
    return ipc_dir() / "frame-current"


def sync_trigger_file() -> Path:
    return ipc_dir() / "sync-now"
