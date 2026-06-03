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
