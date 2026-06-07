# Export Progress Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blocking `POST /api/export` (which builds, zips, and streams the dataset in one request) with a start/poll/download flow that reports per-file progress and lets the UI show a progress bar with an "X dari Y gambar" counter.

**Architecture:** `POST /api/export` validates and kicks off a background thread that runs the existing build→zip pipeline (still serialized by the existing `_export_lock`), updating a per-app progress dict (`app.state.export_state`) as it goes. `GET /api/export/progress` lets the UI poll that dict. `GET /api/export/download` serves the zip bytes captured in memory once the pipeline finishes — avoiding any race with a subsequent export overwriting the file on disk.

**Tech Stack:** FastAPI/Starlette, SQLite, vanilla JS frontend, pytest + FastAPI TestClient.

---

### Task 1: Add progress callbacks to the export pipeline functions

**Files:**
- Modify: `app/export.py:1-8` (imports), `app/export.py:100-143` (`write_dataset`, `zip_dataset`)
- Test: `tests/test_export_logic.py`

`write_dataset` and `zip_dataset` are pure, callback-free functions today. Add an optional `on_progress: Callable[[], None] | None = None` parameter to each so a caller can track per-file progress without coupling these functions to any UI/state concerns. `write_dataset` should call it once per image (after copying the image and writing its label file). `zip_dataset` should call it once per **image** file written to the archive — skip label `.txt` files and `data.yaml` so the count lines up with `write_dataset`'s (this is what makes a predictable `2 × N` total possible).

- [ ] **Step 1: Write the failing tests**

Open `tests/test_export_logic.py`. Replace the existing import block:

```python
from app.export import (
    split_images,
    build_data_yaml,
    format_label_lines,
    assign_splits,
    partition_three_way,
)
```

with (adds `write_dataset`, `zip_dataset`, and a PIL import for building real source images):

```python
from PIL import Image

from app.export import (
    split_images,
    build_data_yaml,
    format_label_lines,
    assign_splits,
    partition_three_way,
    write_dataset,
    zip_dataset,
)
```

Then append these tests to the end of the file:

```python
def _export_item(tmp_path, name, class_id):
    path = tmp_path / name
    Image.new("RGB", (8, 8), (10, 20, 30)).save(path, format="PNG")
    return {
        "src_path": str(path),
        "filename": name,
        "boxes": [{"class_id": class_id, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}],
    }


def test_write_dataset_calls_on_progress_once_per_image(tmp_path):
    items = [_export_item(tmp_path, f"img{i}.png", 0) for i in range(3)]
    calls = []
    write_dataset(
        tmp_path / "out", {0: "a"}, {"train": items, "val": [], "test": []},
        on_progress=lambda: calls.append(1),
    )
    assert len(calls) == 3


def test_write_dataset_works_without_on_progress(tmp_path):
    items = [_export_item(tmp_path, "img.png", 0)]
    out = write_dataset(tmp_path / "out", {0: "a"}, {"train": items, "val": [], "test": []})
    assert (out / "data.yaml").exists()


def test_zip_dataset_calls_on_progress_once_per_image_file(tmp_path):
    items = [_export_item(tmp_path, f"img{i}.png", 0) for i in range(3)]
    out_dir = write_dataset(tmp_path / "out", {0: "a"}, {"train": items, "val": [], "test": []})
    calls = []
    zip_dataset(out_dir, tmp_path / "out.zip", on_progress=lambda: calls.append(1))
    # Only the 3 image files count -- not the 3 label .txt files or data.yaml.
    assert len(calls) == 3


def test_zip_dataset_works_without_on_progress(tmp_path):
    items = [_export_item(tmp_path, "img.png", 0)]
    out_dir = write_dataset(tmp_path / "out", {0: "a"}, {"train": items, "val": [], "test": []})
    zip_path = zip_dataset(out_dir, tmp_path / "out.zip")
    assert zip_path.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_export_logic.py -k "on_progress" -q`
Expected: FAIL with `TypeError: write_dataset() got an unexpected keyword argument 'on_progress'` (and similarly for `zip_dataset`).

- [ ] **Step 3: Implement the callback parameters**

In `app/export.py`, change the typing import on line 8 from:

```python
from typing import Iterable, Mapping, Sequence
```

to:

```python
from typing import Callable, Iterable, Mapping, Sequence
```

Replace the `write_dataset` function (currently `app/export.py:100-131`) with:

