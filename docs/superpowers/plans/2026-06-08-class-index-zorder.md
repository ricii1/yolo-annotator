# Class-Index-Based Default Layer Order + Right-Click Z-Order Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make boxes default to a class-index-based stacking order whenever an image's annotations are loaded (class 0 always renders on top of class 1, etc.), and add a right-click context menu on canvas boxes exposing the existing bring-forward/send-backward/send-to-front/send-to-back actions.

**Architecture:** Both changes live entirely in `BoxCanvas` (`static/js/canvas.js`), which already owns the `boxes[]` array (array index = z-order, see `render()` at line ~335) and the four z-order methods (`bringForward`/`sendBackward`/`sendToFront`/`sendToBack`, lines 84-120). Part 1 adds a stable sort step to `load()`. Part 2 adds a small, self-contained context-menu DOM element built and managed by `BoxCanvas` itself (created in `_bind()`, appended to `document.body`, positioned with `position: fixed` at the cursor) — no `index.html` changes needed, keeping the canvas component self-contained.

**Tech Stack:** Vanilla JS (no framework, no JS test runner — this repo only has Python/pytest tests for the backend). Verification is manual, via the running app in a browser, same as the existing z-order feature (commits `556ac3a`, `dd1af47`, `6451608`).

---

## Before you start

Run the dev server in the background so you can verify each task in the browser:

```bash
cd /home/ricii/joki/yolo-annotator && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000, pick (or create) a project that has at least two classes (e.g. class 0 = "dog", class 1 = "cat"), and an image with two overlapping boxes of different classes — you'll use this for both tasks below. If no such image/annotation exists yet, draw two overlapping boxes of different classes on any image and save, so you have a fixture to reload.

---

### Task 1: Sort boxes by class index when loading an image

**Files:**
- Modify: `static/js/canvas.js:33-42` (`load` method)

- [ ] **Step 1: Add the sort to `load()`**

Replace the `load` method (`static/js/canvas.js:33-42`):

```javascript
  load(imgEl, boxes, readOnly) {
    this.img = imgEl;
    this.boxes = boxes
      .map((b) => ({ ...b }))
      .sort((a, b) => b.class_id - a.class_id);
    this.selected = -1;
    this.hover = -1;
    this.readOnly = !!readOnly;
    this._resize();
    this.render();
    this.onSelect(-1);
  }
```

This is a stable sort (guaranteed by the JS spec since ES2019 — all current browsers) by `class_id` descending. `render()` draws `this.boxes` forward (index 0 first/furthest back, last index last/frontmost — see `static/js/canvas.js:335`), so after this sort, class 0 boxes end up at the highest array indices and are drawn last → on top; class 1 sits just below; etc. Boxes that share a class keep their original relative order.

- [ ] **Step 2: Manually verify the sort**

With the dev server running, open the fixture image described above (two overlapping boxes: one class 0, one class 1, with class 0's box positioned so it visually overlaps class 1's box).

1. Reload the image (navigate away and back, or refresh the page and reopen it).
2. Confirm the class-0 box is drawn on top of the class-1 box at the overlap — its stroke is visible over the other box's stroke, and clicking in the overlap area selects the class-0 box first (topmost hit-test, `_hitBox` iterates back-to-front).
3. Now manually reorder them the "wrong" way using the existing box-list `▼`/`▲` buttons (send the class-0 box backward so class-1 is on top) and save.
4. Reload the image again. Confirm the order snaps back to class-0-on-top — i.e. the load-time sort overrides whatever was previously saved, every time.

Expected: class 0 is always on top after (re)loading, regardless of any manually-saved order from a previous session.

- [ ] **Step 3: Commit**

```bash
git add static/js/canvas.js
git commit -m "feat: sort boxes by class index on load so lower class renders on top"
```

---

### Task 2: Right-click context menu for z-order on canvas boxes

**Files:**
- Modify: `static/js/canvas.js` (constructor area, `_bind`, `_down`, add new private methods)
- Modify: `static/css/app.css` (add `.context-menu` styles, near the existing `.order-btn` rules at line ~233)

- [ ] **Step 1: Build the menu element in `_bind()`**

In `static/js/canvas.js`, the four z-order actions and their disabled conditions already exist as methods (`bringForward`, `sendBackward`, `sendToFront`, `sendToBack`, lines 84-120) and the box-list buttons in `app.js` already encode the same "disabled when at the limit" rules. Add a menu built once, reused on every right-click.

Add a new private method `_buildContextMenu()` and call it from the constructor (right after `this._bind();` on line 23):

```javascript
    this._bind();
    this._buildContextMenu();
