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


def get_images_by_ids(conn: sqlite3.Connection, ids: Sequence[int]) -> list[dict]:
    """Fetch image rows for the given ids, preserving the order of ``ids``."""
    ids = list(ids)
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    rows = {
        r["id"]: dict(r)
        for r in conn.execute(f"SELECT * FROM images WHERE id IN ({ph})", ids)
    }
    return [rows[i] for i in ids if i in rows]


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
    include: list[int] | None,
    exclude: list[int] | None,
    only_unlabeled: bool,
    stage: str | None = None,
) -> tuple[str, list]:
    """Build a WHERE clause (and params) for class-based and stage filtering."""
    clauses: list[str] = []
    params: list = []
    if stage:
        clauses.append("images.stage = ?")
        params.append(stage)
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
    stage: str | None = None,
) -> dict:
    """Return one filtered, paginated page of images plus the total count.

    Class and stage filtering happen in SQL. Per-page class ids and live locks
    are each fetched in a single query, so cost is bounded by ``limit``, not the
    dataset.
    """
    where, params = _filter_clause(include, exclude, only_unlabeled, stage)
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


def set_stage(conn: sqlite3.Connection, image_ids: Sequence[int], stage: str) -> int:
    """Promote/demote images between the 'annotating' and 'database' stages.

    Returns the number of rows updated. A no-op for an empty id list.
    """
    ids = [int(i) for i in image_ids]
    if not ids:
        return 0
    ph = ",".join("?" * len(ids))
    cur = conn.execute(
        f"UPDATE images SET stage = ? WHERE id IN ({ph})", [stage, *ids]
    )
    return cur.rowcount


def set_stage_by_filter(
    conn: sqlite3.Connection,
    target_stage: str,
    *,
    source_stage: str | None = None,
    include: list[int] | None = None,
    exclude: list[int] | None = None,
    only_unlabeled: bool = False,
) -> int:
    """Move every image matching a filter to ``target_stage`` in one statement.

    Reuses the same ``_filter_clause`` as the gallery listing, so "move all
    matching" promotes exactly the set the user is currently viewing, across all
    pages, without shipping ids to the client. Returns the number of rows moved.
    """
    where, params = _filter_clause(include, exclude, only_unlabeled, source_stage)
    cur = conn.execute(f"UPDATE images SET stage = ?{where}", [target_stage, *params])
    return cur.rowcount


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


def set_embedding(
    conn: sqlite3.Connection, image_id: int, vector: bytes, dim: int, model: str
) -> None:
    """Store (or replace) an image's embedding vector."""
    conn.execute(
        "INSERT OR REPLACE INTO image_embeddings (image_id, vector, dim, model)"
        " VALUES (?, ?, ?, ?)",
        (image_id, vector, dim, model),
    )


def images_without_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All images that have no stored embedding yet (id + filename), ordered."""
    return conn.execute(
        "SELECT id, filename FROM images"
        " WHERE id NOT IN (SELECT image_id FROM image_embeddings) ORDER BY id"
    ).fetchall()


def get_embedding_row(conn: sqlite3.Connection, image_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT vector, dim FROM image_embeddings WHERE image_id = ?", (image_id,)
    ).fetchone()


def get_embedding_rows(
    conn: sqlite3.Connection, stage: str | None = None
) -> list[sqlite3.Row]:
    """Embedding rows (image_id + vector), optionally restricted to one stage."""
    if stage:
        return conn.execute(
            "SELECT e.image_id AS image_id, e.vector AS vector FROM image_embeddings e"
            " JOIN images i ON i.id = e.image_id WHERE i.stage = ? ORDER BY e.image_id",
            (stage,),
        ).fetchall()
    return conn.execute(
        "SELECT image_id, vector FROM image_embeddings ORDER BY image_id"
    ).fetchall()


def database_image_ids(conn: sqlite3.Connection) -> list[int]:
    """All image ids currently in the Database stage, ordered."""
    return [r["id"] for r in conn.execute(
        "SELECT id FROM images WHERE stage = 'database' ORDER BY id"
    )]


def split_counts(conn: sqlite3.Connection, stage: str = "database") -> dict:
    """Count images per split within a stage. Returns train/val/test/unassigned/total."""
    counts = {"train": 0, "val": 0, "test": 0, "unassigned": 0, "total": 0}
    for r in conn.execute(
        "SELECT split, COUNT(*) AS c FROM images WHERE stage = ? GROUP BY split", (stage,)
    ):
        key = r["split"] if r["split"] in ("train", "val", "test") else "unassigned"
        counts[key] += r["c"]
        counts["total"] += r["c"]
    return counts


def set_splits(conn: sqlite3.Connection, by_split: dict[str, Sequence[int]]) -> None:
    """Persist a train/val/test partition: ``{split_name: [image_id, ...]}``."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for split, ids in by_split.items():
            ids = [int(i) for i in ids]
            if not ids:
                continue
            ph = ",".join("?" * len(ids))
            conn.execute(f"UPDATE images SET split = ? WHERE id IN ({ph})", [split, *ids])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def database_images_with_boxes(conn: sqlite3.Connection) -> list[dict]:
    """Return Database-stage images with their boxes, for export.

    Only images the user has explicitly promoted to the 'database' stage are
    exported, regardless of label status.
    """
    rows = conn.execute(
        "SELECT * FROM images WHERE stage = 'database' ORDER BY id"
    ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["boxes"] = get_annotations(conn, r["id"])
        result.append(item)
    return result
