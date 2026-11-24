import pytest

from framelink_frame.sync import cache


def test_save_queue_roundtrip(cache_dir):
    slots = [{"type": "single", "guid": "a"}, {"type": "pair", "guids": ["b", "c"]}]
    cache.save_queue(slots)
    assert cache.load_queue() == slots
    assert not list(cache_dir.glob("*.tmp"))


def test_failed_replace_keeps_old_queue(cache_dir, monkeypatch):
    cache.save_queue([{"type": "single", "guid": "old"}])

    def boom(*_):
        raise OSError("disk full")

    monkeypatch.setattr(cache.os, "replace", boom)
    with pytest.raises(OSError):
        cache.save_queue([{"type": "single", "guid": "new"}])
    # the display still reads the complete old file, never a half-written one
    assert cache.load_queue() == [{"type": "single", "guid": "old"}]
