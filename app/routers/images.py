"""Image listing, ingest, retrieval, and annotation saving."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import locks, repo, storage
from app.deps import get_conn, get_session_id, get_settings, utcnow
from app.models import SaveAnnotationsRequest, ScanRequest

router = APIRouter(prefix="/api")


@router.get("/images")
def list_images(conn=Depends(get_conn), sid: str = Depends(get_session_id)):
    items = repo.list_images(conn, utcnow())
    for it in items:
        it["locked_by_me"] = it["locked_by"] == sid
    return {"images": items, "classes": repo.get_classes(conn)}


@router.post("/images/upload")
async def upload_images(
    files: list[UploadFile] = File(...),
    conn=Depends(get_conn),
    settings=Depends(get_settings),
):
    created, skipped = [], []
    for f in files:
        data = await f.read()
        try:
            info = storage.save_upload(settings.images_dir, f.filename or "upload", data)
        except storage.InvalidImageError:
            skipped.append(f.filename)
            continue
        img_id = repo.create_image(
            conn, info.filename, info.rel_path, info.width, info.height, "upload"
        )
        created.append({"id": img_id, "filename": info.filename})
    return {"created": created, "skipped": skipped}


@router.post("/images/scan")
def scan_images(
    body: ScanRequest,
    conn=Depends(get_conn),
    settings=Depends(get_settings),
):
    folder = body.folder or settings.scan_dir
    if not folder:
        raise HTTPException(400, "no scan folder configured")
    path = Path(folder)
    if not path.is_dir():
        raise HTTPException(400, f"folder not found: {folder}")
    existing = repo.image_filenames(conn)
    found = storage.scan_folder(path, settings.images_dir, existing)
    created = []
    for info in found:
        img_id = repo.create_image(
            conn, info.filename, info.rel_path, info.width, info.height, "folder"
        )
        created.append({"id": img_id, "filename": info.filename})
    return {"created": created}


@router.get("/images/{image_id}")
def get_image(image_id: int, conn=Depends(get_conn)):
    row = repo.get_image(conn, image_id)
    if row is None:
        raise HTTPException(404, "image not found")
    return {
        "image": dict(row),
        "annotations": repo.get_annotations(conn, image_id),
        "version": row["version"],
    }


@router.get("/images/{image_id}/file")
def get_image_file(image_id: int, conn=Depends(get_conn), settings=Depends(get_settings)):
    row = repo.get_image(conn, image_id)
    if row is None:
        raise HTTPException(404, "image not found")
    path = settings.images_dir / row["filename"]
    if not path.exists():
        raise HTTPException(404, "image file missing")
    return FileResponse(path)


@router.put("/images/{image_id}/annotations")
def save_annotations(
    image_id: int,
    body: SaveAnnotationsRequest,
    conn=Depends(get_conn),
    sid: str = Depends(get_session_id),
):
    row = repo.get_image(conn, image_id)
    if row is None:
        raise HTTPException(404, "image not found")
    holder = locks.lock_holder(conn, image_id, utcnow())
    if holder is not None and holder != sid:
        raise HTTPException(423, "image is locked by another session")
    boxes = [b.model_dump() for b in body.boxes]
    try:
        new_version = repo.save_annotations(conn, image_id, boxes, body.version)
    except repo.StaleVersionError:
        current = repo.get_image(conn, image_id)["version"]
        raise HTTPException(
            409,
            detail={"message": "stale version, reload required", "current_version": current},
        )
    return {"version": new_version}
