# Class-Index-Based Default Layer Order + Right-Click Z-Order Menu

**Date:** 2026-06-08
**Status:** Approved

## Summary

Two additions building on the existing manual z-order system ([[2026-06-07-box-z-order-design]]):

1. When an image's annotations are loaded, boxes are automatically pre-sorted so that lower class index renders on top of higher class index when boxes overlap (class 0 on top, class 1 below it, etc.).
2. Right-clicking a box on the canvas opens a context menu with the same four z-order actions already available via the box-list buttons and `[`/`]` shortcuts.

Manual reordering continues to work exactly as today after the initial load — this only changes the *starting* order each time an image is opened.

## Part 1: Default order by class index on load

### Where

`BoxCanvas.load(imgEl, boxes, readOnly)` in `canvas.js` (the method called from `app.js:577` whenever an image's annotations are fetched and displayed).

### Behavior

Before storing the incoming boxes, stable-sort them by `class_id` **descending**, keeping original relative order for boxes that share a class_id (stable sort — append the original index as a tiebreaker since `Array.prototype.sort` stability is guaranteed in modern JS engines but we make it explicit for clarity).

Rendering draws forward through `this.boxes` (`canvas.js:335`, index 0 drawn first / furthest back, last index drawn last / frontmost). Sorting by `class_id` descending therefore places class 0 boxes at the highest array indices → drawn last → visually on top; class 1 boxes sit just below; and so on.

```javascript
load(imgEl, boxes, readOnly) {
  this.img = imgEl;
  this.boxes = boxes
    .map((b, i) => ({ box: { ...b }, i }))
    .sort((a, b) => b.box.class_id - a.box.class_id || a.i - b.i)
    .map((entry) => entry.box);
  this.selected = -1;
  this.hover = -1;
  this.readOnly = !!readOnly;
  this._resize();
  this.render();
  this.onSelect(-1);
}
```

### Re-sort on every load (including reload)

This sort runs **every time `load()` is called** — i.e. every time an image is opened or reopened — even if the user previously reordered boxes manually and saved. The displayed order always reflects current class indices on (re)load. (Confirmed preference: simplicity and consistency over preserving a prior manual order across reloads.)

`setBoxes()` (used when appending auto-detect draft boxes to the existing in-session list, `app.js:666`) is **not** changed — it must not disrupt an active manual reordering mid-session.

### Persistence

No schema change. As today, `getBoxes()` exports boxes in current array order and that's what gets saved — the sort simply determines what that initial array order is when annotations are loaded from disk.

## Part 2: Right-click context menu for z-order

### Where

- New `contextmenu` event listener registered in `BoxCanvas._bind()` (`canvas.js:207`).
- A small menu `<div>` element added to `index.html` near `<canvas id="canvas">` (around line 116), styled in `app.css`.
- `BoxCanvas` exposes the menu open/close via a small new internal helper plus a constructor option (or the menu element is looked up by a fixed id, e.g. `#box-context-menu`, consistent with how the canvas itself is referenced by id).

### Behavior

1. On `contextmenu` over the canvas:
   - `e.preventDefault()` to suppress the native browser menu.
   - Hit-test at the cursor position using the same logic as left-click selection (topmost box under cursor, iterating back-to-front).
   - If no box is under the cursor: do nothing (let the menu stay closed; no native menu either, to keep behavior predictable over the canvas).
   - If a box is found: select it (`selectIndex`) and open the context menu positioned at the cursor's client coordinates.
2. The menu shows four items, each invoking the corresponding existing `BoxCanvas` method directly:
   - **Bring Forward** → `bringForward()`
   - **Send Backward** → `sendBackward()`
   - **Send to Front** → `sendToFront()`
   - **Send to Back** → `sendToBack()`
3. Item disabled state mirrors the box-list buttons: "Bring Forward"/"Send to Front" disabled when the box is already frontmost; "Send Backward"/"Send to Back" disabled when already backmost. Disabled items are not clickable.
4. The menu closes when:
   - an item is clicked (after performing its action),
   - the user clicks anywhere outside the menu,
   - `Escape` is pressed,
   - the canvas is scrolled or the window is resized.
5. Hidden entirely when `state.readOnly` is true (matching the existing pattern for order buttons and delete).

### Files Changed

| File | Change |
|------|--------|
| `static/js/canvas.js` | Sort boxes by `class_id` descending (stable) in `load()`; add `contextmenu` handler in `_bind()`; add menu show/hide/positioning logic |
| `static/index.html` | Add hidden context-menu `<div>` with four action items near the canvas |
| `static/css/app.css` | Add styles for the context menu container and items (positioning, hover, disabled state) |

## Out of Scope

- Any persisted "sort mode" toggle — the class-index sort is always applied on load, not configurable.
- Changing `setBoxes()` or any other entry point besides `load()`.
- Reordering classes themselves (class index values come from `classes.txt` / project config, unchanged here).
