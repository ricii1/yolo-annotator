"""Build a YOLO11 detection dataset from labeled images."""
from __future__ import annotations

import random
import shutil
import zipfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def split_images(ids: Sequence[int], val_ratio: float, seed: int) -> tuple[list[int], list[int]]:
    """Deterministically split image ids into (train, val).

    A fixed seed yields the same partition every time. The validation count is
    ``round(len * val_ratio)``; train always keeps at least the remainder so a
    single image never lands solely in val.
    """
    shuffled = list(ids)
    random.Random(seed).shuffle(shuffled)
    val_count = round(len(shuffled) * val_ratio)
    val_count = min(val_count, len(shuffled))
    val = sorted(shuffled[:val_count])
    train = sorted(shuffled[val_count:])
    return train, val


def partition_three_way(
    ids: Sequence[int], train: float, val: float, test: float, seed: int
) -> dict[str, list[int]]:
    """Deterministically partition ids into train/val/test by ratio.

    Val and test counts are ``round(len * ratio)``; train keeps the remainder, so
    it absorbs any rounding slack and is never starved below the leftover. A fixed
    ``seed`` yields the same partition every time. ``train`` is accepted for
    symmetry but unused — train is always the remainder.
    """
    shuffled = list(ids)
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)
    n_test = min(round(n * test), n)
    n_val = min(round(n * val), n - n_test)
    val_ids = sorted(shuffled[:n_val])
    test_ids = sorted(shuffled[n_val : n_val + n_test])
    train_ids = sorted(shuffled[n_val + n_test :])
    return {"train": train_ids, "val": val_ids, "test": test_ids}


def assign_splits(images: Sequence[Mapping], val_ratio: float, seed: int) -> dict[str, list[int]]:
    """Assign image ids to train/val/test.

    Images with an explicit ``split`` ("train"/"val"/"test") keep it. Images
    with no split are randomly partitioned into train/val by ``val_ratio`` with
    a fixed seed.
    """
    result: dict[str, list[int]] = {"train": [], "val": [], "test": []}
    unassigned: list[int] = []
    for img in images:
        split = img.get("split")
        if split in ("train", "val", "test"):
            result[split].append(img["id"])
        else:
            unassigned.append(img["id"])
    rand_train, rand_val = split_images(unassigned, val_ratio, seed)
    result["train"] = sorted(result["train"] + rand_train)
    result["val"] = sorted(result["val"] + rand_val)
    result["test"] = sorted(result["test"])
    return result


def _fmt(value: float) -> str:
    return ("%.6f" % value).rstrip("0").rstrip(".")


def format_label_lines(boxes: Iterable[Mapping]) -> list[str]:
    """Render annotation rows as YOLO label lines: ``class_id cx cy w h``."""
    lines = []
    for b in boxes:
        lines.append(
            f"{int(b['class_id'])} {_fmt(b['cx'])} {_fmt(b['cy'])} {_fmt(b['w'])} {_fmt(b['h'])}"
        )
    return lines


def build_data_yaml(class_names: Mapping[int, str], include_test: bool = False) -> str:
    """Produce a YOLO ``data.yaml`` body for the given class id->name mapping."""
    lines = [
        "path: .",
        "train: images/train",
        "val: images/val",
    ]
    if include_test:
        lines.append("test: images/test")
    lines.append(f"nc: {len(class_names)}")
    lines.append("names:")
    for class_id in sorted(class_names):
        lines.append(f"  {class_id}: {class_names[class_id]}")
    return "\n".join(lines) + "\n"


def write_dataset(
    out_dir: Path,
    class_names: Mapping[int, str],
    splits: Mapping[str, Sequence[dict]],
) -> Path:
    """Write the YOLO dataset tree under ``out_dir`` and return it.

    ``splits`` maps "train"/"val"/"test" to a list of items, each a dict with
    ``src_path`` (image file), ``filename`` and ``boxes`` (annotation dicts).
    Only non-empty splits are written. Images with no boxes still get an empty
    ``.txt`` (a valid YOLO background sample).
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for split_name, items in splits.items():
        if not items:
            continue
        img_dir = out_dir / "images" / split_name
        lbl_dir = out_dir / "labels" / split_name
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            shutil.copy2(item["src_path"], img_dir / item["filename"])
            stem = Path(item["filename"]).stem
            label_text = "\n".join(format_label_lines(item["boxes"]))
            if label_text:
                label_text += "\n"
            (lbl_dir / f"{stem}.txt").write_text(label_text)
    include_test = bool(splits.get("test"))
    (out_dir / "data.yaml").write_text(build_data_yaml(class_names, include_test=include_test))
    return out_dir


def zip_dataset(dataset_dir: Path, zip_path: Path) -> Path:
    """Zip an existing dataset directory, preserving its relative tree."""
    dataset_dir = Path(dataset_dir)
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(dataset_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(dataset_dir))
    return zip_path
