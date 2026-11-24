import pytest
from PIL import Image

from framelink_frame.display import renderer


def _jpeg(path, w, h):
    Image.new("RGB", (w, h), (200, 100, 50)).save(path, "JPEG")
    return path


def test_load_pil_draft_shrinks_but_stays_large_enough(tmp_path):
    p = _jpeg(tmp_path / "a.jpg", 4000, 3000)
    img = renderer._load_pil(p, fit=(1920, 1080))
    # fitted into 1920x1080 the photo is 1440x1080; the decode must not be smaller
    assert img.width >= 1440 and img.height >= 1080
    assert img.width < 4000   # but it was decoded at reduced size


def test_load_pil_without_fit_is_full_size(tmp_path):
    p = _jpeg(tmp_path / "a.jpg", 1000, 500)
    assert renderer._load_pil(p).size == (1000, 500)


def test_load_pil_small_photo_is_not_reduced(tmp_path):
    p = _jpeg(tmp_path / "a.jpg", 800, 600)
    assert renderer._load_pil(p, fit=(1920, 1080)).size == (800, 600)


def test_blurred_fill_size_mode_and_darkened():
    src = Image.new("RGB", (400, 300), (200, 200, 200))
    out = renderer._blurred_fill(src, 640, 360)
    assert out.size == (640, 360) and out.mode == "RGB"
    assert out.getpixel((320, 180)) == (100, 100, 100)   # 50 % darkening


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_render_single_and_pair_fill_the_screen(tmp_path, size):
    a = _jpeg(tmp_path / "a.jpg", 3000, 2000)
    b = _jpeg(tmp_path / "b.jpg", 2000, 3000)
    assert renderer.render_single(a, *size).size == size
    assert renderer.render_pair(b, b, *size).size == size
