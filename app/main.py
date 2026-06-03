"""FastAPI application factory."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db, repo
from app.config import Settings, load_settings, resolve_device
from app.inference import ModelService
from app.routers import assist, export, images, locks

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    settings.images_dir.mkdir(parents=True, exist_ok=True)

    if app.state.model_service is None:
        import torch

        device = resolve_device(settings.device, torch.cuda.is_available())
        app.state.model_service = ModelService.load(settings.model_path, device)

    conn = db.connect(settings.db_path)
    try:
        db.init_schema(conn)
        repo.set_classes(conn, app.state.model_service.names)
    finally:
        conn.close()
    yield


def create_app(settings: Settings | None = None, model_service: ModelService | None = None) -> FastAPI:
    app = FastAPI(title="YOLO Annotator", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.model_service = model_service

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
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
