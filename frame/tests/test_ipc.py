import importlib
import threading
from pathlib import Path

from framelink_frame import ipc
from framelink_frame.sync import loop


def test_ipc_default_is_tmp(monkeypatch):
    monkeypatch.delenv("FRAMELINK_IPC_DIR", raising=False)
    assert ipc.cmd_file() == Path("/tmp/frame-cmd")
    assert ipc.current_file() == Path("/tmp/frame-current")
    assert ipc.sync_trigger_file() == Path("/tmp/sync-now")


def test_ipc_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAMELINK_IPC_DIR", str(tmp_path))
    assert ipc.cmd_file() == tmp_path / "frame-cmd"
    assert ipc.current_file() == tmp_path / "frame-current"
    assert ipc.sync_trigger_file() == tmp_path / "sync-now"


def test_services_pick_up_the_env(monkeypatch, tmp_path):
    from framelink_frame.sync import main as sync_main
    from framelink_frame.webui import main as webui
    monkeypatch.setenv("FRAMELINK_IPC_DIR", str(tmp_path))
    try:
        for mod in (sync_main, webui):
            importlib.reload(mod)
            assert mod._CMD_FILE == tmp_path / "frame-cmd"
        assert webui._CURRENT_FILE == tmp_path / "frame-current"
    finally:
        monkeypatch.undo()
        for mod in (sync_main, webui):
            importlib.reload(mod)


class FakeTime:
    """Clock that only moves when the loop waits; stops the loop after `until` seconds."""
    def __init__(self, stop, until):
        self.now, self.stop, self.until = 0.0, stop, until
        self.events = []   # (time, what)

    def clock(self):
        return self.now

    def wait_hook(self):
        self.now += loop.POLL_S
        if self.now >= self.until:
            self.stop.set()


def run(monkeypatch, tmp_path, until, photo, calendar, before_wait=None):
    monkeypatch.setenv("FRAMELINK_IPC_DIR", str(tmp_path))
    stop = threading.Event()
    t = FakeTime(stop, until)
    real_wait = stop.wait

    def fake_wait(timeout):
        if before_wait:
            before_wait(t.now)
        t.wait_hook()
        return real_wait(0)
    stop.wait = fake_wait
    loop.run_loop(lambda: photo(t.now), lambda: calendar(t.now), 3600, stop, 1800, clock=t.clock)
    return t


def test_both_syncs_run_on_their_own_interval(monkeypatch, tmp_path):
    p, c = [], []
    run(monkeypatch, tmp_path, 7300, p.append, c.append)
    assert p == [0.0, 3600.0, 7200.0]
    assert c == [0.0, 1800.0, 3600.0, 5400.0, 7200.0]


def test_a_failing_sync_does_not_stop_the_loop(monkeypatch, tmp_path):
    p, c = [], []

    def photo(now):
        p.append(now)
        raise SystemExit(1)   # what run_sync() does when the registry is down

    def calendar(now):
        c.append(now)
        raise RuntimeError("boom")

    run(monkeypatch, tmp_path, 3700, photo, calendar)
    assert p == [0.0, 3600.0]
    assert c == [0.0, 1800.0, 3600.0]


def test_trigger_file_runs_both_and_is_removed(monkeypatch, tmp_path):
    p, c = [], []
    trigger = tmp_path / "sync-now"

    def before_wait(now):
        if now == 100:
            trigger.touch()

    run(monkeypatch, tmp_path, 300, p.append, c.append, before_wait)
    assert p == [0.0, 105.0]
    assert c == [0.0, 105.0]
    assert not trigger.exists()


def test_show_black_exists_and_blanks_the_screen():
    from framelink_frame.display.main import DisplayService
    calls = []
    svc = DisplayService.__new__(DisplayService)
    svc.screen = type("S", (), {"fill": lambda self, c: calls.append(("fill", c))})()
    svc.pg = type("P", (), {"display": type("D", (), {"flip": staticmethod(lambda: calls.append("flip"))})})()
    svc.show_black()
    assert calls == [("fill", (0, 0, 0)), "flip"]