```

```javascript
  _buildContextMenu() {
    const items = [
      { label: "Bring Forward", run: () => this.bringForward(), disabled: () => this.selected < 0 || this.selected >= this.boxes.length - 1 },
      { label: "Send Backward", run: () => this.sendBackward(), disabled: () => this.selected <= 0 },
      { label: "Send to Front", run: () => this.sendToFront(), disabled: () => this.selected < 0 || this.selected >= this.boxes.length - 1 },
      { label: "Send to Back", run: () => this.sendToBack(), disabled: () => this.selected <= 0 },
    ];
    this._menu = document.createElement("div");
    this._menu.className = "context-menu hidden";
    this._menuItems = items.map((item) => {
      const btn = document.createElement("button");
      btn.textContent = item.label;
      btn.onclick = () => {
        if (btn.disabled) return;
        item.run();
        this._hideContextMenu();
      };
      this._menu.appendChild(btn);
      return { btn, disabled: item.disabled };
    });
    document.body.appendChild(this._menu);

    document.addEventListener("click", (e) => {
      if (!this._menu.classList.contains("hidden") && !this._menu.contains(e.target)) {
        this._hideContextMenu();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this._hideContextMenu();
    });
    window.addEventListener("scroll", () => this._hideContextMenu(), true);
    window.addEventListener("resize", () => this._hideContextMenu());
  }

  _showContextMenu(x, y) {
    this._menuItems.forEach(({ btn, disabled }) => { btn.disabled = disabled(); });
    this._menu.style.left = `${x}px`;
    this._menu.style.top = `${y}px`;
    this._menu.classList.remove("hidden");
  }

  _hideContextMenu() {
    this._menu.classList.add("hidden");
  }
```

- [ ] **Step 2: Wire up the `contextmenu` event**

In `_bind()` (`static/js/canvas.js:207-217`), add a listener alongside the existing ones:

```javascript
  _bind() {
    this.canvas.addEventListener("mousedown", (e) => this._down(e));
    window.addEventListener("mousemove", (e) => this._move(e));
    window.addEventListener("mouseup", (e) => this._up(e));
    this.canvas.addEventListener("mouseleave", () => {
      if (this.hover !== -1) {
        this.hover = -1;
        this.render();
      }
    });
    this.canvas.addEventListener("contextmenu", (e) => this._onContextMenu(e));
  }
```

Add the handler near `_down`/`_move`/`_up` (e.g. directly after `_up`, `static/js/canvas.js:291`):

```javascript
  _onContextMenu(e) {
    if (!this.img || this.readOnly) return;
    e.preventDefault();
    const m = this._mouse(e);
    const hit = this._hitBox(m);
    if (hit < 0) {
      this._hideContextMenu();
      return;
    }
    this.selectIndex(hit);
    this._showContextMenu(e.clientX, e.clientY);
  }
```

This reuses `_mouse()` (canvas-relative coordinates, line 168) and `_hitBox()` (topmost-box hit test, line 197) exactly as left-click selection does (`_down`, line 228), so right-click selects the same box a left-click would.

- [ ] **Step 3: Hide the menu when starting a new canvas interaction**

So the menu doesn't linger while the user starts dragging/drawing elsewhere, hide it at the top of `_down` (`static/js/canvas.js:219`):

```javascript
  _down(e) {
    if (!this.img || this.readOnly) return;
    this._hideContextMenu();
    const m = this._mouse(e);
```

- [ ] **Step 4: Add CSS for the context menu**

In `static/css/app.css`, add after the `.order-btn.disabled` rule (line 243):

```css
.context-menu {
  position: fixed;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  min-width: 150px;
  background: var(--panel2);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  padding: 4px;
}
.context-menu.hidden { display: none; }
.context-menu button {
  background: transparent;
  border: none;
  color: var(--text);
  text-align: left;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}
.context-menu button:hover:not(:disabled) { background: var(--bg); }
.context-menu button:disabled { color: var(--muted); opacity: 0.4; cursor: default; }
```

- [ ] **Step 5: Manually verify the context menu**

With the dev server running and the same fixture image (two overlapping boxes of different classes) open:

1. Right-click directly on a box. Confirm: the browser's native context menu does NOT appear, the box gets selected (selection outline appears / box-list row highlights), and a small menu with four items — Bring Forward, Send Backward, Send to Front, Send to Back — appears at the cursor.
2. Right-click on empty canvas area (no box under the cursor). Confirm no menu appears and no native menu appears either.
3. With the backmost of two boxes selected via right-click, confirm "Send Backward" and "Send to Back" are visibly disabled (greyed out, unclickable), while "Bring Forward"/"Send to Front" are active. Click "Bring Forward" — confirm the box moves one step forward, the menu closes, and the box-list / canvas reflect the new order (same effect as clicking the `▲` button in the box list).
4. Right-click a box, then click elsewhere on the page outside the menu — confirm the menu closes without performing any action.
5. Right-click a box, then press `Escape` — confirm the menu closes.
6. Right-click a box to open the menu, then scroll or resize the window — confirm the menu closes.
7. Switch the "Boxes" panel to read-only mode if the project supports it (or open an image where `state.readOnly` is true) and right-click a box — confirm no context menu appears (matches existing behavior where order buttons/delete are hidden in read-only mode).

Expected: all checks pass; the four menu actions produce identical results to the existing box-list buttons / `[`/`]`/`Shift+[`/`Shift+]` shortcuts.

- [ ] **Step 6: Commit**

```bash
git add static/js/canvas.js static/css/app.css
git commit -m "feat: add right-click context menu for box z-order actions"
```

---

## Self-review notes

- **Spec coverage:** Part 1 (default sort by class index on load, re-applied every load) → Task 1. Part 2 (right-click menu, 4 actions, selects box first, closes on click-outside/Escape/scroll/resize, hidden when read-only) → Task 2, steps 1-5 cover every listed behavior including the read-only check explicitly called out in the spec.
- **No persisted "sort mode" / no `setBoxes` changes / no class-list reordering** — confirmed out of scope per the spec; this plan does not touch them.
- **Type/method consistency:** `bringForward`/`sendBackward`/`sendToFront`/`sendToBack` are called with the exact names and no-arg signatures already defined in `canvas.js` (lines 84-120); the menu's `disabled()` predicates mirror the same boundary checks those methods use internally (`this.selected < 0`, `this.selected >= this.boxes.length - 1`, `this.selected <= 0`).
