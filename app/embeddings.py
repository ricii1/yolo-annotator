"""Image embeddings (CLIP) with serialized GPU access, for similarity search.

Mirrors ``app.inference.ModelService``: a thin service wrapping an injectable
``embedder`` callable behind an asyncio lock so the GPU is touched one call at a
time, plus an idempotent backfill that embeds any image lacking a stored vector.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Sequence

import numpy as np

# Serializes whole-dataset backfills so startup and post-ingest triggers don't
# embed the same images concurrently.
_backfill_lock = asyncio.Lock()


def build_matrix(rows: Sequence) -> tuple[list[int], np.ndarray]:
    """Turn stored embedding rows into ``(ids, matrix)`` for similarity search.

    Each row exposes ``image_id`` and a float32 ``vector`` blob. Returns an empty
    ``(0, 0)`` matrix when there are no rows.
    """
    ids: list[int] = []
    vecs: list[np.ndarray] = []
    for r in rows:
        ids.append(int(r["image_id"]))
        vecs.append(np.frombuffer(r["vector"], dtype=np.float32))
    matrix = np.vstack(vecs) if vecs else np.empty((0, 0), dtype=np.float32)
    return ids, matrix


def rank_by_similarity(
    query: np.ndarray, ids: Sequence[int], matrix: np.ndarray, k: int
) -> list[tuple[int, float]]:
    """Return up to ``k`` ``(image_id, score)`` pairs by cosine similarity.

    Assumes ``query`` and every row of ``matrix`` are L2-normalized, so cosine
    similarity is the dot product. Brute force is microseconds at dataset scale.
    """
    if matrix.size == 0 or len(ids) == 0:
        return []
    scores = matrix @ query
    k = min(k, len(ids))
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [(int(ids[i]), float(scores[i])) for i in top]


class EmbeddingService:
    """Serializes embedding computation so the GPU is accessed one call at a time.

    ``embedder`` is ``(image_path: str) -> np.ndarray`` returning an L2-normalized
    float32 vector. Injecting it keeps the service testable without CLIP or a GPU.
    """

    def __init__(self, embedder: Callable[[str], np.ndarray], dim: int, model_name: str):
        self._embedder = embedder
        self.dim = dim
        self.model_name = model_name
        self._lock = asyncio.Lock()

    async def embed_image(self, image_path: str) -> np.ndarray:
        async with self._lock:
            return await asyncio.to_thread(self._embedder, image_path)

    @classmethod
    def load(cls, model_name: str, device: str) -> "EmbeddingService":
        """Build a service backed by a real CLIP image encoder (downloads weights)."""
        import torch
        from PIL import Image
        from transformers import CLIPModel, CLIPProcessor

        model = CLIPModel.from_pretrained(model_name).to(device).eval()
        processor = CLIPProcessor.from_pretrained(model_name)
        dim = int(model.config.projection_dim)

        def embedder(image_path: str) -> np.ndarray:
            with Image.open(image_path) as im:
                inputs = processor(images=im.convert("RGB"), return_tensors="pt").to(device)
            with torch.no_grad():
                feats = model.get_image_features(**inputs)
            vec = feats[0].cpu().numpy().astype("float32")
            norm = float(np.linalg.norm(vec))
            return vec / norm if norm > 0 else vec

        return cls(embedder, dim, model_name)


async def embed_missing(settings, service: "EmbeddingService") -> int:
    """Embed every image lacking a stored vector. Idempotent; returns count embedded.

    Operates on a snapshot of currently-missing images, so unreadable files are
    simply skipped (no infinite retry) and images created mid-run are handled by
    the next trigger. Serialized by ``_backfill_lock`` so overlapping triggers
    don't duplicate work.
    """
    from app import db, repo

    async with _backfill_lock:
        conn = db.connect(settings.db_path)
        embedded = 0
        try:
            rows = repo.images_without_embedding(conn)
            for row in rows:
                src = settings.images_dir / row["filename"]
                if not src.exists():
                    continue
                try:
                    vec = await service.embed_image(str(src))
                except Exception:
                    continue
                repo.set_embedding(
                    conn, row["id"], vec.tobytes(), service.dim, service.model_name
                )
                embedded += 1
        finally:
            conn.close()
        return embedded
