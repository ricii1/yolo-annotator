# Box Z-Order (Send to Front / Back) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add z-order controls (send to front, send to back, bring forward, send backward) to overlapping annotation boxes via sidebar buttons and keyboard shortcuts `[` / `]`.

**Architecture:** `BoxCanvas.boxes[]` array index is already the z-order — index 0 is drawn first (back), last index is drawn last (front). Four new methods on `BoxCanvas` mutate the array and update `this.selected`. `renderBoxList()` in `app.js` gains `▲`/`▼` buttons per row. Keyboard shortcuts bound in `init()`. No backend changes needed — box order is already persisted by the existing annotations API.

**Tech Stack:** Vanilla JS (canvas.js, app.js), CSS.

---

## File Map

| File | Change |
|------|--------|
| `static/js/canvas.js` | Add 4 public methods: `bringForward()`, `sendBackward()`, `sendToFront()`, `sendToBack()` |
| `static/js/app.js` | Update `renderBoxList()` to add `▲`/`▼` buttons; add keyboard handler in `init()` |
| `static/css/app.css` | Add `.order-btn` and `.order-btn.disabled` styles |

No automated frontend tests exist in this project. Correctness is verified manually and by running the backend test suite to confirm no regression.

---

### Task 1: Add z-order methods to `canvas.js`

**Files:**
- Modify: `static/js/canvas.js`

- [ ] **Step 1: Add the four methods**

  Open `static/js/canvas.js`. Find the `deleteSelected()` method (around line 64). Add the four new methods **after** `assignClassToSelected()` and **before** `selectIndex()`:

  ```javascript
  bringForward() {
    const i = this.selected;
    if (i < 0 || i >= this.boxes.length - 1) return;
    [this.boxes[i], this.boxes[i + 1]] = [this.boxes[i + 1], this.boxes[i]];
    this.selected = i + 1;
    this.render();
    this.onChange();
  }

  sendBackward() {
    const i = this.selected;
    if (i <= 0) return;
    [this.boxes[i], this.boxes[i - 1]] = [this.boxes[i - 1], this.boxes[i]];
    this.selected = i - 1;
    this.render();
    this.onChange();
  }

  sendToFront() {
    const i = this.selected;
    if (i < 0 || i >= this.boxes.length - 1) return;
    const box = this.boxes.splice(i, 1)[0];
    this.boxes.push(box);
    this.selected = this.boxes.length - 1;
    this.render();
    this.onChange();
  }

  sendToBack() {
    const i = this.selected;
    if (i <= 0) return;
    const box = this.boxes.splice(i, 1)[0];
    this.boxes.unshift(box);
    this.selected = 0;
    this.render();
    this.onChange();
  }
  ```

  > **Why no `onSelect()` call?** `onSelect` signals that a *different* box was chosen — updating the class list UI. Here the same box remains selected; only its z-position in the rendering order changes. Calling `onChange()` is enough to trigger `renderBoxList()` via the wired callback (`onChange: () => { setDirty(true); renderBoxList(); }`).

- [ ] **Step 2: Verify method placement**

  ```bash
  grep -n "bringForward\|sendBackward\|sendToFront\|sendToBack\|selectIndex" static/js/canvas.js
  ```

  Expected output shows all four new methods defined *before* `selectIndex`:
  ```
  83:  bringForward() {
  92:  sendBackward() {
  101: sendToFront() {
  111: sendToBack() {
  122: selectIndex(i) {
  ```
  (exact line numbers may differ slightly)

- [ ] **Step 3: Run backend tests to confirm no regression**

  ```bash
  python3 -m pytest tests/ -x --tb=short -q
  ```

  Expected: all tests pass (no Python code changed; this is a sanity check).

- [ ] **Step 4: Commit**

  ```bash
  git add static/js/canvas.js
  git commit -m "feat: add bringForward/sendBackward/sendToFront/sendToBack to BoxCanvas"
  ```

---

### Task 2: Add CSS for order buttons

**Files:**
- Modify: `static/css/app.css`

- [ ] **Step 1: Append `.order-btn` styles**

  Open `static/css/app.css`. Find the existing `.del` button styles (around line 225):
  ```css
  .del {
    background: transparent;
    border: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 12px;
  }
  .del:hover { color: var(--err); }
  ```

  Append the order-btn styles **immediately after** the `.del:hover` line:
  ```css
  .order-btn {
    background: transparent;
    border: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 10px;
    padding: 0 1px;
    line-height: 1;
  }
  .order-btn:hover { color: var(--text); }
  .order-btn.disabled { opacity: 0.3; cursor: default; pointer-events: none; }
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add static/css/app.css
  git commit -m "feat: add .order-btn CSS for z-order buttons in box list"
  ```

---