```python
def write_dataset(
    out_dir: Path,
    class_names: Mapping[int, str],
    splits: Mapping[str, Sequence[dict]],
    on_progress: Callable[[], None] | None = None,
) -> Path:
    """Write the YOLO dataset tree under ``out_dir`` and return it.

    ``splits`` maps "train"/"val"/"test" to a list of items, each a dict with
    ``src_path`` (image file), ``filename`` and ``boxes`` (annotation dicts).
    Only non-empty splits are written. Images with no boxes still get an empty
    ``.txt`` (a valid YOLO background sample). ``on_progress``, if given, is
    called once per image after it's copied and labeled.
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for split_name, items in splits.items():
        if not items:
            continue
        img_dir = out_dir / "images" / split_name
        lbl_dir = out_dir / "labels" / split_name
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            shutil.copy2(item["src_path"], img_dir / item["filename"])
            stem = Path(item["filename"]).stem
            label_text = "\n".join(format_label_lines(item["boxes"]))
            if label_text:
                label_text += "\n"
            (lbl_dir / f"{stem}.txt").write_text(label_text)
            if on_progress is not None:
                on_progress()
    include_test = bool(splits.get("test"))
    (out_dir / "data.yaml").write_text(build_data_yaml(class_names, include_test=include_test))
    return out_dir
```

Replace the `zip_dataset` function (currently `app/export.py:134-143`) with:

```python
def zip_dataset(
    dataset_dir: Path,
    zip_path: Path,
    on_progress: Callable[[], None] | None = None,
) -> Path:
    """Zip an existing dataset directory, preserving its relative tree.

    ``on_progress``, if given, is called once per **image** file written to
    the archive -- label ``.txt`` files and ``data.yaml`` are excluded so the
    count matches the one ``write_dataset`` reports, keeping a combined
    progress total predictable.
    """
    dataset_dir = Path(dataset_dir)
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(dataset_dir.rglob("*")):
            if file.is_file():
                arcname = file.relative_to(dataset_dir)
                zf.write(file, arcname)
                if on_progress is not None and arcname.parts[0] == "images":
                    on_progress()
    return zip_path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_export_logic.py -q`
Expected: all tests in the file PASS (including the 4 new ones).

- [ ] **Step 5: Commit**

```bash
git add app/export.py tests/test_export_logic.py
git commit -m "feat: add on_progress callbacks to write_dataset/zip_dataset"
```

---

### Task 2: Add per-app export progress state

**Files:**
- Modify: `app/main.py` (in `create_app`), `app/deps.py`

The progress dict must live per-`FastAPI` app instance (not as a module-level global) so that tests get a clean slate each time `create_app()` runs (the existing `app`/`client` fixtures create a fresh app per test). This mirrors how `app.state.settings`/`model_service`/`embedding_service` are already wired up.

- [ ] **Step 1: Initialize the state dict in `create_app`**

In `app/main.py`, find this block inside `create_app` (currently around line 79-81):

```python
    app = FastAPI(title="YOLO Annotator", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.model_service = model_service
    app.state.embedding_service = embedding_service
```

Add one line after it so the block reads:

```python
    app = FastAPI(title="YOLO Annotator", lifespan=lifespan)
    app.state.settings = settings or load_settings()
    app.state.model_service = model_service
    app.state.embedding_service = embedding_service
    # Tracks the single in-flight (or most recently completed) dataset export
    # so the UI can poll progress instead of holding one request open for minutes.
    app.state.export_state = {"status": "idle", "current": 0, "total": 0, "error": None, "data": None}
```

- [ ] **Step 2: Add a dependency to fetch it**

In `app/deps.py`, add this function after `get_embedder` (currently ending around line 24):

```python
def get_export_state(request: Request) -> dict:
    """Mutable per-app dict tracking the single in-flight/most-recent export."""
    return request.app.state.export_state
```

- [ ] **Step 3: Run the existing test suite to confirm nothing broke**

