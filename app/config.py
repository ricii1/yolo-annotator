"""Application configuration sourced from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def resolve_device(requested: str, cuda_available: bool) -> str:
    """Resolve the inference device.

    "auto" maps to "cuda" when a GPU is available, otherwise "cpu".
    Any explicit value is returned unchanged.
    """
    if requested == "auto":
        return "cuda" if cuda_available else "cpu"
    return requested


@dataclass
class Settings:
    model_path: str
    data_dir: Path
    device: str
    lock_ttl: int
    scan_dir: str | None
    default_val_ratio: float

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "annotator.db"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("ANNOTATOR_DATA_DIR", "./data")).resolve()
    return Settings(
        model_path=os.environ.get("ANNOTATOR_MODEL_PATH", "yolo11n.pt"),
        data_dir=data_dir,
        device=os.environ.get("ANNOTATOR_DEVICE", "auto"),
        lock_ttl=int(os.environ.get("ANNOTATOR_LOCK_TTL", "60")),
        scan_dir=os.environ.get("ANNOTATOR_SCAN_DIR") or None,
        default_val_ratio=float(os.environ.get("ANNOTATOR_DEFAULT_VAL_RATIO", "0.2")),
    )
