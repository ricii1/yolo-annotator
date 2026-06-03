"""SQLite connection factory (WAL) and schema initialization."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT UNIQUE NOT NULL,
    rel_path    TEXT NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('upload', 'folder', 'import')),
    status      TEXT NOT NULL DEFAULT 'unlabeled'
                CHECK (status IN ('unlabeled', 'labeled', 'skipped')),
    split       TEXT,
    version     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id    INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    class_id    INTEGER NOT NULL,
    cx          REAL NOT NULL,
    cy          REAL NOT NULL,
    w           REAL NOT NULL,
    h           REAL NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'assist')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locks (
    image_id    INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    session_id  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS classes (
    class_id    INTEGER PRIMARY KEY,
    name        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_annotations_image ON annotations(image_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for concurrent small-team use."""
    conn = sqlite3.connect(
        str(path), timeout=10.0, check_same_thread=False, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_column(conn, "images", "split", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Add a column to an existing table if it is missing (simple migration)."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
