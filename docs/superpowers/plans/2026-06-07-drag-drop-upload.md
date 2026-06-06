# Drag & Drop Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full-page drag & drop file upload to the YOLO Annotator — dropping image files anywhere on the window triggers the existing upload flow.

**Architecture:** Pure frontend change. An overlay div is always in the DOM (invisible by default); a depth counter tracks `dragenter`/`dragleave` events to show/hide it without flickering. The existing `doUpload` logic is extracted into a shared `uploadFiles(files)` function used by both the `<input>` path and the new drag path.

**Tech Stack:** Vanilla JS, CSS custom properties (already defined in `app.css`), HTML5 Drag and Drop API. No new libraries.

---

## File Map

| File | What changes |
|------|-------------|
| `static/index.html` | Add `#drop-overlay` div before closing `</body>` |
| `static/css/app.css` | Add overlay styles + `@keyframes drop-pulse` at end of file |
| `static/js/app.js` | Extract `uploadFiles()`, update `doUpload()`, add `initDropZone()`, call from `init()`, improve status message |

---

### Task 1: Add overlay HTML and CSS

**Files:**
- Modify: `static/index.html` (before closing `</body>`)
- Modify: `static/css/app.css` (append at end)

- [ ] **Step 1: Add the overlay div to index.html**

  Open `static/index.html`. Before the closing `</body>` tag (which currently looks like):
  ```html
    <script src="/js/router.js"></script>
  </body>
  </html>
  ```
  Insert the overlay div so it reads:
  ```html
    <script src="/js/router.js"></script>

    <div id="drop-overlay">
      <div class="drop-overlay-inner">
        <div class="drop-overlay-icon">📂</div>
        <p class="drop-overlay-title">Lepaskan foto di sini</p>
        <p class="drop-overlay-sub">Mendukung banyak file sekaligus</p>
      </div>
    </div>
  </body>
  </html>
  ```

- [ ] **Step 2: Add overlay CSS to app.css**

  Append these rules at the very end of `static/css/app.css`:
  ```css
  /* ---- drag & drop overlay ---- */
  #drop-overlay {
    position: fixed;
    inset: 0;
    background: rgba(99, 102, 241, 0.15);
    border: 3px dashed var(--accent);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
  }
  #drop-overlay.active {
    pointer-events: auto;
    opacity: 1;
    animation: drop-pulse 1.5s ease-in-out infinite;
  }
  .drop-overlay-inner { text-align: center; }
  .drop-overlay-icon { font-size: 48px; margin-bottom: 12px; }
  .drop-overlay-title { font-size: 20px; font-weight: 600; margin: 0 0 6px; color: var(--text); }
  .drop-overlay-sub { font-size: 13px; color: var(--muted); margin: 0; }
  @keyframes drop-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.75; }
  }
  ```

- [ ] **Step 3: Verify overlay is invisible at rest**

  Open the app in a browser. The page should look exactly the same as before — no overlay visible. Open DevTools → Elements, find `#drop-overlay`, confirm `opacity: 0` and `pointer-events: none` are applied.

- [ ] **Step 4: Commit**

  ```bash
  git add static/index.html static/css/app.css
  git commit -m "feat: add drag & drop overlay HTML and CSS"
  ```

---

### Task 2: Wire up drag & drop logic in app.js

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: Extract `uploadFiles()` from `doUpload()`**

  Current `doUpload` (around line 688):
  ```javascript
  async function doUpload(e) {
    const files = e.target.files;
    if (!files.length) return;
    setStatus("Uploading…", "");
    const res = await api.upload(files);
    e.target.value = "";
    setStatus(`Uploaded ${res.created.length}, skipped ${res.skipped.length}`, "ok");
    await refreshGallery();
  }
  ```

  Replace it with two functions — `uploadFiles` (shared core logic) and the updated `doUpload` (thin wrapper):
  ```javascript
  async function uploadFiles(files) {
    setStatus("Uploading…", "");
    const res = await api.upload(files);
    const created = res.created.length;
    const skipped = res.skipped;
    if (!skipped.length) {
      setStatus(`Diupload ${created} foto`, "ok");
    } else {
      const detail = skipped
        .map((s) => `${s.filename} (${s.reason === "duplicate" ? "duplikat" : "bukan gambar"})`)
        .join(", ");
      setStatus(`Diupload ${created}, dilewati: ${detail}`, created > 0 ? "ok" : "warn");
    }
    await refreshGallery();
  }

  async function doUpload(e) {
    const files = e.target.files;
    if (!files.length) return;
    await uploadFiles(files);
    e.target.value = "";
  }
  ```

  > **Why extract?** Both the `<input onchange>` path and the drag path need identical upload + status + refresh behaviour. Sharing `uploadFiles` keeps them in sync.

