"""Per-image soft locks with heartbeat TTL.

A lock is identified by a random ``session_id`` (a cookie). Locks expire after a
TTL unless refreshed by a heartbeat, so a closed browser tab frees the image
automatically. The owner may always re-claim; others may claim only once the
existing lock has expired.
"""
from __future__ import annotations

import datetime
import sqlite3


def _parse(ts: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts)


def lock_holder(conn: sqlite3.Connection, image_id: int, now: datetime.datetime) -> str | None:
    """Return the session id of the live lock holder, or None if free/expired."""
    row = conn.execute(
        "SELECT session_id, expires_at FROM locks WHERE image_id = ?", (image_id,)
    ).fetchone()
    if row is None:
        return None
    if _parse(row["expires_at"]) <= now:
        return None
    return row["session_id"]


def claim_lock(
    conn: sqlite3.Connection,
    image_id: int,
    session_id: str,
    now: datetime.datetime,
    ttl: int,
) -> bool:
    """Claim or refresh a lock. Returns False if another session holds it live."""
    holder = lock_holder(conn, image_id, now)
    if holder is not None and holder != session_id:
        return False
    expires_at = (now + datetime.timedelta(seconds=ttl)).isoformat()
    conn.execute(
        "INSERT INTO locks (image_id, session_id, expires_at) VALUES (?, ?, ?)"
        " ON CONFLICT(image_id) DO UPDATE SET session_id = excluded.session_id,"
        " expires_at = excluded.expires_at",
        (image_id, session_id, expires_at),
    )
    return True


def heartbeat(
    conn: sqlite3.Connection,
    image_id: int,
    session_id: str,
    now: datetime.datetime,
    ttl: int,
) -> bool:
    """Extend a live lock the caller owns. Returns False otherwise."""
    if lock_holder(conn, image_id, now) != session_id:
        return False
    expires_at = (now + datetime.timedelta(seconds=ttl)).isoformat()
    conn.execute(
        "UPDATE locks SET expires_at = ? WHERE image_id = ? AND session_id = ?",
        (expires_at, image_id, session_id),
    )
    return True


def release_lock(conn: sqlite3.Connection, image_id: int, session_id: str) -> None:
    """Release a lock the caller owns. No-op for non-owners."""
    conn.execute(
        "DELETE FROM locks WHERE image_id = ? AND session_id = ?", (image_id, session_id)
    )
