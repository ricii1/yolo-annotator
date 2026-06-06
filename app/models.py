"""Pydantic request/response schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    iou: float = Field(default=0.45, ge=0.0, le=1.0)


class ScanRequest(BaseModel):
    folder: str | None = None


class SetStageRequest(BaseModel):
    image_ids: list[int]
    stage: Literal["annotating", "database"]


class SetStageByFilterRequest(BaseModel):
    stage: Literal["annotating", "database"]
    source_stage: Literal["annotating", "database"] | None = None
    include: list[int] = Field(default_factory=list)
    exclude: list[int] = Field(default_factory=list)
    only_unlabeled: bool = False


class ExportRequest(BaseModel):
    val_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    seed: int = 42


class SimilarRequest(BaseModel):
    image_id: int
    stage: str | None = None
    k: int = Field(default=200, ge=1, le=1000)


class RebalanceRequest(BaseModel):
    train: float = Field(ge=0.0, le=1.0)
    val: float = Field(ge=0.0, le=1.0)
    test: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: int = 42

    @model_validator(mode="after")
    def _ratios_within_one(self) -> "RebalanceRequest":
        if self.val + self.test > 1.0001:
            raise ValueError("val + test must not exceed 1.0")
        return self
