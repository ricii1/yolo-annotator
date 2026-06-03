"""Data access for images, annotations, and classes."""
from __future__ import annotations

import datetime
import sqlite3
from typing import Sequence

from app import locks


class StaleVersionError(Exception):
    """Raised when a save is attempted against an out-of-date image version."""


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def create_image(
    conn: sqlite3.Connection,
    filename: str,
    rel_path: str,
    width: int,
    height: int,
    source: str,
) -> int:
    cur = conn.execute(
        "INSERT INTO images (filename, rel_path, width, height, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (filename, rel_path, width, height, source, _now_iso()),
    )
    return cur.lastrowid


def get_image(conn: sqlite3.Connection, image_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


def image_filenames(conn: sqlite3.Connection) -> set[str]:
    return {r["filename"] for r in conn.execute("SELECT filename FROM images")}


def list_images(conn: sqlite3.Connection, now: datetime.datetime) -> list[dict]:
    """List images with their current lock holder (if any)."""
    rows = conn.execute("SELECT * FROM images ORDER BY id").fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["locked_by"] = locks.lock_holder(conn, r["id"], now)
        result.append(item)
    return result


def get_annotations(conn: sqlite3.Connection, image_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT class_id, cx, cy, w, h, source FROM annotations WHERE image_id = ? ORDER BY id",
        (image_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def save_annotations(
    conn: sqlite3.Connection,
    image_id: int,
    boxes: Sequence[dict],
    expected_version: int,
) -> int:
    """Replace an image's annotations atomically, guarded by optimistic version.

    Returns the new version. Raises StaleVersionError if ``expected_version`` no
    longer matches the stored version.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT version FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"image {image_id} not found")
        if row["version"] != expected_version:
            raise StaleVersionError(
                f"expected version {expected_version}, have {row['version']}"
            )
        conn.execute("DELETE FROM annotations WHERE image_id = ?", (image_id,))
        created_at = _now_iso()
        for b in boxes:
            conn.execute(
                "INSERT INTO annotations (image_id, class_id, cx, cy, w, h, source, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    image_id,
                    int(b["class_id"]),
                    float(b["cx"]),
                    float(b["cy"]),
                    float(b["w"]),
                    float(b["h"]),
                    b.get("source", "manual"),
                    created_at,
                ),
            )
        new_version = expected_version + 1
        conn.execute(
            "UPDATE images SET version = ?, status = 'labeled' WHERE id = ?",
            (new_version, image_id),
        )
        conn.execute("COMMIT")
        return new_version
    except Exception:
        conn.execute("ROLLBACK")
        raise


def set_status(conn: sqlite3.Connection, image_id: int, status: str) -> None:
    conn.execute("UPDATE images SET status = ? WHERE id = ?", (status, image_id))


def set_classes(conn: sqlite3.Connection, names: dict[int, str]) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM classes")
        for class_id, name in names.items():
            conn.execute(
                "INSERT INTO classes (class_id, name) VALUES (?, ?)", (int(class_id), name)
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_classes(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute("SELECT class_id, name FROM classes ORDER BY class_id").fetchall()
    return {r["class_id"]: r["name"] for r in rows}


def labeled_images_with_boxes(conn: sqlite3.Connection) -> list[dict]:
    """Return labeled images with their boxes, for export."""
    rows = conn.execute(
        "SELECT * FROM images WHERE status = 'labeled' ORDER BY id"
    ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["boxes"] = get_annotations(conn, r["id"])
        result.append(item)
    return result
