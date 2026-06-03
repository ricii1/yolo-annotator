"""Label-assist inference endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app import repo
from app.deps import get_conn, get_model, get_settings
from app.models import PredictRequest

router = APIRouter(prefix="/api/assist")


@router.post("/predict")
async def predict(
    body: PredictRequest,
    conn=Depends(get_conn),
    model=Depends(get_model),
    settings=Depends(get_settings),
):
    row = repo.get_image(conn, body.image_id)
    if row is None:
        raise HTTPException(404, "image not found")
    path = str(settings.images_dir / row["filename"])
    try:
        boxes = await model.predict(path, body.conf, body.iou)
    except Exception as exc:  # inference failure must not crash annotation
        raise HTTPException(503, f"inference failed: {exc}")
    return {"boxes": boxes}
