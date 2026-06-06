"""Image ingestion: uploads and server-folder scans."""
from __future__ import annotations

import shutil
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
    try:
        with Image.open(src_path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_edge, max_edge))
            im.save(dest, format="JPEG", quality=80)
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError(f"cannot create thumbnail for {src_path}") from exc
    return dest


def save_upload(images_dir: Path, filename: str, data: bytes) -> IngestedImage:
    """Validate and store uploaded image bytes under ``images_dir``."""
    images_dir = Path(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    stored = _unique_name(images_dir, filename)
    dest = images_dir / stored
    dest.write_bytes(data)
    try:
        width, height = _read_size(dest)
    except (UnidentifiedImageError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise InvalidImageError(f"{filename} is not a valid image") from exc
    return IngestedImage(stored, f"images/{stored}", width, height)


def ingest_file(images_dir: Path, src_path: Path) -> IngestedImage | None:
    """Copy a single image file into ``images_dir`` (deduped). None if unreadable."""
    images_dir = Path(images_dir)
    src_path = Path(src_path)
    images_dir.mkdir(parents=True, exist_ok=True)
    try:
        width, height = _read_size(src_path)
    except (UnidentifiedImageError, OSError):
        return None
    stored = _unique_name(images_dir, src_path.name)
    shutil.copy2(src_path, images_dir / stored)
    return IngestedImage(stored, f"images/{stored}", width, height)


def scan_folder(
    folder: Path, images_dir: Path, existing_filenames: set[str]
) -> list[IngestedImage]:
    """Register image files from ``folder`` not already known.

    Files are copied into ``images_dir`` so the app owns a stable copy.
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
        stored = _unique_name(images_dir, path.name)
        shutil.copy2(path, images_dir / stored)
        existing_filenames.add(stored)
        found.append(IngestedImage(stored, f"images/{stored}", width, height))
    return found
