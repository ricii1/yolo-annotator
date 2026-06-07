# Export progress reporting

## Problem

`POST /api/export` builds a YOLO dataset tree (copying every Database-stage
image and writing a label file per image), zips it, and returns the archive —
all within a single blocking request. For datasets in the thousands of images
this can take minutes. The user has no visibility into how far along the
process is, and a long-held HTTP request risks client/proxy timeouts.

## Goals

- Show the user a combined progress bar with an "X of Y images" counter while
  an export runs.
- Don't hold an HTTP request open for the whole export — start it, then poll.
- Surface failures with an error message.
- Let the user trigger the download once the archive is ready (no
  auto-download).

## Non-goals

- Cancelling an in-progress export.
- Supporting multiple concurrent exports (the existing `_export_lock` already
  serializes exports; this design keeps that single-export-at-a-time reality
  and tracks progress for "the" export rather than per-job).

## Architecture

A single, in-memory, server-global progress state replaces the current
synchronous build-then-respond flow. Three endpoints replace the current
`POST /api/export`:

- **`POST /api/export`** — validates that there are Database-stage images with
  boxes (same 400 check as today), resets the global state to `running`, spawns
  a background thread that runs the build+zip pipeline, and returns
  immediately with `{"status": "started"}`. If an export is already running,
  returns the current state instead of starting a second one.
- **`GET /api/export/progress`** — returns the current global state:
  `{"status": "idle"|"running"|"done"|"error", "current": int, "total": int, "error": str|null}`.
- **`GET /api/export/download`** — once `status == "done"`, returns the zip
  bytes captured in memory by the worker (mirrors the read-into-memory fix
  already applied to `/api/export`, so a subsequent export overwriting
  `dataset.zip` on disk can't corrupt an in-flight download). Returns 409 if
  no completed export is available.

### Global state

```python
_export_state = {"status": "idle", "current": 0, "total": 0, "error": None, "data": None}
_state_lock = threading.Lock()
```

Guarded by `_state_lock` (separate from `_export_lock`, which still serializes
the actual filesystem work). The worker thread updates `current`/`status`
under the lock as it progresses; `GET /api/export/progress` reads a snapshot
under the same lock.

### Background worker

Runs inside `_export_lock` (as today), executing the existing
`write_dataset` → `zip_dataset` → `read_bytes` sequence, but passing an
`on_progress` callback through to both functions. On success, stores the zip
bytes in `_export_state["data"]` and sets `status = "done"`. On any exception,
sets `status = "error"` and `error = str(exc)`.

## Progress accounting

Total work is defined as **2 × N**, where N is the number of images being
exported (known upfront from the assigned splits, before the pipeline starts):

- `write_dataset` calls `on_progress()` once per image after it copies the
  image file and writes its label `.txt` — contributing N increments.
- `zip_dataset` calls `on_progress()` once per **image** file it writes to the
  archive (identified by its arcname living under `images/`) — contributing
  another N increments. Label files and `data.yaml` are zipped without
  incrementing, since counting them would make the upfront total
  unpredictable for negligible visual benefit.

This keeps the total computable before the pipeline starts and the bar
progresses smoothly and monotonically through both phases.

`write_dataset` and `zip_dataset` (in `app/export.py`) gain an optional
`on_progress: Callable[[], None] | None = None` parameter (default `None` /
no-op), keeping them pure and independently testable — the router is the only
place that wires the callback to the shared state.

## Frontend

A small progress element (bar + "X dari Y gambar" counter) is added to the
header toolbar near the existing "Export YOLO11" button — visible from every
view, since export can be triggered from the header or the Splits page.

`doExport()` in `static/js/app.js` changes from "POST and download the blob"
to:

1. `POST /api/export` → on success, show the progress element at 0/N.
2. Poll `GET /api/export/progress` every ~1s, updating the bar and counter
   text from the response.
3. On `status == "done"`: stop polling, hide the bar, show a "Unduh
   dataset.zip" button. Clicking it fetches `GET /api/export/download` and
   triggers the browser download (reusing the existing blob/anchor-click
   logic), then resets the UI back to the export button.
4. On `status == "error"`: stop polling, hide the bar, surface the message via
   `setStatus(..., "err")`.

If `POST /api/export` reports an export is already running (e.g. the user
re-clicks, or another tab started one), the UI starts polling immediately
instead of erroring — picking up the in-progress job's state.

## Testing

- `app/export.py`: unit tests verifying `on_progress` is invoked exactly N
  times by `write_dataset` and N times (image files only) by `zip_dataset`,
  and that omitting the callback still works (back-compat with existing
  callers/tests).
- `app/routers/export.py` / API tests:
  - `POST /api/export` returns immediately with `{"status": "started"}` and
    `GET /api/export/progress` reflects `running` → `done` with `current`
    reaching `total`.
  - `GET /api/export/download` returns the zip only after `done`, and 409
    before any export has completed.
  - Error path: a forced failure mid-pipeline surfaces `status == "error"`
    with a message, and does not leave the global lock stuck (a subsequent
    export can still start).
  - Re-`POST`ing while one is `running` doesn't start a second pipeline run
    (reuses the existing concurrency test's instrumentation pattern).
