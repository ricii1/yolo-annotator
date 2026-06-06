# Nginx Subpath Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the YOLO Annotator deployable at any nginx subpath (e.g. `/annotator/`) by adding a `ROOT_PATH` env var that injects a `<base href>` into the served HTML, combined with making all frontend URLs relative.

**Architecture:** Three-layer change — (1) `Settings` gains `root_path` field, (2) `main.py` serves a modified `index.html` with the correct `<base href>` injected, (3) all `/api/…` and `/js/…` references in the frontend become relative URLs so the browser resolves them via the base href.

**Tech Stack:** Python stdlib `os`, FastAPI `HTMLResponse`, vanilla JS `fetch`, HTML `<base>` element.

---

## File Map

| File | Change |
|------|--------|
| `app/config.py` | Add `root_path: str` to `Settings`; normalise in `load_settings()` |
| `app/main.py` | Cache modified index.html in lifespan; add `GET /` route returning `HTMLResponse` |
| `static/index.html` | Add `<base href="/">` to `<head>`; make all asset paths relative |
| `static/js/api.js` | Remove leading `/` from all API URL strings |
| `tests/test_config.py` | Tests for `root_path` normalisation |
| `tests/test_api.py` | Test that `GET /` injects the correct `<base href>` |

---

### Task 1: Add `root_path` to Settings

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

  Open `tests/test_config.py` and append:

  ```python
  from app.config import load_settings


  def test_root_path_defaults_to_slash(monkeypatch):
      monkeypatch.delenv("ROOT_PATH", raising=False)
      s = load_settings()
      assert s.root_path == "/"


  def test_root_path_reads_from_env(monkeypatch):
      monkeypatch.setenv("ROOT_PATH", "/annotator/")
      s = load_settings()
      assert s.root_path == "/annotator/"


  def test_root_path_auto_appends_trailing_slash(monkeypatch):
      monkeypatch.setenv("ROOT_PATH", "/annotator")
      s = load_settings()
      assert s.root_path == "/annotator/"


  def test_root_path_auto_prepends_leading_slash(monkeypatch):
      monkeypatch.setenv("ROOT_PATH", "annotator/")
      s = load_settings()
      assert s.root_path == "/annotator/"


  def test_root_path_strips_double_slashes(monkeypatch):
      monkeypatch.setenv("ROOT_PATH", "//annotator//")
      s = load_settings()
      assert s.root_path == "/annotator/"
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```bash
  python3 -m pytest tests/test_config.py -k "root_path" -x --tb=short -q
  ```

  Expected: FAIL — `Settings` has no `root_path` attribute.

- [ ] **Step 3: Add `root_path` to `Settings` and `load_settings()`**

  In `app/config.py`, add `root_path: str` to the `Settings` dataclass (after `embed_model`):

  ```python
  @dataclass
  class Settings:
      model_path: str
      data_dir: Path
      device: str
      lock_ttl: int
      scan_dir: str | None
      default_val_ratio: float
      embed_model: str
      root_path: str
  ```

  At the end of `load_settings()`, add the `root_path` computation before the `return Settings(...)` line. First add this helper at the bottom of `load_settings()`:

  ```python
  def load_settings() -> Settings:
      load_dotenv()
      data_dir = Path(os.environ.get("ANNOTATOR_DATA_DIR", "./data")).resolve()
      root_path = os.environ.get("ROOT_PATH", "/")
      if not root_path.startswith("/"):
          root_path = "/" + root_path
      if not root_path.endswith("/"):
          root_path = root_path + "/"
      while "//" in root_path:
          root_path = root_path.replace("//", "/")
      return Settings(
          model_path=os.environ.get("ANNOTATOR_MODEL_PATH", "yolo11n.pt"),
          data_dir=data_dir,
          device=os.environ.get("ANNOTATOR_DEVICE", "auto"),
          lock_ttl=int(os.environ.get("ANNOTATOR_LOCK_TTL", "60")),
          scan_dir=os.environ.get("ANNOTATOR_SCAN_DIR") or None,
          default_val_ratio=float(os.environ.get("ANNOTATOR_DEFAULT_VAL_RATIO", "0.2")),
          embed_model=os.environ.get("ANNOTATOR_EMBED_MODEL", "openai/clip-vit-base-patch32"),
          root_path=root_path,
      )
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```bash
  python3 -m pytest tests/test_config.py -k "root_path" -x --tb=short -q
  ```

  Expected: 5 passed.

