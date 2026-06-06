import asyncio
import hashlib

import numpy as np
import pytest
from PIL import Image

from app import db, embeddings, repo
from app.config import Settings
from app.embeddings import EmbeddingService, build_matrix, rank_by_similarity


def _unit(v):
    v = np.array(v, dtype="float32")
    return v / np.linalg.norm(v)


def _fake_service(dim=8):
    def embedder(path):
        raw = open(path, "rb").read()
        seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
        v = np.random.default_rng(seed).standard_normal(dim).astype("float32")
        return v / np.linalg.norm(v)

    return EmbeddingService(embedder=embedder, dim=dim, model_name="fake")


def _settings(tmp_path):
    return Settings(
        model_path="x", data_dir=tmp_path, device="cpu", lock_ttl=60,
        scan_dir=None, default_val_ratio=0.2, embed_model="fake",
        root_path="/",
    )


def test_rank_by_similarity_orders_by_cosine():
    ids = [10, 20, 30]
    matrix = np.vstack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([1, 1, 0])])
    ranked = rank_by_similarity(_unit([1, 0, 0]), ids, matrix, k=3)
    assert ranked[0][0] == 10  # exact match first
    assert ranked[0][1] == pytest.approx(1.0, abs=1e-5)
    assert [r[0] for r in ranked] == [10, 30, 20]  # [1,1,0] closer than [0,1,0]


def test_rank_by_similarity_empty_matrix():
    assert rank_by_similarity(_unit([1, 0]), [], np.empty((0, 0), dtype="float32"), 5) == []


def test_rank_by_similarity_respects_k():
    ids = [1, 2, 3, 4]
    matrix = np.vstack([_unit([1, 0]), _unit([0.9, 0.1]), _unit([0, 1]), _unit([-1, 0])])
    assert len(rank_by_similarity(_unit([1, 0]), ids, matrix, k=2)) == 2


def test_build_matrix_roundtrip():
    v = _unit([1, 2, 3])
    ids, m = build_matrix([{"image_id": 5, "vector": v.tobytes()}])
    assert ids == [5]
    assert np.allclose(m[0], v)


def test_embed_missing_populates_only_missing(tmp_path):
    settings = _settings(tmp_path)
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    for i, name in enumerate(["a.png", "b.png"]):
        Image.new("RGB", (8, 8), (i * 40, 10, 10)).save(settings.images_dir / name)
        repo.create_image(conn, name, f"images/{name}", 8, 8, "upload")
    conn.close()

    svc = _fake_service()
    assert asyncio.run(embeddings.embed_missing(settings, svc)) == 2

    conn = db.connect(settings.db_path)
    assert repo.images_without_embedding(conn) == []
    conn.close()
    # idempotent: a second run embeds nothing
    assert asyncio.run(embeddings.embed_missing(settings, svc)) == 0


def test_embed_missing_skips_unreadable_files(tmp_path):
    settings = _settings(tmp_path)
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_path)
    db.init_schema(conn)
    repo.create_image(conn, "ghost.png", "images/ghost.png", 8, 8, "upload")  # no file on disk
    conn.close()
    # does not raise or loop forever; just embeds nothing
    assert asyncio.run(embeddings.embed_missing(settings, _fake_service())) == 0
