# Drag & Drop Upload

**Date:** 2026-06-07
**Status:** Approved

## Summary

Add drag & drop support for uploading one or many image files to the YOLO Annotator. Dropping files anywhere on the window triggers the existing upload flow. No backend changes required.

## Behavior

- User drags one or more image files from their file manager onto any part of the browser window.
- A full-page overlay appears as soon as the drag enters the window (only for file drags, not text/link drags).
- User releases (drops) the files — overlay disappears, upload begins immediately using the existing `/api/images/upload` endpoint.
- Status bar updates as upload progresses, same as the existing Upload button flow.
- Duplicate files are blocked by the existing hash check; the status message names duplicates explicitly: e.g. `"Diupload 3, dilewati 1 duplikat (a.jpg)"`.
- Non-image files dropped alongside images are silently skipped by the existing backend (returns `skipped` with `reason: "invalid"`).
- Drag & drop works on all views (Annotate, Database, Splits), not just the gallery.

## UI

### Overlay (`#drop-overlay`)

- Fixed-position, covers entire viewport (`inset: 0`).
- Background: semi-transparent indigo (`rgba(99, 102, 241, 0.15)`).
- Border: 3px dashed indigo inset, with a CSS `@keyframes` pulse on opacity.
- Centered content: cloud/folder icon + "Lepaskan foto di sini" + subtitle "Mendukung banyak file".
- Hidden by default (`hidden` attribute); shown by toggling a `.active` class.
- Z-index above all content including the annotation canvas.

### Depth counter (flickering fix)

`dragenter`/`dragleave` fire for every child element the cursor crosses. A module-level integer `dragDepth` is incremented on `dragenter` and decremented on `dragleave`. The overlay is shown when `dragDepth > 0` and hidden when it reaches 0. This prevents the overlay from flickering as the cursor moves over gallery thumbnails or toolbar buttons.

## Files Changed

| File | Change |
|------|--------|
| `static/index.html` | Add `#drop-overlay` div at end of `<body>` |
| `static/css/app.css` | Add `.drop-overlay` and `.drop-overlay.active` styles |
| `static/js/app.js` | Add `initDropZone()` function called from `init()`, update status message for duplicates |

## Implementation Detail

```
initDropZone():
  dragDepth = 0
  document.addEventListener('dragenter', e => {
    if (!e.dataTransfer.types.includes('Files')) return
    dragDepth++
    overlay.classList.add('active')
    e.preventDefault()
  })
  document.addEventListener('dragover', e => {
    if (!e.dataTransfer.types.includes('Files')) return
    e.preventDefault()
  })
  document.addEventListener('dragleave', e => {
    dragDepth--
    if (dragDepth === 0) overlay.classList.remove('active')
  })
  document.addEventListener('drop', e => {
    e.preventDefault()
    dragDepth = 0
    overlay.classList.remove('active')
    const files = Array.from(e.dataTransfer.files)
    if (files.length) uploadFiles(files)
  })
```

`uploadFiles(files)` is extracted from the existing `doUpload` handler so both the `<input>` path and the drag path share the same logic without duplication.

## Status Message Format

After upload completes:

- All created: `"Diupload 3 foto"`
- Some skipped (duplicate): `"Diupload 2, dilewati: a.jpg (duplikat), b.jpg (duplikat)"`
- Some skipped (invalid): `"Diupload 2, dilewati: x.txt (bukan gambar)"`
- Mixed: combined into one message

## Out of Scope

- Drag & drop for folder upload (requires File System Access API or `webkitdirectory` — not planned)
- Drop on the annotation canvas (canvas has its own mouse events; dropping there uses the window handler)
- Mobile/touch drag support
