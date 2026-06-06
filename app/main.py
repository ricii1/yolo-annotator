"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db, embeddings, repo, storage
from app.config import Settings, load_settings, resolve_device
from app.embeddings import EmbeddingService
from app.inference import ModelService
from app.routers import assist, dataset, export, images, locks, search

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    settings.images_dir.mkdir(parents=True, exist_ok=True)

    if app.state.model_service is None:
        import torch

        device = resolve_device(settings.device, torch.cuda.is_available())
        app.state.model_service = ModelService.load(settings.model_path, device)

    # Load the CLIP embedding model for image search unless one was injected (tests).
    # A failure here (e.g. no internet for the weight download) disables search but
    # must not stop the annotator from serving.
    if app.state.embedding_service is None:
        import torch

        device = resolve_device(settings.device, torch.cuda.is_available())
        try:
            app.state.embedding_service = EmbeddingService.load(settings.embed_model, device)
        except Exception as exc:  # pragma: no cover - depends on network/model
            logger.warning("image search disabled: failed to load %s (%s)", settings.embed_model, exc)
            app.state.embedding_service = None

    conn = db.connect(settings.db_path)
    try:
        db.init_schema(conn)
        repo.set_classes(conn, app.state.model_service.names)
    finally:
        conn.close()

    # Backfill file_hash and embeddings for any images that lack them (non-blocking).
    asyncio.create_task(storage.hash_missing(settings))
    if app.state.embedding_service is not None:
        asyncio.create_task(embeddings.embed_missing(settings, app.state.embedding_service))
    yield


def create_app(
    settings: Settings | None = None,
    model_service: ModelService | None = None,
    embedding_service: EmbeddingService | None = None,
) -> FastAPI:
    app = FastAPI(title="YOLO Annotator", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.model_service = model_service
    app.state.embedding_service = embedding_service

    @app.middleware("http")
    async def ensure_session(request, call_next):
        sid = request.cookies.get("sid") or uuid.uuid4().hex
        request.state.sid = sid
        response = await call_next(request)
        response.set_cookie("sid", sid, httponly=True, samesite="lax")
        return response

    app.include_router(images.router)
    app.include_router(locks.router)
    app.include_router(assist.router)
    app.include_router(export.router)
    app.include_router(dataset.router)
    app.include_router(search.router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