Run: `python3 -m pytest tests/ -q`
Expected: `153 passed` (same as before this change — this step only adds new, unused state/dependency).

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/deps.py
git commit -m "feat: add per-app export progress state and dependency"
```

---

### Task 3: Rewrite the export endpoint into start/progress/download

**Files:**
- Modify: `app/routers/export.py` (entire file)
- Test: `tests/test_api.py`

This is the core of the feature: `POST /api/export` becomes a "start (or report already-running)" endpoint that returns immediately, a background thread runs the actual pipeline, `GET /api/export/progress` reports status, and `GET /api/export/download` serves the finished archive from memory.

- [ ] **Step 1: Write the failing API tests**

Open `tests/test_api.py`. We're replacing three existing export tests (`test_export_produces_valid_yolo_zip`, `test_export_preserves_imported_splits`, and `test_concurrent_exports_serialize_dataset_build_and_zip` — the last one is obsoleted because the new dedup check makes the race it guarded against structurally impossible) and keeping `test_export_without_database_images_is_400` as-is (its assertion — an immediate 400 — still holds; validation runs synchronously before the background job starts).

First, add a polling helper near the top of the file, right after the `_upload` helper (currently ending around line 84):

```python
def _run_export_to_completion(client, body=None, timeout=10):
    """POST /api/export, poll /api/export/progress to completion, return the
    final progress snapshot. Fails the test if it doesn't finish in time."""
    import time

    r = client.post("/api/export", json=body or {})
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("started", "running")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        progress = client.get("/api/export/progress").json()
        if progress["status"] in ("done", "error"):
            return progress
        time.sleep(0.02)
    pytest.fail("export did not finish within the timeout")


def _export_and_download(client, body=None):
    progress = _run_export_to_completion(client, body)
    assert progress["status"] == "done", progress.get("error")
    assert progress["current"] == progress["total"]
    dl = client.get("/api/export/download")
    assert dl.status_code == 200
    return dl
```

Now find `test_export_produces_valid_yolo_zip` (currently `tests/test_api.py:205-222`) and replace it with:

```python
def test_export_produces_valid_yolo_zip(client):
    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
    client.post("/api/images/stage", json={"image_ids": [img_id], "stage": "database"})
    dl = _export_and_download(client, {"val_ratio": 0.0, "seed": 1})
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    names = set(zf.namelist())
    assert "data.yaml" in names
    assert any(n.startswith("images/train/") for n in names)
    assert any(n.startswith("labels/train/") and n.endswith(".txt") for n in names)
    label_name = next(n for n in names if n.startswith("labels/train/"))
    assert zf.read(label_name).decode().strip() == "0 0.5 0.5 0.2 0.2"
    assert "nc: 2" in zf.read("data.yaml").decode()
```

Leave `test_export_without_database_images_is_400` untouched.

Now find `test_concurrent_exports_serialize_dataset_build_and_zip` (added in the previous fix) and replace the **entire test function** with:

```python
def test_export_progress_reaches_total(client):
    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
    client.post("/api/images/stage", json={"image_ids": [img_id], "stage": "database"})

    r = client.post("/api/export", json={"val_ratio": 0.0, "seed": 1})
    assert r.status_code == 200
    started = r.json()
    assert started["status"] == "started"
    assert started["total"] == 2  # 1 image: +1 in write_dataset, +1 in zip_dataset

    progress = _run_export_to_completion(client, body=None)
    assert progress["status"] == "done"
    assert progress["current"] == progress["total"] == 2
    assert progress["error"] is None


def test_export_download_before_any_completed_export_is_409(client):
    r = client.get("/api/export/download")
    assert r.status_code == 409


def test_export_download_serves_completed_archive(client):
    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
    client.post("/api/images/stage", json={"image_ids": [img_id], "stage": "database"})
    dl = _export_and_download(client, {"val_ratio": 0.0, "seed": 1})
    assert dl.headers["content-type"] == "application/zip"
    assert "dataset.zip" in dl.headers["content-disposition"]


def test_export_request_while_running_reports_running_without_starting_a_second_pipeline(client, monkeypatch):
    """A second POST while one export is in flight must not spawn its own
    pipeline run -- two runs racing on the shared export directory/zip path
    is exactly the FileNotFoundError bug this design prevents structurally."""
    import threading
    import time

    from app.routers import export as export_router

    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
    client.post("/api/images/stage", json={"image_ids": [img_id], "stage": "database"})

    real_write_dataset = export_router.export_logic.write_dataset
    starts = []
    starts_lock = threading.Lock()

    def tracking_write_dataset(*args, **kwargs):
        with starts_lock:
            starts.append(time.monotonic())
        time.sleep(0.2)  # widen the window so a second POST overlaps the run
        return real_write_dataset(*args, **kwargs)

    monkeypatch.setattr(export_router.export_logic, "write_dataset", tracking_write_dataset)

    r1 = client.post("/api/export", json={"val_ratio": 0.0, "seed": 1})
    assert r1.status_code == 200
    assert r1.json()["status"] == "started"

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not starts:
        time.sleep(0.01)
    assert starts, "background pipeline never started"

    r2 = client.post("/api/export", json={"val_ratio": 0.0, "seed": 1})
    assert r2.status_code == 200
    assert r2.json()["status"] == "running"

    _run_export_to_completion(client)
    assert len(starts) == 1, "a second POST spawned its own export pipeline run"


