# YOLO Annotator — Design Spec

**Date:** 2026-06-03
**Status:** Approved

A single-project, Roboflow-like image annotation tool for **bounding box / object
detection**. Loads a custom YOLO `.pt` model on the server (GPU when available) to
assist labeling, lets multiple users annotate concurrently on one shared server
(no auth) without clobbering each other, and exports the result on demand as a
YOLO11 detection dataset.

## Goals

- Draw, edit, and delete bounding boxes on a Roboflow-like canvas (zoom/pan, labels).
- **Label assist:** run the custom `.pt` model on an image and get draft boxes the
  user can accept / correct / delete before saving.
- **Classes** come from the loaded model (`model.names`); the project is fixed to
  those classes.
- **Ingest** images two ways: upload via UI, and scan an existing server folder.
- **Export** on demand to a YOLO11 dataset (`images/{train,val}`,
  `labels/{train,val}`, `data.yaml`) with a train/val split, downloadable as a zip.
- **Concurrency-safe** for a small team on one server: serialized GPU inference,
  per-image soft locks, optimistic-version saves.

## Non-Goals (YAGNI)

- No authentication / user accounts (identity = random session cookie).
- No multi-project support — exactly one project.
- No segmentation / polygons / OBB / keypoints — bounding boxes only.
- No model training inside the app (export is consumed by external YOLO training).
- No cloud storage — local filesystem + SQLite only.

## Stack

- **Backend:** Python, FastAPI, Uvicorn.
- **Model:** Ultralytics YOLO loaded from a `.pt` path at startup. Device resolved
  as `cuda` if available else `cpu` (configurable).
- **State:** SQLite in WAL mode (concurrent readers + single writer; fine for a
  small team).
- **Frontend:** Static HTML + CSS + vanilla JS using the HTML5 Canvas. Served by
  FastAPI. No Node/npm build step.

## Project Structure

```
yolo-annotator/
├── app/
│   ├── main.py            # FastAPI app, lifespan model load, static mount, routers
│   ├── config.py          # Settings from env: model path, data dir, split, lock TTL, device
│   ├── db.py              # SQLite (WAL) connection factory + schema init
│   ├── models.py          # pydantic schemas for requests/responses
│   ├── inference.py       # ModelService: load YOLO, serialized predict()
│   ├── storage.py         # image ingest (upload + folder scan), path helpers
│   ├── locks.py           # soft per-image locks (session + heartbeat TTL)
│   ├── geometry.py        # pixel<->YOLO-normalized conversion + clamping
│   ├── export.py          # build YOLO11 dataset dir + data.yaml + zip
│   └── routers/{images,annotations,assist,export,locks}.py
├── static/{index.html, css/app.css, js/{api.js,canvas.js,app.js}}
├── data/                  # images + annotator.db (gitignored)
├── tests/
├── requirements.txt
└── README.md
```

## Data Model (SQLite, WAL)

- **images**: `id INTEGER PK, filename TEXT UNIQUE, rel_path TEXT, width INT,
  height INT, source TEXT(upload|folder), status TEXT(unlabeled|labeled|skipped)
  DEFAULT unlabeled, version INT DEFAULT 0, created_at TEXT`
- **annotations**: `id INTEGER PK, image_id INT FK, class_id INT, cx REAL, cy REAL,
  w REAL, h REAL, source TEXT(manual|assist), created_at TEXT` — all coords
  normalized 0..1 (YOLO format).
- **locks**: `image_id INTEGER PK FK, session_id TEXT, expires_at TEXT`
- **classes**: `class_id INTEGER PK, name TEXT` — populated from `model.names` at
  startup; the single source of truth for `data.yaml`.

`version` on `images` is the optimistic-concurrency token (bumped on every save).
Label `.txt` files are produced only at export time, never per-save.

## Key Flows

### Ingest
- **Upload:** multipart files → validate is-image via Pillow → store under
  `data/images/<filename>` (de-dup name collisions) → read width/height → insert
  row with `source=upload`. Non-images → reported as skipped (422 detail per file).
- **Scan folder:** walk a configured/posted folder → for image files not already in
  DB, copy/register under data dir → insert with `source=folder`.

### Annotate
1. Open image → `POST /locks/{image_id}` claims a soft lock (session cookie, TTL).
   If held by another live session → 423 Locked, UI shows "🔒 sedang diedit".
2. Load image + its annotations + current `version`.
3. User draws/edits/deletes boxes on canvas.
4. **Save:** `PUT /images/{id}/annotations` with full box set + `version`. Server,
   in one transaction: verify `version` matches (else 409), delete old annotations,
   insert new, bump `version`, set `status=labeled`. Refresh lock.
5. Heartbeat `POST /locks/{id}/heartbeat` extends TTL while editing; lock auto-expires
   on tab close.

### Label assist
- `POST /assist/predict {image_id, conf}` → ModelService runs `model.predict` behind
  a single asyncio lock (serialized GPU access) → returns boxes
  `[{class_id, cx, cy, w, h, conf}]` normalized. Frontend shows them as **draft**
  boxes (distinct color) the user accepts/edits/deletes before saving. Drafts are
  not persisted until Save.

### Export
- `POST /export {val_ratio=0.2, seed=42}` → take all `status=labeled` images →
  deterministic seeded shuffle → split train/val → write:
  ```
  export/
    images/train/*  images/val/*
    labels/train/*.txt  labels/val/*.txt   (YOLO: "class_id cx cy w h" per box)
    data.yaml         (path, train, val, nc, names)
  ```
  → zip → stream download. Images with zero boxes still emit an empty `.txt`
  (valid YOLO background sample). Error 400 if no labeled images.

## Concurrency

- **GPU:** one `asyncio.Lock` (or single-worker queue) wraps `model.predict`;
  inference requests are serialized so the GPU is never accessed re-entrantly.
- **Edit conflicts:** per-image soft lock keyed by random `session_id` cookie, with
  `expires_at` TTL (default 60s) refreshed by heartbeat. Expired/own locks are
  re-claimable. Gallery marks locked images.
- **Save safety:** optimistic `version` check inside a single SQLite transaction —
  a stale save returns 409 instead of silently overwriting.
- **SQLite:** WAL mode + short `busy_timeout`; all writes via a transaction helper.

## Error Handling

- Model fails to load at startup → fail fast with a clear message naming the `.pt` path.
- Inference error → 503; manual annotation still works.
- Stale save → 409 with current version; UI offers reload.
- Locked image → 423 with holder/expiry info.
- Bad/corrupt upload → 422, per-file skip report.
- Export with no labeled images → 400.

## Testing

- **Unit:** `geometry` pixel↔normalized round-trip + clamping; split determinism;
  `data.yaml` generation; lock claim/expiry/steal; optimistic-version logic.
- **Integration (FastAPI TestClient, model mocked):** ingest→annotate→save→export
  yields a valid YOLO tree; assist endpoint returns boxes from a mocked model;
  two-client race → exactly one 409; lock contention → 423.
- Inference is mocked in tests (no GPU required in CI). `ModelService` exposes a
  seam so tests inject a fake predictor.

## Configuration (env)

- `ANNOTATOR_MODEL_PATH` (default `yolo11n.pt`) — custom weights.
- `ANNOTATOR_DATA_DIR` (default `./data`).
- `ANNOTATOR_DEVICE` (default `auto` → cuda else cpu).
- `ANNOTATOR_LOCK_TTL` (default `60` seconds).
- `ANNOTATOR_SCAN_DIR` (optional default folder for "Scan folder").
- `ANNOTATOR_DEFAULT_VAL_RATIO` (default `0.2`).