- [ ] **Step 2: Add `initDropZone()` function**

  Add this function anywhere after `uploadFiles` (e.g., right before `doUploadFolder`):
  ```javascript
  function initDropZone() {
    const overlay = document.getElementById("drop-overlay");
    let dragDepth = 0;

    document.addEventListener("dragenter", (e) => {
      if (!e.dataTransfer.types.includes("Files")) return;
      dragDepth++;
      overlay.classList.add("active");
      e.preventDefault();
    });

    document.addEventListener("dragover", (e) => {
      if (!e.dataTransfer.types.includes("Files")) return;
      e.preventDefault();
    });

    document.addEventListener("dragleave", () => {
      dragDepth--;
      if (dragDepth === 0) overlay.classList.remove("active");
    });

    document.addEventListener("drop", async (e) => {
      e.preventDefault();
      dragDepth = 0;
      overlay.classList.remove("active");
      const files = Array.from(e.dataTransfer.files);
      if (files.length) await uploadFiles(files);
    });
  }
  ```

  > **Why `dragDepth`?** `dragenter`/`dragleave` fire on every child element the cursor crosses. Without the counter, moving the mouse over a gallery thumbnail would hide the overlay unexpectedly. The counter ensures the overlay only disappears when the drag fully leaves the window.

- [ ] **Step 3: Call `initDropZone()` from `init()`**

  Inside the `init()` function, after the existing event listeners are set up (around line 103 where `els.scan.onclick = doScan` is), add one call:
  ```javascript
  initDropZone();
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add static/js/app.js
  git commit -m "feat: wire drag & drop upload with depth counter and improved status"
  ```

---

### Task 3: Manual verification

No automated frontend test framework exists in this project — verification is done in the browser.

- [ ] **Step 1: Start the dev server**

  ```bash
  python -m uvicorn app.main:app --host 0.0.0.0 --port 1234
  ```

- [ ] **Step 2: Test — single file drop**

  1. Open the app in the browser.
  2. Drag a single `.jpg` or `.png` from your file manager onto the browser window.
  3. **Expected while dragging:** the indigo overlay appears with "Lepaskan foto di sini".
  4. **Expected after drop:** overlay disappears, status bar shows `"Diupload 1 foto"`, image appears in gallery.

- [ ] **Step 3: Test — multiple files drop**

  1. Select 3+ images in your file manager, drag them all at once onto the window.
  2. **Expected:** status bar shows `"Diupload 3 foto"` (or however many).
  3. All images appear in gallery.

- [ ] **Step 4: Test — duplicate drop**

  1. Drag the same image file that was uploaded in Step 2 onto the window again.
  2. **Expected:** status bar shows `"Diupload 0, dilewati: <filename> (duplikat)"`.
  3. Gallery count unchanged.

- [ ] **Step 5: Test — non-image file dropped alongside images**

  1. Drag one image and one `.txt` file together onto the window.
  2. **Expected:** status bar shows `"Diupload 1, dilewati: <txtfile> (bukan gambar)"`.
  3. Only the image appears in gallery.

- [ ] **Step 6: Test — drag text/link does NOT trigger overlay**

  1. Select some text on any webpage in another tab.
  2. Try to drag it into the annotator window.
  3. **Expected:** overlay does NOT appear (the `types.includes("Files")` guard prevents it).

- [ ] **Step 7: Test — overlay disappears correctly when drag is cancelled**

  1. Start dragging a file over the window so the overlay appears.
  2. Press `Escape` or drag the file back out of the window without dropping.
  3. **Expected:** overlay disappears cleanly (depth counter returns to 0).

- [ ] **Step 8: Run backend tests to confirm no regression**

  ```bash
  python3 -m pytest tests/ -x --tb=short -q
  ```
  Expected: all tests pass (79 passed as of last run).
