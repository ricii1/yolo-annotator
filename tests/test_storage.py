import io

import pytest
from PIL import Image

from app import storage


def _png_bytes(w=64, h=48, color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_save_upload_returns_dimensions(tmp_path):
    info = storage.save_upload(tmp_path, "photo.png", _png_bytes(64, 48))
    assert info.width == 64
    assert info.height == 48
    assert (tmp_path / info.filename).exists()


def test_save_upload_rejects_non_image(tmp_path):
    with pytest.raises(storage.InvalidImageError):
        storage.save_upload(tmp_path, "bad.png", b"not an image")


def test_save_upload_dedupes_colliding_names(tmp_path):
    a = storage.save_upload(tmp_path, "img.png", _png_bytes())
    b = storage.save_upload(tmp_path, "img.png", _png_bytes())
    assert a.filename != b.filename
    assert (tmp_path / a.filename).exists()
    assert (tmp_path / b.filename).exists()


def test_scan_folder_registers_new_images(tmp_path):
    src = tmp_path / "incoming"
    src.mkdir()
    (src / "one.png").write_bytes(_png_bytes(10, 20))
    (src / "two.png").write_bytes(_png_bytes(30, 40))
    (src / "notes.txt").write_text("ignore me")

    images_dir = tmp_path / "store"
    images_dir.mkdir()
    found = storage.scan_folder(src, images_dir, existing_filenames=set())

    names = sorted(f.filename for f in found)
    assert names == ["one.png", "two.png"]
    for f in found:
        assert (images_dir / f.filename).exists()


def test_scan_folder_skips_already_registered(tmp_path):
    src = tmp_path / "incoming"
    src.mkdir()
    (src / "one.png").write_bytes(_png_bytes())
    images_dir = tmp_path / "store"
    images_dir.mkdir()

    found = storage.scan_folder(src, images_dir, existing_filenames={"one.png"})
    assert found == []
