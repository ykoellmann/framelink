"""
Framelink display service — runs as a systemd service on the Pi Zero 2W.

Reads queue.json, shows photos with fade/cut transitions, draws metadata
overlay, and polls /tmp/frame-cmd for IPC commands from the sync service
and web UI.

IPC commands (written to /tmp/frame-cmd):
  reload-queue   — re-read queue.json and restart from the beginning
  reload-config  — re-read config.yaml (interval, schedule, overlay, …)
  next           — skip to next slot immediately
  pause          — toggle pause
  exclude:<guid> — add guid to excluded list in config and skip current slot
"""
from __future__ import annotations

import json
import logging
import os
import random
import signal
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

_CMD_FILE = Path("/tmp/frame-cmd")


def _run_cmd(args: list[str]) -> bool:
    """Run a command, return True on success, False if not found or failed."""
    import subprocess
    try:
        subprocess.run(args, check=True, timeout=3, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    except Exception as e:
        log.warning("Command %s failed: %s", args[0], e)
        return False


def _kscreen_outputs() -> list[tuple[str, int, int]]:
    """Return list of (output_name, width, height) from kscreen-doctor."""
    import subprocess, re
    try:
        out = subprocess.run(["kscreen-doctor", "-o"], capture_output=True,
                             text=True, timeout=3).stdout
    except Exception:
        return []
    results = []
    current_name = None
    for line in out.splitlines():
        # Strip ANSI escape codes
        clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
        m = re.match(r'Output:\s+\d+\s+(\S+)', clean)
        if m:
            current_name = m.group(1)
        if current_name:
            g = re.search(r'Geometry:\s+\S+\s+(\d+)x(\d+)', clean)
            if g:
                results.append((current_name, int(g.group(1)), int(g.group(2))))
    return results


def _kscreen_dpms(state: str, screen_w: int, screen_h: int) -> bool:
    """Turn on/off only the output matching screen_w x screen_h via kscreen-doctor."""
    outputs = _kscreen_outputs()
    if not outputs:
        return False
    target = next((name for name, w, h in outputs if w == screen_w and h == screen_h), None)
    if target is None:
        # Fallback: turn all off/on
        return _run_cmd(["kscreen-doctor", "--dpms", state])
    excluded = [name for name, _, _ in outputs if name != target]
    args = ["kscreen-doctor", "--dpms", state]
    for name in excluded:
        args += ["--dpms-excluded", name]
    return _run_cmd(args)
_CMD_POLL_INTERVAL = 1.0  # seconds between IPC polls


class DisplayService:
    def __init__(self) -> None:
        import pygame
        from ..config import config
        from ..sync.cache import load_queue, load_metadata, image_path
        from ..sync.icloud import PhotoMeta
        from . import renderer, overlay, transition

        from ..sync import db as _db
        _db.init_db()
        self._record_view = _db.record_view

        self.config = config
        self.load_queue = load_queue
        self.load_metadata = load_metadata
        self.image_path = image_path
        self.renderer = renderer
        self.overlay = overlay
        self.transition = transition
        self.pg = pygame

        # State
        self.queue: list[dict] = []
        self.metadata: dict = {}
        self.slot_index = 0
        self.paused = False
        self.running = True
        self.current_surface = None

        # Screen
        pygame.init()
        pygame.display.init()
        # Hide mouse cursor on framebuffer
        try:
            pygame.mouse.set_visible(False)
        except Exception:
            pass

        self._windowed = bool(os.environ.get("FRAMELINK_WINDOWED"))
        if self._windowed:
            # Dev/test mode: resizable window at 1280×720
            self.screen_w, self.screen_h = 1280, 720
            self.screen = pygame.display.set_mode(
                (self.screen_w, self.screen_h), pygame.RESIZABLE
            )
        else:
            # (0,0) lets pygame pick the native resolution for the current display
            flags = pygame.FULLSCREEN | pygame.NOFRAME
            self.screen = pygame.display.set_mode((0, 0), flags)
            self.screen_w = self.screen.get_width()
            self.screen_h = self.screen.get_height()
        log.info("Screen: %dx%d", self.screen_w, self.screen_h)
        pygame.display.set_caption("Framelink")

        # Register signal handler for clean shutdown
        signal.signal(signal.SIGTERM, self._on_sigterm)
        signal.signal(signal.SIGINT, self._on_sigterm)

    def _on_sigterm(self, *_) -> None:
        log.info("Signal received — shutting down")
        self.running = False

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def reload_queue(self) -> None:
        self.queue = self.load_queue()
        self.metadata = self.load_metadata()
        self.slot_index = random.randint(0, len(self.queue) - 1) if self.queue else 0
        log.info("Queue reloaded: %d slot(s), starting at slot %d", len(self.queue), self.slot_index)

    def advance_slot(self) -> None:
        if self.queue:
            self.slot_index = (self.slot_index + 1) % len(self.queue)

    def current_slot(self) -> dict | None:
        if not self.queue:
            return None
        return self.queue[self.slot_index % len(self.queue)]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_slot(self, slot: dict) -> tuple | None:
        """
        Render a slot to a pygame Surface.
        Returns (surface, primary_guid) or None if images are missing.
        """
        fill = self.config.layout.fill_mode
        w, h = self.screen_w, self.screen_h

        try:
            if slot["type"] == "single":
                guid = slot["guid"]
                path = self.image_path(guid)
                if not path.exists():
                    log.warning("Image missing for guid=%s — skipping slot", guid)
                    return None
                pil_img = self.renderer.render_single(path, w, h, fill)
                surf = self.renderer.pil_to_pygame_surface(pil_img)
                self.overlay.draw_overlay(surf, guid, w, h, self.metadata)
                return surf, guid

            elif slot["type"] == "pair":
                guids = slot["guids"]
                paths = [self.image_path(g) for g in guids]
                if not all(p.exists() for p in paths):
                    log.warning("Image(s) missing for pair %s — skipping", guids)
                    return None
                pil_img = self.renderer.render_pair(paths[0], paths[1], w, h, fill)
                surf = self.renderer.pil_to_pygame_surface(pil_img)
                # Overlay uses the first photo's metadata
                self.overlay.draw_overlay(surf, guids[0], w, h, self.metadata)
                return surf, guids[0]

        except Exception:
            log.exception("Error rendering slot %s", slot)
            return None

    # ------------------------------------------------------------------
    # IPC
    # ------------------------------------------------------------------

    def poll_cmd(self) -> str | None:
        if not _CMD_FILE.exists():
            return None
        try:
            cmd = _CMD_FILE.read_text().strip()
            _CMD_FILE.unlink()
            return cmd if cmd else None
        except OSError:
            return None

    def reload_config(self) -> None:
        import framelink_frame.config as _cfg_mod
        from ..config import load_config as _load_config
        import os
        from pathlib import Path as _Path
        cfg_path = os.environ.get("FRAMELINK_CONFIG")
        new_cfg = _load_config(_Path(cfg_path) if cfg_path else None)
        self.config = new_cfg
        # Update the module-level singleton so overlay.py, renderer etc. see the change
        _cfg_mod.config = new_cfg
        log.info("Config reloaded (interval=%.1fmin, overlay=%s, schedule=%s)",
                 new_cfg.rotation.interval_minutes,
                 new_cfg.overlay.enabled,
                 [(p.start, p.end) for p in new_cfg.schedule.active_periods])

    def handle_cmd(self, cmd: str) -> bool:
        """Handle an IPC command. Returns True if the display should advance immediately."""
        if cmd == "reload-queue":
            self.reload_queue()
            return True
        if cmd == "reload-config":
            self.reload_config()
            return True  # re-render current slot with new settings
        if cmd == "next":
            self.advance_slot()
            return True
        if cmd == "pause":
            self.paused = not self.paused
            log.info("Paused: %s", self.paused)
            return False
        if cmd.startswith("exclude:"):
            guid = cmd.removeprefix("exclude:")
            excluded = set(self.config.filters.excluded_photos)
            excluded.add(guid)
            self.config.filters.excluded_photos = list(excluded)
            # Skip current slot if it's the excluded photo
            slot = self.current_slot()
            if slot and (
                (slot["type"] == "single" and slot["guid"] == guid)
                or (slot["type"] == "pair" and guid in slot["guids"])
            ):
                self.advance_slot()
                return True
        return False

    # ------------------------------------------------------------------
    # Show a black screen (e.g. outside active hours)
    # ------------------------------------------------------------------

    def screen_off(self) -> None:
        # Always blank pygame surface first
        self.screen.fill((0, 0, 0))
        self.pg.display.flip()
        if self._windowed:
            return
        if _run_cmd(["vcgencmd", "display_power", "0"]):
            log.info("HDMI off (vcgencmd)")
        elif _kscreen_dpms("off", self.screen_w, self.screen_h):
            log.info("Display off (kscreen-doctor %dx%d)", self.screen_w, self.screen_h)
        elif _run_cmd(["xset", "dpms", "force", "off"]):
            log.info("Display off (xset dpms)")
        else:
            log.info("Screen blanked (no power-off command available)")

    def screen_on(self) -> None:
        if self._windowed:
            return
        if _run_cmd(["vcgencmd", "display_power", "1"]):
            log.info("HDMI on (vcgencmd)")
        elif _kscreen_dpms("on", self.screen_w, self.screen_h):
            log.info("Display on (kscreen-doctor %dx%d)", self.screen_w, self.screen_h)
        elif _run_cmd(["xset", "dpms", "force", "on"]):
            log.info("Display on (xset dpms)")

    def is_active_now(self) -> bool:
        from datetime import datetime
        now = datetime.now()
        current = now.hour * 60 + now.minute
        for period in self.config.schedule.active_periods:
            sh, sm = map(int, period.start.split(":"))
            eh, em = map(int, period.end.split(":"))
            if sh * 60 + sm <= current < eh * 60 + em:
                return True
        return False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.reload_queue()

        if not self.queue:
            log.warning("Queue is empty — waiting for sync")
            self.show_black()

        last_advance = 0.0
        last_cmd_poll = 0.0
        force_render = True
        screen_is_on = True  # assume on at start

        while self.running:
            now = time.monotonic()
            interval_s = self.config.rotation.interval_minutes * 60

            # Poll pygame events (keeps the event queue from overflowing)
            for event in self.pg.event.get():
                if event.type == self.pg.QUIT:
                    self.running = False
                elif event.type == self.pg.KEYDOWN:
                    if event.key in (self.pg.K_ESCAPE, self.pg.K_q):
                        self.running = False
                    elif event.key in (self.pg.K_SPACE, self.pg.K_RIGHT, self.pg.K_n):
                        force_render = self.handle_cmd("next")
                    elif event.key == self.pg.K_p:
                        self.handle_cmd("pause")
                elif event.type == self.pg.VIDEORESIZE and self._windowed:
                    self.screen_w, self.screen_h = event.w, event.h
                    self.screen = self.pg.display.set_mode(
                        (self.screen_w, self.screen_h), self.pg.RESIZABLE
                    )
                    # Re-render current slot at new size immediately
                    slot = self.current_slot()
                    if slot:
                        rendered = self.render_slot(slot)
                        if rendered:
                            self.current_surface, _ = rendered
                            self.transition.cut(self.screen, self.current_surface)

            # IPC poll
            if now - last_cmd_poll >= _CMD_POLL_INTERVAL:
                cmd = self.poll_cmd()
                if cmd:
                    if self.handle_cmd(cmd):
                        # Trigger immediate re-render without advancing slot
                        last_advance = 0.0
                        force_render = True
                last_cmd_poll = now

            # Outside active hours → turn screen off, poll events so window stays responsive
            if not self.is_active_now():
                if screen_is_on:
                    log.info("Outside active hours — screen off")
                    self.screen_off()
                    screen_is_on = False
                # Sleep in short bursts to keep event loop alive
                for _ in range(300):  # ~30s total
                    time.sleep(0.1)
                    for event in self.pg.event.get():
                        if event.type == self.pg.QUIT:
                            self.running = False
                        elif event.type == self.pg.KEYDOWN:
                            if event.key in (self.pg.K_ESCAPE, self.pg.K_q):
                                self.running = False
                    if not self.running:
                        break
                continue

            # Entering active hours — turn screen back on
            if not screen_is_on:
                log.info("Entering active hours — screen on")
                self.screen_on()
                screen_is_on = True
                force_render = True
                last_advance = 0.0

            # Time to advance to next slot?
            if not self.paused and (now - last_advance >= interval_s):
                if not force_render:  # avoid double-advance on reload
                    self.advance_slot()
                force_render = False
                last_advance = now

                # Find next renderable slot (skip missing images)
                rendered = None
                attempts = 0
                while rendered is None and attempts < len(self.queue):
                    slot = self.current_slot()
                    if slot:
                        rendered = self.render_slot(slot)
                    if rendered is None:
                        self.advance_slot()
                        attempts += 1

                if rendered is None:
                    log.warning("No renderable slots in queue")
                    self.show_black()
                    time.sleep(5)
                    continue

                # Record view + publish current slot for web UI
                displayed_slot = self.current_slot()
                if displayed_slot:
                    try:
                        if displayed_slot["type"] == "single":
                            self._record_view(displayed_slot["guid"])
                        else:
                            for g in displayed_slot["guids"]:
                                self._record_view(g)
                    except Exception:
                        log.debug("Could not record view for slot %s", displayed_slot)
                    try:
                        import json as _json
                        Path("/tmp/frame-current").write_text(_json.dumps(displayed_slot))
                    except OSError:
                        pass

                new_surface, _ = rendered

                # Transition
                if self.current_surface is not None:
                    style = self.config.transition.style
                    dur = self.config.transition.duration_ms
                    if style == "fade":
                        self.transition.fade(self.screen, self.current_surface, new_surface, dur)
                    else:
                        self.transition.cut(self.screen, new_surface)
                else:
                    self.transition.cut(self.screen, new_surface)

                self.current_surface = new_surface

            time.sleep(0.1)

        self.pg.quit()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    svc = DisplayService()
    svc.run()


if __name__ == "__main__":
    main()
