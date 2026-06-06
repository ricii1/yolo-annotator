"""Parse and import Roboflow-format YOLO detection datasets.

A Roboflow export looks like::

    data.yaml
    train/images/*.jpg   train/labels/*.txt
    valid/images/*.jpg   valid/labels/*.txt
    test/images/*.jpg    test/labels/*.txt

Class ids in the zip are remapped to the server model's classes by name; boxes
whose class name is unknown to the model are dropped (and counted).
"""
from __future__ import annotations

import io
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import yaml

from app import repo, storage

SPLIT_FOLDERS = {"train": "train", "valid": "val", "val": "val", "test": "test"}
IMAGE_EXTENSIONS = storage.IMAGE_EXTENSIONS


def parse_names(data_yaml_text: str) -> dict[int, str]:
    """Read the ``names`` mapping from a data.yaml, as list or dict form."""
    data = yaml.safe_load(data_yaml_text) or {}
    names = data.get("names")
    if names is None:
        raise ValueError("data.yaml has no 'names'")
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    if isinstance(names, (list, tuple)):
        return {i: str(v) for i, v in enumerate(names)}
    raise ValueError("unsupported 'names' format")


def normalize_split(folder_name: str) -> str:
    """Map a Roboflow split folder name to a canonical split."""
    return SPLIT_FOLDERS.get(folder_name.lower(), folder_name.lower())


def build_class_remap(
    zip_names: dict[int, str], model_names: dict[int, str]
) -> dict[int, int]:
    """Map zip class id -> model class id by (case-insensitive) name match."""
    by_name = {name.strip().lower(): cid for cid, name in model_names.items()}
    remap: dict[int, int] = {}
    for zid, zname in zip_names.items():
        model_id = by_name.get(str(zname).strip().lower())
        if model_id is not None:
            remap[zid] = model_id
    return remap


def parse_label_file(text: str) -> list[dict]:
    """Parse YOLO detection label lines (``class cx cy w h``)."""
    boxes = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            class_id = int(float(parts[0]))
            cx, cy, w, h = (float(p) for p in parts[1:])
        except ValueError:
            continue
        boxes.append({"class_id": class_id, "cx": cx, "cy": cy, "w": w, "h": h})
    return boxes


def remap_boxes(boxes: list[dict], remap: dict[int, int]) -> tuple[list[dict], int]:
    """Remap box class ids; drop and count boxes whose class is unmatched."""
    kept, skipped = [], 0
    for b in boxes:
        if b["class_id"] not in remap:
            skipped += 1
            continue
        kept.append(
            {
                "class_id": remap[b["class_id"]],
                "cx": b["cx"],
                "cy": b["cy"],
                "w": b["w"],
                "h": b["h"],
                "source": "manual",
            }
        )
    return kept, skipped


def _is_split_dir(path: Path) -> bool:
    return (path / "images").is_dir() and (path / "labels").is_dir()


def discover_splits(root: Path) -> dict[str, dict]:
    """Find split folders under ``root`` (or one nested level down).

    Returns ``{canonical_split: {"images": Path, "labels": Path}}``.
    """
    root = Path(root)
    candidates = [root] + [p for p in sorted(root.iterdir()) if p.is_dir()]
    for base in candidates:
        found: dict[str, dict] = {}
        for child in sorted(base.iterdir()) if base.is_dir() else []:
            if child.is_dir() and child.name.lower() in SPLIT_FOLDERS and _is_split_dir(child):
                found[normalize_split(child.name)] = {
                    "images": child / "images",
                    "labels": child / "labels",
                }
        if found:
            return found
    return {}


def _find_data_yaml(root: Path) -> Path | None:
    matches = sorted(root.rglob("data.yaml"))
    return matches[0] if matches else None


def import_dataset(
    zip_bytes: bytes,
    conn: sqlite3.Connection,
    images_dir: Path,
    model_names: dict[int, str],
) -> dict:
    """Import a Roboflow YOLO zip into the project.

    Images from every split are copied in and registered with their original
    split; labels are remapped to the model's class ids by name (unknown classes
    dropped). Returns a summary dict.
    """
    images_dir = Path(images_dir)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(root)

        data_yaml = _find_data_yaml(root)
        if data_yaml is None:
            raise ValueError("zip has no data.yaml")
        zip_names = parse_names(data_yaml.read_text())
        remap = build_class_remap(zip_names, model_names)
        matched_ids = set(remap.keys())
        classes_skipped = sorted(
            zip_names[zid] for zid in zip_names if zid not in matched_ids
        )

        splits = discover_splits(data_yaml.parent)
        existing_hashes = repo.image_hashes(conn)
        images_imported = 0
        boxes_imported = 0
        boxes_skipped = 0
        per_split = {"train": 0, "val": 0, "test": 0}

        for split, dirs in splits.items():
            images_subdir = dirs["images"]
            labels_subdir = dirs["labels"]
            for img_path in sorted(images_subdir.iterdir()):
                if not img_path.is_file() or img_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                try:
                    h = storage.compute_hash(img_path.read_bytes())
                except OSError:
                    continue
                if h in existing_hashes:
                    continue
                info = storage.ingest_file(images_dir, img_path)
                if info is None:
                    continue
                existing_hashes.add(h)
                image_id = repo.create_image(
                    conn, info.filename, info.rel_path, info.width, info.height,
                    source="import", split=split, file_hash=h,
                )
                label_path = labels_subdir / f"{img_path.stem}.txt"
                boxes = parse_label_file(label_path.read_text()) if label_path.is_file() else []
                kept, skipped = remap_boxes(boxes, remap)
                repo.save_annotations(conn, image_id, kept, expected_version=0)
                images_imported += 1
                boxes_imported += len(kept)
                boxes_skipped += skipped
                per_split[split] = per_split.get(split, 0) + 1

    return {
        "images_imported": images_imported,
        "boxes_imported": boxes_imported,
        "boxes_skipped": boxes_skipped,
        "classes_skipped": classes_skipped,
        "splits": per_split,
    }
