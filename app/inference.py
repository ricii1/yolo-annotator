"""YOLO model serving with serialized GPU access."""
from __future__ import annotations

import asyncio
from typing import Callable


def boxes_from_result(result) -> list[dict]:
    """Convert one Ultralytics result into normalized box dicts.

    Uses ``boxes.xywhn`` (normalized center x/y + width/height), ``cls`` and
    ``conf``. Returns an empty list when there are no detections.
    """
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    out = []
    count = len(boxes.cls)
    for i in range(count):
        row = boxes.xywhn[i]
        out.append(
            {
                "class_id": int(float(boxes.cls[i])),
                "cx": round(float(row[0]), 6),
                "cy": round(float(row[1]), 6),
                "w": round(float(row[2]), 6),
                "h": round(float(row[3]), 6),
                "conf": round(float(boxes.conf[i]), 4),
            }
        )
    return out


class ModelService:
    """Wraps a predictor callable and serializes calls so the GPU is never
    accessed concurrently.

    ``predictor`` is ``(image_path: str, conf: float) -> list[dict]``. Injecting
    it keeps the service testable without a real model or GPU.
    """

    def __init__(self, predictor: Callable[[str, float], list[dict]], names: dict[int, str]):
        self._predictor = predictor
        self.names = names
        self._lock = asyncio.Lock()

    async def predict(self, image_path: str, conf: float = 0.25) -> list[dict]:
        async with self._lock:
            return await asyncio.to_thread(self._predictor, image_path, conf)

    @classmethod
    def load(cls, model_path: str, device: str) -> "ModelService":
        """Load an Ultralytics YOLO model and build a serialized service."""
        from ultralytics import YOLO

        model = YOLO(model_path)
        names = {int(k): v for k, v in model.names.items()}

        def predictor(image_path: str, conf: float) -> list[dict]:
            results = model.predict(
                source=image_path, conf=conf, device=device, verbose=False
            )
            return boxes_from_result(results[0]) if results else []

        return cls(predictor, names)
