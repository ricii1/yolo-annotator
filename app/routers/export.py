"""Classes and YOLO11 dataset export."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app import export as export_logic
from app import repo
from app.deps import get_conn, get_settings
from app.models import ExportRequest

router = APIRouter(prefix="/api")

# write_dataset() deletes and rebuilds the shared export directory, then
# zip_dataset() walks it; overlapping requests would have one rebuild the
# tree while another is mid-walk, raising FileNotFoundError. Serialize the
# whole build-then-zip pipeline so each export sees a consistent tree.
_export_lock = threading.Lock()


@router.get("/classes")
def get_classes(conn=Depends(get_conn)):
    return {"classes": repo.get_classes(conn)}


@router.post("/export")
def export_dataset(
    body: ExportRequest,
    conn=Depends(get_conn),
    settings=Depends(get_settings),
):
    database = repo.database_images_with_boxes(conn)
    if not database:
        raise HTTPException(400, "no Database images to export")

    val_ratio = body.val_ratio if body.val_ratio is not None else settings.default_val_ratio
    assigned = export_logic.assign_splits(database, val_ratio, body.seed)
    by_id = {r["id"]: r for r in database}

    def to_item(image_id: int) -> dict:
        r = by_id[image_id]
        return {
            "src_path": str(settings.images_dir / r["filename"]),
            "filename": r["filename"],
            "boxes": r["boxes"],
        }

    splits = {name: [to_item(i) for i in ids] for name, ids in assigned.items()}
    classes = repo.get_classes(conn)

    out_dir = settings.data_dir / "export"
    zip_path = settings.data_dir / "dataset.zip"
    with _export_lock:
        export_logic.write_dataset(out_dir, classes, splits)
        export_logic.zip_dataset(out_dir, zip_path)
        # Read the bytes while still holding the lock so the response is immune
        # to a subsequent export overwriting zip_path mid-stream.
        data = zip_path.read_bytes()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="dataset.zip"'},
    )
