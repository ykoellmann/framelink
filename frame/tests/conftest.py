import pytest

from framelink_frame.config import config


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Point the frame's cache directory at a temp folder."""
    monkeypatch.setattr(config.sync, "cache_dir", tmp_path)
    return tmp_path
