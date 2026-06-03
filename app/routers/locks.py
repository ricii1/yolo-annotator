"""Soft per-image edit locks."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app import locks as lock_logic
from app import repo
from app.deps import get_conn, get_session_id, get_settings, utcnow

router = APIRouter(prefix="/api/locks")


@router.post("/{image_id}")
def claim(
    image_id: int,
    conn=Depends(get_conn),
    sid: str = Depends(get_session_id),
    settings=Depends(get_settings),
):
    if repo.get_image(conn, image_id) is None:
        raise HTTPException(404, "image not found")
    ok = lock_logic.claim_lock(conn, image_id, sid, utcnow(), settings.lock_ttl)
    if not ok:
        raise HTTPException(423, "image is being edited by another session")
    return {"locked": True, "ttl": settings.lock_ttl}


@router.post("/{image_id}/heartbeat")
def heartbeat(
    image_id: int,
    conn=Depends(get_conn),
    sid: str = Depends(get_session_id),
    settings=Depends(get_settings),
):
    ok = lock_logic.heartbeat(conn, image_id, sid, utcnow(), settings.lock_ttl)
    if not ok:
        raise HTTPException(409, "lock no longer held")
    return {"ok": True}


@router.delete("/{image_id}")
def release(
    image_id: int,
    conn=Depends(get_conn),
    sid: str = Depends(get_session_id),
):
    lock_logic.release_lock(conn, image_id, sid)
    return {"released": True}
