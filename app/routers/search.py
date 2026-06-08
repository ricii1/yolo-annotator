"""Image search: exact-duplicate lookup by content hash, and CLIP-based similarity."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import embeddings as emb
from app import repo
from app import storage
from app.deps import get_conn, get_embedder
from app.models import SimilarRequest

router = APIRouter(prefix="/api/search")


def _require_embedder(embedder):
    if embedder is None:
        raise HTTPException(503, "image search is unavailable (embedding model not loaded)")
    return embedder


def _rank(conn, query: np.ndarray, stage: str | None, k: int) -> list[dict]:
    ids, matrix = emb.build_matrix(repo.get_embedding_rows(conn, stage))
    ranked = emb.rank_by_similarity(query, ids, matrix, k)
    by_id = {r["id"]: r for r in repo.get_images_by_ids(conn, [i for i, _ in ranked])}
    out = []
    for i, s in ranked:
        item = dict(by_id.get(i, {"id": i}))
        item["image_id"] = i
        item["score"] = round(s, 4)
        out.append(item)
    return out


@router.post("/by-upload")
async def search_by_upload(
    file: UploadFile = File(...),
    stage: str = Form(""),
    conn=Depends(get_conn),
):
    """Find an exact duplicate of an uploaded image by content hash."""
    data = await file.read()
    row = repo.get_image_by_hash(conn, storage.compute_hash(data))
    results = []
    if row is not None and (not stage or row["stage"] == stage):
        item = dict(row)
        item["image_id"] = row["id"]
        item["score"] = 1.0
        results.append(item)
    return {"results": results}


@router.post("/similar")
async def search_similar(
    body: SimilarRequest,
    conn=Depends(get_conn),
    embedder=Depends(get_embedder),
):
    """Rank the dataset by similarity to an existing image's stored embedding."""
    _require_embedder(embedder)
    row = repo.get_embedding_row(conn, body.image_id)
    if row is None:
        raise HTTPException(404, "no embedding for that image yet")
    query = np.frombuffer(row["vector"], dtype=np.float32)
    return {"results": _rank(conn, query, body.stage, body.k)}
