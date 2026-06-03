import datetime

import pytest

from app import db


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()


@pytest.fixture
def make_image(conn):
    def _make(filename="img.jpg", width=100, height=100, source="upload"):
        cur = conn.execute(
            "INSERT INTO images (filename, rel_path, width, height, source, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (filename, f"images/{filename}", width, height, source, "2026-06-03T00:00:00Z"),
        )
        return cur.lastrowid

    return _make


@pytest.fixture
def now():
    return datetime.datetime(2026, 6, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)
