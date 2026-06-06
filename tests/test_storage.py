import asyncio
import hashlib
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


def test_compute_hash_returns_md5_hex():
    data = b"hello world"
    h = storage.compute_hash(data)
    assert h == hashlib.md5(data).hexdigest()
    assert len(h) == 32


def test_compute_hash_differs_for_different_data():
    assert storage.compute_hash(b"aaa") != storage.compute_hash(b"bbb")


def test_save_upload_includes_file_hash(tmp_path):
    data = _png_bytes()
    info = storage.save_upload(tmp_path, "photo.png", data)
    assert info.file_hash == hashlib.md5(data).hexdigest()


def test_ingest_file_includes_file_hash(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    data = _png_bytes()
    (src / "img.png").write_bytes(data)
    dest = tmp_path / "dest"
    dest.mkdir()
    info = storage.ingest_file(dest, src / "img.png")
    assert info.file_hash == hashlib.md5(data).hexdigest()


def test_scan_folder_includes_file_hash(tmp_path):
    src = tmp_path / "incoming"
    src.mkdir()
    data = _png_bytes()
    (src / "one.png").write_bytes(data)
    images_dir = tmp_path / "store"
    images_dir.mkdir()
    found = storage.scan_folder(src, images_dir, existing_filenames=set())
    assert found[0].file_hash == hashlib.md5(data).hexdigest()


def test_scan_folder_skips_hash_duplicate(tmp_path):
    src = tmp_path / "incoming"
    src.mkdir()
    data = _png_bytes()
    (src / "one.png").write_bytes(data)
    images_dir = tmp_path / "store"
    images_dir.mkdir()
    known_hash = hashlib.md5(data).hexdigest()
    found = storage.scan_folder(src, images_dir, existing_filenames=set(), existing_hashes={known_hash})
    assert found == []
    assert not (images_dir / "one.png").exists()


def test_hash_missing_backfills_unhashed_images(tmp_path):
    from app import db, repo
    from app.config import Settings

    settings = Settings(
        model_path="x", data_dir=tmp_path, device="cpu", lock_ttl=60,
        scan_dir=None, default_val_ratio=0.2, embed_model="fake",
        root_path="/",
    )
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    data = _png_bytes()
    (settings.images_dir / "img.png").write_bytes(data)

    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    repo.create_image(conn, "img.png", "images/img.png", 64, 48, "upload")
    conn.close()

    assert asyncio.run(storage.hash_missing(settings)) == 1

    conn = db.connect(settings.db_path)
    assert repo.images_without_hash(conn) == []
    row = repo.get_image_by_hash(conn, hashlib.md5(data).hexdigest())
    assert row is not None
    conn.close()

    assert asyncio.run(storage.hash_missing(settings)) == 0


def test_hash_missing_skips_missing_files(tmp_path):
    from app import db, repo
    from app.config import Settings

    settings = Settings(
        model_path="x", data_dir=tmp_path, device="cpu", lock_ttl=60,
        scan_dir=None, default_val_ratio=0.2, embed_model="fake",
        root_path="/",
    )
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    repo.create_image(conn, "ghost.png", "images/ghost.png", 8, 8, "upload")
    conn.close()

    assert asyncio.run(storage.hash_missing(settings)) == 0
