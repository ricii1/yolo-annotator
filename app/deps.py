"""Shared FastAPI dependencies."""
from __future__ import annotations

import datetime
from typing import Iterator

from fastapi import Request

from app import db
from app.config import Settings
from app.inference import ModelService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_model(request: Request) -> ModelService:
    return request.app.state.model_service


def get_embedder(request: Request):
    """The embedding service, or None when image search is unavailable."""
    return getattr(request.app.state, "embedding_service", None)


def get_conn(request: Request) -> Iterator:
    """Open a fresh SQLite connection per request and close it afterwards."""
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_session_id(request: Request) -> str:
    return request.state.sid


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)
