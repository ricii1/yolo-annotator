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
    split: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO images (filename, rel_path, width, height, source, split, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (filename, rel_path, width, height, source, split, _now_iso()),
    )
    return cur.lastrowid


def get_image(conn: sqlite3.Connection, image_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


def image_filenames(conn: sqlite3.Connection) -> set[str]:
    return {r["filename"] for r in conn.execute("SELECT filename FROM images")}


def _live_lock_map(conn: sqlite3.Connection, now: datetime.datetime) -> dict[int, str]:
    """All currently-live locks as {image_id: session_id} in one query."""
    rows = conn.execute(
        "SELECT image_id, session_id, expires_at FROM locks"
    ).fetchall()
    return {
        r["image_id"]: r["session_id"]
        for r in rows
        if datetime.datetime.fromisoformat(r["expires_at"]) > now
    }


def list_images(conn: sqlite3.Connection, now: datetime.datetime) -> list[dict]:
    """List all images with their current lock holder (if any)."""
    rows = conn.execute("SELECT * FROM images ORDER BY id").fetchall()
    class_rows = conn.execute(
        "SELECT image_id, class_id FROM annotations GROUP BY image_id, class_id"
    ).fetchall()
    class_map: dict[int, list[int]] = {}
    for cr in class_rows:
        class_map.setdefault(cr["image_id"], []).append(cr["class_id"])
    lock_map = _live_lock_map(conn, now)
    result = []
    for r in rows:
        item = dict(r)
        item["locked_by"] = lock_map.get(r["id"])
        item["class_ids"] = sorted(class_map.get(r["id"], []))
        result.append(item)
    return result


def _filter_clause(
    include: list[int] | None, exclude: list[int] | None, only_unlabeled: bool
) -> tuple[str, list]:
    """Build a WHERE clause (and params) for class-based filtering."""
    clauses: list[str] = []
    params: list = []
    if only_unlabeled:
        clauses.append("NOT EXISTS (SELECT 1 FROM annotations a WHERE a.image_id = images.id)")
    else:
        if include:
            ph = ",".join("?" * len(include))
            clauses.append(
                f"EXISTS (SELECT 1 FROM annotations a WHERE a.image_id = images.id"
                f" AND a.class_id IN ({ph}))"
            )
            params += list(include)
        if exclude:
            ph = ",".join("?" * len(exclude))
            clauses.append(
                f"NOT EXISTS (SELECT 1 FROM annotations a WHERE a.image_id = images.id"
                f" AND a.class_id IN ({ph}))"
            )
            params += list(exclude)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_images_page(
    conn: sqlite3.Connection,
    now: datetime.datetime,
    *,
    limit: int,
    offset: int,
    include: list[int] | None = None,
    exclude: list[int] | None = None,
    only_unlabeled: bool = False,
) -> dict:
    """Return one filtered, paginated page of images plus the total count.

    Class filtering happens in SQL. Per-page class ids and live locks are each
    fetched in a single query, so cost is bounded by ``limit``, not the dataset.
    """
    where, params = _filter_clause(include, exclude, only_unlabeled)
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM images{where}", params
    ).fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM images{where} ORDER BY id LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    ids = [r["id"] for r in rows]
    class_map: dict[int, list[int]] = {}
    lock_map: dict[int, str] = {}
    if ids:
        ph = ",".join("?" * len(ids))
        for cr in conn.execute(
            f"SELECT image_id, class_id FROM annotations WHERE image_id IN ({ph})"
            f" GROUP BY image_id, class_id",
            ids,
        ):
            class_map.setdefault(cr["image_id"], []).append(cr["class_id"])
        for lr in conn.execute(
            f"SELECT image_id, session_id, expires_at FROM locks WHERE image_id IN ({ph})",
            ids,
        ):
            if datetime.datetime.fromisoformat(lr["expires_at"]) > now:
                lock_map[lr["image_id"]] = lr["session_id"]

    images = []
    for r in rows:
        item = dict(r)
        item["class_ids"] = sorted(class_map.get(r["id"], []))
        item["locked_by"] = lock_map.get(r["id"])
        images.append(item)
    return {"images": images, "total": total}


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
