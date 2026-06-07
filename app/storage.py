"""Image ingestion: uploads and server-folder scans."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


class InvalidImageError(Exception):
    """Raised when uploaded bytes are not a readable image."""


@dataclass
class IngestedImage:
    filename: str
    rel_path: str
    width: int
    height: int
    file_hash: str


def compute_hash(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _unique_name(images_dir: Path, filename: str) -> str:
    """Return a filename that does not collide with existing files."""
    candidate = Path(filename).name
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    i = 1
    while (images_dir / candidate).exists():
        candidate = f"{stem}_{i}{suffix}"
        i += 1
    return candidate


def _read_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.width, im.height


def thumbnail_path(data_dir: Path, image_id: int, src_path: Path, max_edge: int = 256) -> Path:
    """Return a cached downscaled JPEG for ``src_path``, creating it on first use.

    Thumbnails live under ``data_dir/thumbs/{id}.jpg`` and are regenerated when the
    source image is newer than the cache. Raises ``InvalidImageError`` if the source
    cannot be read.
    """
    data_dir = Path(data_dir)
    src_path = Path(src_path)
    thumbs_dir = data_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    dest = thumbs_dir / f"{image_id}.jpg"
    if dest.exists() and dest.stat().st_mtime >= src_path.stat().st_mtime:
        return dest
    # Write to a temp file and rename into place atomically: a concurrent request
    # for the same thumbnail must never observe (and stream) a half-written file.
    fd, tmp_name = tempfile.mkstemp(dir=thumbs_dir, prefix=f".{image_id}-", suffix=".jpg")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp_file, Image.open(src_path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_edge, max_edge))
            im.save(tmp_file, format="JPEG", quality=80)
        os.replace(tmp_path, dest)
    except (UnidentifiedImageError, OSError) as exc:
        tmp_path.unlink(missing_ok=True)
        raise InvalidImageError(f"cannot create thumbnail for {src_path}") from exc
    return dest


def save_upload(images_dir: Path, filename: str, data: bytes) -> IngestedImage:
    """Validate and store uploaded image bytes under ``images_dir``."""
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    h = compute_hash(data)
    stored = _unique_name(images_dir, filename)
    dest = images_dir / stored
    dest.write_bytes(data)
    try:
        width, height = _read_size(dest)
    except (UnidentifiedImageError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise InvalidImageError(f"{filename} is not a valid image") from exc
    return IngestedImage(stored, f"images/{stored}", width, height, file_hash=h)


def ingest_file(images_dir: Path, src_path: Path) -> IngestedImage | None:
    """Copy a single image file into ``images_dir`` (deduped). None if unreadable."""
    images_dir = Path(images_dir)
    src_path = Path(src_path)
    images_dir.mkdir(parents=True, exist_ok=True)
    try:
        width, height = _read_size(src_path)
    except (UnidentifiedImageError, OSError):
        return None
    try:
        data = src_path.read_bytes()
    except OSError:
        return None
    h = compute_hash(data)
    stored = _unique_name(images_dir, src_path.name)
    shutil.copy2(src_path, images_dir / stored)
    return IngestedImage(stored, f"images/{stored}", width, height, file_hash=h)


def scan_folder(
    folder: Path,
    images_dir: Path,
    existing_filenames: set[str],
    existing_hashes: set[str] | None = None,
) -> list[IngestedImage]:
    """Register image files from ``folder`` not already known.

    Files are copied into ``images_dir`` so the app owns a stable copy.
    Pass ``existing_hashes`` to skip byte-identical duplicates by MD5.
    """
    folder = Path(folder)
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    found: list[IngestedImage] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if path.name in existing_filenames:
            continue
        try:
            width, height = _read_size(path)
        except (UnidentifiedImageError, OSError):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        h = compute_hash(data)
        if existing_hashes is not None and h in existing_hashes:
            continue
        stored = _unique_name(images_dir, path.name)
        shutil.copy2(path, images_dir / stored)
        existing_filenames.add(stored)
        if existing_hashes is not None:
            existing_hashes.add(h)
        found.append(IngestedImage(stored, f"images/{stored}", width, height, file_hash=h))
    return found


async def hash_missing(settings) -> int:
    """Backfill file_hash for images that lack one. Idempotent; returns count updated."""
    import logging
    import sqlite3
    from app import db, repo

    logger = logging.getLogger(__name__)
    conn = db.connect(settings.db_path)
    hashed = 0
    try:
        rows = repo.images_without_hash(conn)
        for row in rows:
            src = settings.images_dir / row["filename"]
            try:
                data = src.read_bytes()
            except OSError:
                continue
            h = compute_hash(data)
            try:
                repo.set_file_hash(conn, row["id"], h)
                hashed += 1
            except sqlite3.IntegrityError:
                # Another image already has this hash — pre-existing duplicate.
                # Skip silently; both records stay, but only the first gets the hash.
                logger.warning("hash_missing: skipping duplicate image id=%d (hash=%s)", row["id"], h)
    finally:
        conn.close()
    return hashed