- [ ] **Step 5: Run full suite to confirm no regression**

  ```bash
  python3 -m pytest tests/ -x --tb=short -q
  ```

  Expected: all 144 passed.

- [ ] **Step 6: Commit**

  ```bash
  git add app/config.py tests/test_config.py
  git commit -m "feat: add root_path to Settings for nginx subpath support"
  ```

---

### Task 2: Update `index.html` — add `<base href>` and relative asset paths

**Files:**
- Modify: `static/index.html`

> No automated test for this task — it's a static file change. Correctness is verified by the integration test in Task 4 (which checks the HTML returned by `GET /`).

- [ ] **Step 1: Add `<base href="/">` to `<head>`**

  In `static/index.html`, the current `<head>` block starts:
  ```html
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>YOLO Annotator</title>
    <link rel="stylesheet" href="/css/app.css" />
  ```

  Replace it with:
  ```html
    <meta charset="UTF-8" />
    <base href="/" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>YOLO Annotator</title>
    <link rel="stylesheet" href="css/app.css" />
  ```

  Note: `<base>` must come before any resource reference. `href` on the `<link>` loses its leading `/`.

- [ ] **Step 2: Make all script paths relative**

  Near the end of `static/index.html`, find the script block:
  ```html
    <script src="/js/api.js"></script>
    <script src="/js/canvas.js"></script>
    <script src="/js/grid.js"></script>
    <script src="/js/app.js"></script>
    <script src="/js/gallery.js"></script>
    <script src="/js/database.js"></script>
    <script src="/js/splits.js"></script>
    <script src="/js/router.js"></script>
  ```

  Replace with (remove all leading `/`):
  ```html
    <script src="js/api.js"></script>
    <script src="js/canvas.js"></script>
    <script src="js/grid.js"></script>
    <script src="js/app.js"></script>
    <script src="js/gallery.js"></script>
    <script src="js/database.js"></script>
    <script src="js/splits.js"></script>
    <script src="js/router.js"></script>
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add static/index.html
  git commit -m "feat: add <base href> and relative asset paths to index.html"
  ```

---

### Task 3: Update `api.js` — relative API URLs

**Files:**
- Modify: `static/js/api.js`

