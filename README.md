# YOLO Annotator

A single-project, Roboflow-like bounding-box annotation tool. It loads a custom
YOLO `.pt` model on the server (GPU when available) for **label assist**, lets
several people annotate on one shared server without clobbering each other, and
exports a **YOLO11 detection dataset** on demand.

See the design spec: `docs/superpowers/specs/2026-06-03-yolo-annotator-design.md`.

## Features

- Draw / move / resize / delete bounding boxes on an HTML5 canvas.
- **Auto-label**: run your `.pt` model on an image and review draft boxes before saving.
- Classes come from the model (`model.names`).
- Ingest images via **upload**, by **scanning a server folder**, or by **importing a
  Roboflow YOLO zip** (`data.yaml` + `train`/`valid`/`test`). Imported labels are
  remapped to the model's classes by name; the original split is preserved.
- **Filter the gallery** by class (include / exclude, cycle by clicking) and an
  "only images with no boxes" toggle. Filtering and listing are paginated
  server-side (SQL), so the client stays responsive on large datasets (tested at
  15k images: ~53 KB per page, one page of DOM at a time).
- **Export** to `images/{train,val[,test]}` + `labels/{...}` + `data.yaml`, zipped.
  Images keep their imported split; un-split images are randomly split by `val_ratio`.
- Concurrency-safe: serialized GPU inference, per-image soft locks with heartbeat,
  optimistic-version saves (no silent overwrites).

## Requirements

- Python 3.10+
- A custom YOLO detection model (`.pt`). Defaults to `yolo11n.pt` (auto-downloaded)
  if you don't set one.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
# point at your trained weights; device auto-selects cuda when present
ANNOTATOR_MODEL_PATH=/path/to/best.pt ANNOTATOR_DEVICE=auto \
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# or: make run
```

Open http://localhost:8000.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ANNOTATOR_MODEL_PATH` | `yolo11n.pt` | Custom weights to load. |
| `ANNOTATOR_DEVICE` | `auto` | `auto` → `cuda` if available else `cpu`; or set `cpu`/`cuda:0`. |
| `ANNOTATOR_DATA_DIR` | `./data` | Stores images + `annotator.db`. |
| `ANNOTATOR_LOCK_TTL` | `60` | Edit-lock lifetime (seconds); refreshed by heartbeat. |
| `ANNOTATOR_SCAN_DIR` | — | Default folder for "Scan folder". |
| `ANNOTATOR_DEFAULT_VAL_RATIO` | `0.2` | Train/val split used by export. |

## Usage

1. **Upload** images, or **Scan folder** to register images already on the server.
2. Click an image (this claims an edit lock). Others see it as 🔒 read-only.
3. Pick a class, **drag** to draw a box; click to select, drag handles to resize,
   `Delete` to remove. **Auto-label** adds model suggestions (dashed) to review.
4. **Save**. A stale save (someone else saved first) is rejected with a reload prompt.
5. **Export YOLO11** downloads `dataset.zip` ready for `yolo train data=data.yaml`.

## Tests

```bash
make test
# the host has a ROS pytest plugin on PYTHONPATH; the Makefile sets
# PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 to avoid it.
```

## Architecture

- `app/main.py` — app factory, lifespan (model load + schema init), session cookie,
  static mount.
- `app/inference.py` — `ModelService`: loads YOLO, serializes `predict` behind an
  asyncio lock (one GPU access at a time).
- `app/repo.py` — image/annotation/class data access; optimistic-version saves.
- `app/locks.py` — per-image soft locks (claim / heartbeat / release / expiry).
- `app/storage.py` — upload + folder-scan ingest.
- `app/export.py` — split, `data.yaml`, label files, zip.
- `app/geometry.py` — pixel ↔ YOLO-normalized conversion + clamping.
- `static/` — vanilla-JS canvas frontend (no build step).
