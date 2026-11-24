from framelink_frame.webui import main as webui


def test_sync_button_goes_through_sudo(monkeypatch):
    calls = []
    monkeypatch.setattr("shutil.which", lambda name: "/bin/systemctl")
    monkeypatch.setattr("subprocess.run", lambda args, **kw: calls.append(args))
    resp = webui.app.test_client().post("/api/sync")
    assert resp.get_json() == {"ok": True}
    # install.sh whitelists exactly this command for the framelink user
    assert calls == [["sudo", "-n", "/bin/systemctl", "start", "framelink-sync.service"]]


def test_sync_button_without_systemd_writes_trigger_file(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("FRAMELINK_IPC_DIR", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("subprocess.run", lambda args, **kw: calls.append(args))
    resp = webui.app.test_client().post("/api/sync")
    assert resp.get_json() == {"ok": True}
    assert (tmp_path / "sync-now").exists()
    assert calls == []