- [ ] **Step 1: Remove leading `/` from all API URLs**

  Replace every `"/api/` occurrence with `"api/` in `static/js/api.js`.

  The file has these absolute URLs that must become relative:

  | Current | Replace with |
  |---------|-------------|
  | `` `/api/images?${p.toString()}` `` | `` `api/images?${p.toString()}` `` |
  | `"/api/images/stage"` | `"api/images/stage"` |
  | `"/api/images/stage/all"` | `"api/images/stage/all"` |
  | `` `/api/images/${id}/thumb` `` | `` `api/images/${id}/thumb` `` |
  | `"/api/search/by-upload"` | `"api/search/by-upload"` |
  | `"/api/search/similar"` | `"api/search/similar"` |
  | `"/api/splits"` | `"api/splits"` |
  | `"/api/splits/rebalance"` | `"api/splits/rebalance"` |
  | `` `/api/images/${id}` `` | `` `api/images/${id}` `` |
  | `` `/api/images/${id}/annotations` `` | `` `api/images/${id}/annotations` `` |
  | `"/api/images/scan"` | `"api/images/scan"` |
  | `"/api/assist/predict"` | `"api/assist/predict"` |
  | `` `/api/locks/${id}` `` (×3) | `` `api/locks/${id}` `` |
  | `"/api/classes"` | `"api/classes"` |
  | `"/api/images/upload"` | `"api/images/upload"` |
  | `"/api/images/import-roboflow"` | `"api/images/import-roboflow"` |
  | `"/api/export"` | `"api/export"` |

  The quickest way: in `static/js/api.js`, do a global find-and-replace of `"/api/` → `"api/` and `` `/api/ `` → `` `api/ ``. Verify no URL was missed by checking the file has zero remaining occurrences of `"/api/` or `` `/api/ ``.

  ```bash
  grep -n '"/api/\|`/api/' static/js/api.js
  ```

  Expected: no output (zero matches).

- [ ] **Step 2: Commit**

  ```bash
  git add static/js/api.js
  git commit -m "feat: make all API URLs relative in api.js for subpath support"
  ```

---

### Task 4: Serve templated `index.html` from `main.py`

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

  In `tests/test_api.py`, append:

  ```python
  def test_get_root_injects_base_href(tmp_path):
      """GET / returns HTML with <base href> matching ROOT_PATH setting."""
      from app.config import Settings
      from app.main import create_app
      settings = Settings(
          model_path="yolo11n.pt",
          data_dir=tmp_path,
          device="cpu",
          lock_ttl=60,
          scan_dir=None,
          default_val_ratio=0.2,
          embed_model="fake",
          root_path="/myapp/",
      )
      app = create_app(settings=settings, model_service=_fake_model(), embedding_service=_fake_embedder())
      with TestClient(app) as c:
          r = c.get("/")
      assert r.status_code == 200
      assert 'base href="/myapp/"' in r.text


  def test_get_root_default_base_href(tmp_path):
      """GET / with default ROOT_PATH returns <base href='/'>."""
      from app.config import Settings
      from app.main import create_app
      settings = Settings(
          model_path="yolo11n.pt",
          data_dir=tmp_path,
          device="cpu",
          lock_ttl=60,
          scan_dir=None,
          default_val_ratio=0.2,
          embed_model="fake",
          root_path="/",
      )
      app = create_app(settings=settings, model_service=_fake_model(), embedding_service=_fake_embedder())
      with TestClient(app) as c:
          r = c.get("/")
      assert r.status_code == 200
      assert 'base href="/"' in r.text
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```bash
  python3 -m pytest tests/test_api.py -k "base_href" -x --tb=short -q
  ```

  Expected: FAIL — `GET /` currently returns the raw static file without any `<base href>` injection.

- [ ] **Step 3: Update `main.py` to cache and serve modified `index.html`**

  Add `HTMLResponse` to FastAPI imports at top of `app/main.py`:

  ```python
  from fastapi import FastAPI
  from fastapi.responses import HTMLResponse
  from fastapi.staticfiles import StaticFiles
  ```

  In the `lifespan` function, add index.html caching right before `yield`. The lifespan already has the `settings` variable in scope:

  ```python
  # Cache index.html with root_path injected into <base href>
  index_src = (STATIC_DIR / "index.html").read_text()
  app.state.index_html = index_src.replace(
      '<base href="/" />',
      f'<base href="{settings.root_path}" />',
  )
  yield
  ```

  In `create_app()`, add the `GET /` route **before** the `StaticFiles` mount:

  ```python
  @app.get("/", include_in_schema=False)
  def serve_index():
      return HTMLResponse(app.state.index_html)

  app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```bash
  python3 -m pytest tests/test_api.py -k "base_href" -x --tb=short -q
  ```

  Expected: 2 passed.

- [ ] **Step 5: Run full suite**

  ```bash
  python3 -m pytest tests/ -x --tb=short -q
  ```

  Expected: 151 passed (144 original + 5 root_path config tests from Task 1 + 2 new tests).

- [ ] **Step 6: Commit**

  ```bash
  git add app/main.py tests/test_api.py
  git commit -m "feat: serve templated index.html with injected <base href> from main.py"
  ```
