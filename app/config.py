"""Application configuration sourced from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_env_text(text: str) -> dict[str, str]:
    """Parse ``.env`` style text into a dict.

    Supports ``KEY=value`` lines, an optional ``export`` prefix, ``#`` comment
    lines, blank lines, surrounding single/double quotes, and ``=`` inside the
    value (only the first ``=`` splits).
    """
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (len(value) >= 2) and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def load_dotenv(path: str | Path = PROJECT_ROOT / ".env") -> None:
    """Load a ``.env`` file into ``os.environ`` without overriding existing vars.

    Missing files are ignored. Process environment values take precedence so a
    var set on the command line always wins over the file.
    """
    path = Path(path)
    if not path.is_file():
        return
    for key, value in parse_env_text(path.read_text()).items():
        os.environ.setdefault(key, value)


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
    embed_model: str
    root_path: str

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "annotator.db"


def load_settings() -> Settings:
    load_dotenv()
    data_dir = Path(os.environ.get("ANNOTATOR_DATA_DIR", "./data")).resolve()
    root_path = os.environ.get("ROOT_PATH", "/")
    if not root_path.startswith("/"):
        root_path = "/" + root_path
    if not root_path.endswith("/"):
        root_path = root_path + "/"
    while "//" in root_path:
        root_path = root_path.replace("//", "/")
    return Settings(
        model_path=os.environ.get("ANNOTATOR_MODEL_PATH", "yolo11n.pt"),
        data_dir=data_dir,
        device=os.environ.get("ANNOTATOR_DEVICE", "auto"),
        lock_ttl=int(os.environ.get("ANNOTATOR_LOCK_TTL", "60")),
        scan_dir=os.environ.get("ANNOTATOR_SCAN_DIR") or None,
        default_val_ratio=float(os.environ.get("ANNOTATOR_DEFAULT_VAL_RATIO", "0.2")),
        embed_model=os.environ.get("ANNOTATOR_EMBED_MODEL", "openai/clip-vit-base-patch32"),
        root_path=root_path,
    )