def test_export_failure_surfaces_error_and_does_not_stick(client, monkeypatch):
    """A pipeline failure must report status=='error' with a message, and must
    not leave the dedup/lock state stuck so a later export can still run."""
    from app.routers import export as export_router

    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
    client.post("/api/images/stage", json={"image_ids": [img_id], "stage": "database"})

    real_write_dataset = export_router.export_logic.write_dataset
    calls = [0]

    def flaky_write_dataset(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("disk exploded")
        return real_write_dataset(*args, **kwargs)

    monkeypatch.setattr(export_router.export_logic, "write_dataset", flaky_write_dataset)

    progress = _run_export_to_completion(client, {"val_ratio": 0.0, "seed": 1})
    assert progress["status"] == "error"
    assert "disk exploded" in progress["error"]

    # The lock/dedup state must not be stuck -- a retry should run for real.
    dl = _export_and_download(client, {"val_ratio": 0.0, "seed": 1})
    assert dl.status_code == 200
```

Finally, find `test_export_preserves_imported_splits` (currently `tests/test_api.py:343-355`) and replace its body's export+assert lines:

```python
    r = client.post("/api/export", json={})
    assert r.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
```

with:

```python
    dl = _export_and_download(client, {})
    names = set(zipfile.ZipFile(io.BytesIO(dl.content)).namelist())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_api.py -k export -q`
Expected: FAIL — `POST /api/export` still returns the zip synchronously (`status_code == 200` but `r.json()` raising because the body is binary, or `started["status"]` KeyError), and `/api/export/progress`/`/api/export/download` return 404 (routes don't exist yet).

- [ ] **Step 3: Rewrite the router**

Replace the entire contents of `app/routers/export.py` with:

```python
"""Classes and YOLO11 dataset export."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app import export as export_logic
from app import repo
from app.deps import get_conn, get_export_state, get_settings
from app.models import ExportRequest

router = APIRouter(prefix="/api")

# write_dataset() deletes and rebuilds the shared export directory, then
# zip_dataset() walks it; overlapping pipeline runs would have one rebuild
# the tree while another is mid-walk, raising FileNotFoundError. Serialize
# the whole build-then-zip pipeline so each export sees a consistent tree.
_export_lock = threading.Lock()

# Guards reads/writes of the per-app progress dict so the polling endpoint
# never observes a half-updated snapshot from the background worker thread.
_state_lock = threading.Lock()


def _snapshot(state: dict) -> dict:
    with _state_lock:
        return dict(state)


def _try_start(state: dict, total: int) -> bool:
    """Atomically claim the running slot. False if one is already in flight."""
    with _state_lock:
        if state["status"] == "running":
            return False
        state.update(status="running", current=0, total=total, error=None, data=None)
        return True


def _increment(state: dict) -> None:
    with _state_lock:
        state["current"] += 1


def _finish(state: dict, **fields) -> None:
    with _state_lock:
        state.update(fields)


def _run_export(state: dict, out_dir, zip_path, classes, splits) -> None:
    try:
        with _export_lock:
            export_logic.write_dataset(out_dir, classes, splits, on_progress=lambda: _increment(state))
            export_logic.zip_dataset(out_dir, zip_path, on_progress=lambda: _increment(state))
            data = zip_path.read_bytes()
        _finish(state, status="done", data=data)
    except Exception as exc:
        _finish(state, status="error", error=str(exc))


@router.get("/classes")
def get_classes(conn=Depends(get_conn)):
    return {"classes": repo.get_classes(conn)}


@router.post("/export")
def export_dataset(
    body: ExportRequest,
    conn=Depends(get_conn),
    settings=Depends(get_settings),
    state=Depends(get_export_state),
):
    snapshot = _snapshot(state)
    if snapshot["status"] == "running":
        return {"status": "running", "current": snapshot["current"], "total": snapshot["total"]}

    database = repo.database_images_with_boxes(conn)
    if not database:
        raise HTTPException(400, "no Database images to export")

    val_ratio = body.val_ratio if body.val_ratio is not None else settings.default_val_ratio
    assigned = export_logic.assign_splits(database, val_ratio, body.seed)
    by_id = {r["id"]: r for r in database}

    def to_item(image_id: int) -> dict:
        r = by_id[image_id]
        return {
            "src_path": str(settings.images_dir / r["filename"]),
            "filename": r["filename"],
            "boxes": r["boxes"],
        }

    splits = {name: [to_item(i) for i in ids] for name, ids in assigned.items()}
    classes = repo.get_classes(conn)
    total = sum(len(items) for items in splits.values()) * 2

    if not _try_start(state, total):
        snapshot = _snapshot(state)
        return {"status": "running", "current": snapshot["current"], "total": snapshot["total"]}

    out_dir = settings.data_dir / "export"
    zip_path = settings.data_dir / "dataset.zip"
    threading.Thread(
        target=_run_export, args=(state, out_dir, zip_path, classes, splits), daemon=True
    ).start()
    return {"status": "started", "total": total}


@router.get("/export/progress")
def export_progress(state=Depends(get_export_state)):
    snapshot = _snapshot(state)
    return {
        "status": snapshot["status"],
        "current": snapshot["current"],
        "total": snapshot["total"],
        "error": snapshot["error"],
    }


@router.get("/export/download")
def export_download(state=Depends(get_export_state)):
    snapshot = _snapshot(state)
    if snapshot["status"] != "done" or snapshot["data"] is None:
        raise HTTPException(409, "no completed export available to download")
    return Response(
        content=snapshot["data"],
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="dataset.zip"'},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_api.py -k export -q`
Expected: all export-related tests PASS (8 tests: the 6 above plus `test_export_without_database_images_is_400` and `test_export_preserves_imported_splits`).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all tests PASS. The suite is now 4 tests larger than the pre-Task-1 baseline in `tests/test_export_logic.py` (Task 1's new tests) and net 4 larger in `tests/test_api.py` (5 new export tests replacing the 1 removed concurrency test).

- [ ] **Step 6: Commit**

```bash
git add app/routers/export.py tests/test_api.py
git commit -m "feat: split dataset export into start/progress/download endpoints"
```

---

### Task 4: Add the progress UI markup and styles

**Files:**
- Modify: `static/index.html:32` (header actions), `static/css/app.css`

Add a hidden progress indicator and a hidden download button next to the existing "Export YOLO11" button in the header toolbar — visible from every view (the header is shared across Annotate/Database/Splits).

- [ ] **Step 1: Add the markup**

In `static/index.html`, find this line (currently line 32):

```html
        <button id="export" class="btn primary">Export YOLO11</button>
```

Replace it with:

```html
        <button id="export" class="btn primary">Export YOLO11</button>
        <span id="export-progress" class="export-progress" hidden>
          <progress id="export-progress-bar" max="100" value="0"></progress>
          <span id="export-progress-text" class="muted-note"></span>
        </span>
        <button id="export-download" class="btn primary" hidden>Unduh dataset.zip</button>
```

- [ ] **Step 2: Add styles**

In `static/css/app.css`, find the `.muted-note` rule (currently around line 264):

```css
.muted-note { color: var(--muted); font-size: 12px; margin: 0; }
```

Add this rule directly after it:

```css
.export-progress { display: flex; align-items: center; gap: 6px; }
.export-progress progress { width: 120px; }
```

- [ ] **Step 3: Verify the page still loads**

Run the dev server (see the project's `run` skill or your usual startup command) and open the app in a browser. Confirm the header looks unchanged (the new elements are `hidden`).

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/css/app.css
git commit -m "feat: add export progress bar and download button markup"
```

---

### Task 5: Wire up the polling flow in the frontend

**Files:**
- Modify: `static/js/api.js` (add URL helpers), `static/js/app.js` (`init`, `doExport`)

- [ ] **Step 1: Add API URL helpers**

In `static/js/api.js`, find:

```js
  exportUrl() {
    return "api/export";
  },
```

Replace it with:

```js
  exportUrl() {
    return "api/export";
  },
  exportProgressUrl() {
    return "api/export/progress";
  },
  exportDownloadUrl() {
    return "api/export/download";
  },
```

- [ ] **Step 2: Register the new elements**

In `static/js/app.js`, inside `init()`, find:

```js
  els.export = $("export");
```

Replace it with:

```js
  els.export = $("export");
  els.exportProgress = $("export-progress");
  els.exportProgressBar = $("export-progress-bar");
  els.exportProgressText = $("export-progress-text");
  els.exportDownload = $("export-download");
```

Find:

```js
  els.export.onclick = doExport;
```

Replace it with:

```js
  els.export.onclick = doExport;
  els.exportDownload.onclick = downloadExportedDataset;
```

- [ ] **Step 3: Replace `doExport` with the polling flow**

Find the existing `doExport` function (currently `static/js/app.js:803-826`):

```js
async function doExport() {
  setStatus("Building dataset…", "");
  try {
    const res = await fetch(api.exportUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "dataset.zip";
    a.click();
    URL.revokeObjectURL(url);
    setStatus("Dataset exported", "ok");
  } catch (e) {
    setStatus("Export failed: " + e.message, "err");
  }
}
```

Replace it with:

```js
let exportPollTimer = null;

function stopExportPolling() {
  if (exportPollTimer) {
    clearInterval(exportPollTimer);
    exportPollTimer = null;
  }
}

function showExportProgress(current, total) {
  els.export.hidden = true;
  els.exportDownload.hidden = true;
  els.exportProgress.hidden = false;
  els.exportProgressBar.max = total || 1;
  els.exportProgressBar.value = current;
  els.exportProgressText.textContent = `${current} dari ${total} gambar`;
}

function showExportDownload() {
  stopExportPolling();
  els.exportProgress.hidden = true;
  els.export.hidden = true;
  els.exportDownload.hidden = false;
}

function resetExportUI() {
  stopExportPolling();
  els.exportProgress.hidden = true;
  els.exportDownload.hidden = true;
  els.export.hidden = false;
}

async function pollExportProgress() {
  try {
    const res = await fetch(api.exportProgressUrl());
    if (!res.ok) throw new Error(res.statusText);
    const p = await res.json();
    if (p.status === "done") {
      showExportDownload();
      setStatus("Dataset siap diunduh", "ok");
    } else if (p.status === "error") {
      resetExportUI();
      setStatus("Export failed: " + (p.error || "unknown error"), "err");
    } else {
      showExportProgress(p.current, p.total);
    }
  } catch (e) {
    resetExportUI();
    setStatus("Export failed: " + e.message, "err");
  }
}

function startExportPolling() {
  stopExportPolling();
  pollExportProgress();
  exportPollTimer = setInterval(pollExportProgress, 1000);
}

async function doExport() {
  setStatus("Memulai export…", "");
  try {
    const res = await fetch(api.exportUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.statusText);
    showExportProgress(data.current || 0, data.total || 0);
    startExportPolling();
  } catch (e) {
    setStatus("Export failed: " + e.message, "err");
  }
}

async function downloadExportedDataset() {
  setStatus("Mengunduh…", "");
  try {
    const res = await fetch(api.exportDownloadUrl());
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "dataset.zip";
    a.click();
    URL.revokeObjectURL(url);
    setStatus("Dataset exported", "ok");
    resetExportUI();
  } catch (e) {
    setStatus("Download failed: " + e.message, "err");
  }
}
```

- [ ] **Step 4: Manually verify in the browser**

Start the dev server, open the app, upload a few images, annotate and move them to "Database", then click "Export YOLO11". Confirm:
- The button is replaced by a progress bar that fills up with a "X dari Y gambar" counter.
- When it reaches the total, the bar is replaced by an "Unduh dataset.zip" button.
- Clicking that button downloads `dataset.zip` and the UI resets back to the "Export YOLO11" button.
- Clicking "Export YOLO11" again from the **Splits** page also shows the same progress UI in the header (it's shared across views).

- [ ] **Step 5: Commit**

```bash
git add static/js/api.js static/js/app.js
git commit -m "feat: poll export progress and add explicit download step in the UI"
```

---

### Task 6: Final full-suite check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire backend test suite**

Run: `python3 -m pytest tests/ -q`
Expected: all tests PASS.

- [ ] **Step 2: Review the diff**

Run: `git log --oneline -6` and `git diff origin/main..HEAD --stat`
Confirm the 5 feature commits from Tasks 1, 2, 3, 4, 5 are present and the diff touches only the files listed in this plan.

- [ ] **Step 3: Push**

Ask the user before pushing — `git push origin main` affects the shared remote.
