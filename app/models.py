"""Pydantic request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Box(BaseModel):
    class_id: int
    cx: float = Field(ge=0.0, le=1.0)
    cy: float = Field(ge=0.0, le=1.0)
    w: float = Field(ge=0.0, le=1.0)
    h: float = Field(ge=0.0, le=1.0)
    source: str = "manual"


class SaveAnnotationsRequest(BaseModel):
    version: int
    boxes: list[Box]


class PredictRequest(BaseModel):
    image_id: int
    conf: float = Field(default=0.25, ge=0.0, le=1.0)


class ScanRequest(BaseModel):
    folder: str | None = None


class ExportRequest(BaseModel):
    val_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    seed: int = 42