### Task 3: Wire buttons and keyboard shortcuts in `app.js`

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: Update `renderBoxList()` to add order buttons**

  In `static/js/app.js`, find `renderBoxList()` (around line 852). The current function body is:

  ```javascript
  function renderBoxList() {
    els.boxList.innerHTML = "";
    const boxes = board.boxes;
    boxes.forEach((b, i) => {
      const row = document.createElement("div");
      row.className = "box-row" + (i === board.selected ? " active" : "");
      const name = state.classes[b.class_id] ?? b.class_id;
      row.innerHTML = `<span class="swatch" style="background:${board._color(b.class_id)}"></span>` +
        `<span>${name}${b.source === "assist" ? " (suggested)" : ""}</span>`;
      row.onclick = () => board.selectIndex(i);
      const del = document.createElement("button");
      del.textContent = "✕";
      del.className = "del";
      del.onclick = (ev) => {
        ev.stopPropagation();
        board.selectIndex(i);
        board.deleteSelected();
      };
      if (!state.readOnly) row.appendChild(del);
      els.boxList.appendChild(row);
    });
    if (boxes.length === 0) els.boxList.innerHTML = '<p class="empty">No boxes yet.</p>';
  }
  ```

  Replace the entire function with:

  ```javascript
  function renderBoxList() {
    els.boxList.innerHTML = "";
    const boxes = board.boxes;
    boxes.forEach((b, i) => {
      const row = document.createElement("div");
      row.className = "box-row" + (i === board.selected ? " active" : "");
      const name = state.classes[b.class_id] ?? b.class_id;
      row.innerHTML = `<span class="swatch" style="background:${board._color(b.class_id)}"></span>` +
        `<span>${name}${b.source === "assist" ? " (suggested)" : ""}</span>`;
      row.onclick = () => board.selectIndex(i);
      if (!state.readOnly) {
        if (boxes.length > 1) {
          const up = document.createElement("button");
          up.textContent = "▲";
          up.title = "Bring forward";
          up.className = "order-btn" + (i === boxes.length - 1 ? " disabled" : "");
          up.onclick = (ev) => { ev.stopPropagation(); board.selectIndex(i); board.bringForward(); };
          const dn = document.createElement("button");
          dn.textContent = "▼";
          dn.title = "Send backward";
          dn.className = "order-btn" + (i === 0 ? " disabled" : "");
          dn.onclick = (ev) => { ev.stopPropagation(); board.selectIndex(i); board.sendBackward(); };
          row.appendChild(up);
          row.appendChild(dn);
        }
        const del = document.createElement("button");
        del.textContent = "✕";
        del.className = "del";
        del.onclick = (ev) => { ev.stopPropagation(); board.selectIndex(i); board.deleteSelected(); };
        row.appendChild(del);
      }
      els.boxList.appendChild(row);
    });
    if (boxes.length === 0) els.boxList.innerHTML = '<p class="empty">No boxes yet.</p>';
  }
  ```

  > `▲` is disabled when `i === boxes.length - 1` (already at front). `▼` is disabled when `i === 0` (already at back). Buttons hidden entirely when `boxes.length === 1`.

- [ ] **Step 2: Add keyboard handler in `init()`**

  In `app.js`, inside the `init()` function, find the line `initDropZone();` (added in the drag & drop feature). Add the keyboard handler immediately after it:

  ```javascript
  initDropZone();
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (board.selected < 0) return;
    if (e.key === "]" && !e.shiftKey) { e.preventDefault(); board.bringForward(); }
    if (e.key === "[" && !e.shiftKey) { e.preventDefault(); board.sendBackward(); }
    if (e.key === "]" && e.shiftKey)  { e.preventDefault(); board.sendToFront(); }
    if (e.key === "[" && e.shiftKey)  { e.preventDefault(); board.sendToBack(); }
  });
  ```

  > `renderBoxList()` is called automatically via `board.onChange()` which is already wired to `() => { setDirty(true); renderBoxList(); }` — no need to call it explicitly here.

- [ ] **Step 3: Run backend tests to confirm no regression**

  ```bash
  python3 -m pytest tests/ -x --tb=short -q
  ```

  Expected: all tests pass.

- [ ] **Step 4: Commit**

  ```bash
  git add static/js/app.js
  git commit -m "feat: add z-order buttons and keyboard shortcuts to box list"
  ```

---

### Task 4: Manual verification

No automated frontend test framework exists. Verify in the browser.

- [ ] **Step 1: Start the dev server**

  ```bash
  python -m uvicorn app.main:app --host 0.0.0.0 --port 1234
  ```

- [ ] **Step 2: Open an image with multiple overlapping boxes**

  Upload or open an image that already has 2+ annotation boxes. If none exist, draw 2 overlapping boxes manually.

- [ ] **Step 3: Test `▲` / `▼` buttons in box list**

  1. The box list sidebar shows `▲` and `▼` buttons next to each box (when 2+ boxes exist).
  2. `▲` on the last box (front) is greyed out (`.disabled` style).
  3. `▼` on the first box (back) is greyed out.
  4. Clicking `▲` on a box visually moves it one layer forward on the canvas.
  5. Clicking `▼` on a box visually moves it one layer backward.
  6. After clicking, the clicked box remains selected (highlighted in box list).

- [ ] **Step 4: Test keyboard shortcuts**

  1. Select a box by clicking it.
  2. Press `]` → box moves one layer forward (canvas re-renders, box list updates).
  3. Press `[` → box moves one layer backward.
  4. Press `Shift+]` → box jumps to front.
  5. Press `Shift+[` → box jumps to back.
  6. Shortcuts do nothing when no box is selected (no crash).
  7. Shortcuts do nothing when an `<input>` or `<textarea>` is focused.

- [ ] **Step 5: Test persistence**

  1. Reorder boxes, then click Save.
  2. Reload the page and reopen the image.
  3. Verify boxes render in the same z-order as saved.

- [ ] **Step 6: Test single-box case**

  1. Open an image with exactly 1 box.
  2. Verify the `▲`/`▼` buttons do NOT appear (only the `✕` delete button).
  3. Verify `[` and `]` keys do nothing (no crash, no visual change).
