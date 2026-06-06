# Box Z-Order (Send to Front / Back)

**Date:** 2026-06-07
**Status:** Approved

## Summary

Add z-order controls for annotation boxes in the annotator editor. When boxes overlap, users can reorder them (send to front, send to back, bring forward, send backward) via sidebar buttons and keyboard shortcuts — matching the Roboflow interaction model.

## How Z-Order Works Today

`BoxCanvas` in `canvas.js` stores boxes in `this.boxes[]`. Rendering iterates index 0 → N (index 0 drawn first = furthest back). Hit-testing iterates N → 0 (topmost box is hit first on click). Therefore: **array index = z-order** — moving a box in the array changes its visual layer. No schema change needed.

## Operations

| Operation | Keyboard | Effect on array |
|-----------|----------|-----------------|
| Bring Forward | `]` | Swap selected with next element (index + 1) |
| Send Backward | `[` | Swap selected with previous element (index - 1) |
| Send to Front | `Shift+]` | Move selected to last position |
| Send to Back | `Shift+[` | Move selected to first position |

All four are no-ops when there is no selected box or when already at the limit (e.g. bring forward when already at front).

## UI

### Sidebar buttons (in each box-row)

Each row in `#box-list` gets two small icon buttons prepended before the existing delete (`✕`) button:

```
[▲] [▼]  dogClass (suggested)  [✕]
```

- `▲` = Bring Forward (move one step toward front)
- `▼` = Send Backward (move one step toward back)
- Buttons are hidden when there is only one box (`boxes.length === 1`)
- `▲` is disabled (visually muted, no click action) when box is already at front
- `▼` is disabled when box is already at back
- Clicking a button selects that box and performs the operation (consistent with how delete works)
- Buttons not rendered when `state.readOnly` is true

### Keyboard shortcuts

Bound at the `document` level (same as existing shortcuts like Delete, arrow keys). Only fire when `board.selected >= 0`. Added in `app.js` inside `init()`.

## canvas.js Changes

Four new public methods on `BoxCanvas`:

```javascript
bringForward()   // swap selected with selected+1; update selected; render + onChange
sendBackward()   // swap selected with selected-1; update selected; render + onChange
sendToFront()    // move selected to end; update selected; render + onChange
sendToBack()     // move selected to 0; update selected; render + onChange
```

Each method:
1. Guards: returns immediately if `this.selected < 0` or already at limit
2. Performs the array mutation
3. Updates `this.selected` to the new index of the moved box
4. Calls `this.render()` and `this.onChange()`
5. Does NOT call `this.onSelect()` — selection doesn't change conceptually, only the rendering order

## app.js Changes

### `renderBoxList()` update

Add order buttons to each `box-row`. Each button click handler calls `board.selectIndex(i)` then `board.bringForward()` (or `board.sendBackward()`). Only added when `!state.readOnly`.

### Keyboard handler in `init()`

```javascript
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (board.selected < 0) return;
  if (e.key === "]" && !e.shiftKey) { e.preventDefault(); board.bringForward(); }
  if (e.key === "[" && !e.shiftKey) { e.preventDefault(); board.sendBackward(); }
  if (e.key === "]" && e.shiftKey)  { e.preventDefault(); board.sendToFront(); }
  if (e.key === "[" && e.shiftKey)  { e.preventDefault(); board.sendToBack(); }
});
```

`renderBoxList()` is triggered automatically via `board.onChange()` callback (already wired: `onChange: () => { setDirty(true); renderBoxList(); }`).

## Persistence

Box order is already persisted: `board.export()` returns boxes in array order, which is sent to the backend `PUT /api/images/{id}/annotations`. The backend stores and returns them in the same order. When annotations are loaded, they are set via `board.setBoxes(boxes)` which preserves order. No backend changes needed.

## CSS

Add styles for `.order-btn`:
- Small, borderless button similar to existing `.del` style
- Muted color by default; slightly brighter on hover
- `.disabled` class: opacity 0.3, cursor default, pointer-events none

## Files Changed

| File | Change |
|------|--------|
| `static/js/canvas.js` | Add 4 public methods: `bringForward`, `sendBackward`, `sendToFront`, `sendToBack` |
| `static/js/app.js` | Update `renderBoxList()` to add order buttons; add keyboard handler in `init()` |
| `static/css/app.css` | Add `.order-btn` and `.order-btn.disabled` styles |

## Out of Scope

- Right-click context menu (keyboard + sidebar buttons cover the need)
- "Select next overlapping box" on repeated click (separate feature)
- Database view z-order (annotations are only edited in the annotator canvas)
