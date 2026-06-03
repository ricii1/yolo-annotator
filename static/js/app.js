// Orchestrates the annotator: gallery, lock lifecycle, save, assist, export.
const state = {
  classes: {},
  currentId: null,
  version: 0,
  locked: false,
  readOnly: false,
  dirty: false,
  heartbeat: null,
};

const els = {};
let board;

function $(id) {
  return document.getElementById(id);
}

function setStatus(msg, kind = "") {
  els.status.textContent = msg;
  els.status.className = "status " + kind;
}

function setDirty(d) {
  state.dirty = d;
  els.save.disabled = !d || state.readOnly;
}

async function init() {
  els.gallery = $("gallery");
  els.classList = $("class-list");
  els.boxList = $("box-list");
  els.status = $("status");
  els.save = $("save");
  els.autolabel = $("autolabel");
  els.export = $("export");
  els.upload = $("upload");
  els.scan = $("scan");
  els.title = $("image-title");

  board = new BoxCanvas($("canvas"), {
    onChange: () => {
      setDirty(true);
      renderBoxList();
    },
    onSelect: () => renderBoxList(),
  });

  const data = await api.classes();
  state.classes = normalizeClasses(data.classes);
  board.setClasses(state.classes);
  renderClassList();

  els.save.onclick = save;
  els.autolabel.onclick = autoLabel;
  els.export.onclick = doExport;
  els.upload.onchange = doUpload;
  els.scan.onclick = doScan;
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Delete" || e.key === "Backspace") && state.currentId && !state.readOnly) {
      if (document.activeElement.tagName !== "INPUT") {
        e.preventDefault();
        board.deleteSelected();
      }
    }
  });
  // On tab close we stop heart-beating; the lock then expires by TTL server-side.

  await refreshGallery();
}

function normalizeClasses(raw) {
  // server returns {"0":"cat",...}; coerce keys to numbers
  const out = {};
  for (const k of Object.keys(raw)) out[Number(k)] = raw[k];
  return out;
}

async function refreshGallery() {
  const data = await api.listImages();
  els.gallery.innerHTML = "";
  for (const img of data.images) {
    const li = document.createElement("div");
    li.className = "thumb" + (img.id === state.currentId ? " active" : "");
    const lockMark = img.locked_by && !img.locked_by_me ? " 🔒" : "";
    li.innerHTML = `<span class="dot ${img.status}"></span>` +
      `<span class="name">${img.filename}</span><span class="badge">${img.status}${lockMark}</span>`;
    li.onclick = () => openImage(img.id);
    els.gallery.appendChild(li);
  }
  if (data.images.length === 0) {
    els.gallery.innerHTML = '<p class="empty">No images. Upload or scan a folder.</p>';
  }
}

async function openImage(id) {
  if (state.dirty && !confirm("Discard unsaved changes?")) return;
  await releaseCurrent();

  state.currentId = id;
  state.readOnly = false;
  let lockMsg = "";
  try {
    await api.claimLock(id);
    state.locked = true;
    startHeartbeat(id);
  } catch (e) {
    if (e.status === 423) {
      state.readOnly = true;
      state.locked = false;
      lockMsg = " — read-only (locked by another user)";
    } else {
      throw e;
    }
  }

  const detail = await api.getImage(id);
  state.version = detail.version;
  const imgEl = new Image();
  imgEl.onload = () => {
    board.load(imgEl, detail.annotations, state.readOnly);
    renderBoxList();
  };
  imgEl.src = `/api/images/${id}/file`;
  els.title.textContent = detail.image.filename + lockMsg;
  setDirty(false);
  setStatus(state.readOnly ? "Read-only" : "Editing", state.readOnly ? "warn" : "ok");
  await refreshGallery();
}

function startHeartbeat(id) {
  stopHeartbeat();
  state.heartbeat = setInterval(async () => {
    try {
      await api.heartbeat(id);
    } catch (e) {
      stopHeartbeat();
    }
  }, 20000);
}
function stopHeartbeat() {
  if (state.heartbeat) clearInterval(state.heartbeat);
  state.heartbeat = null;
}

async function releaseCurrent() {
  stopHeartbeat();
  if (state.currentId && state.locked) {
    try {
      await api.releaseLock(state.currentId);
    } catch (e) {
      /* ignore */
    }
  }
  state.locked = false;
}

async function save() {
  if (!state.currentId) return;
  try {
    const res = await api.saveAnnotations(state.currentId, state.version, board.getBoxes());
    state.version = res.version;
    setDirty(false);
    setStatus("Saved", "ok");
    await refreshGallery();
  } catch (e) {
    if (e.status === 409) {
      setStatus("Conflict: someone else saved. Reloading…", "err");
      await openImage(state.currentId);
    } else if (e.status === 423) {
      setStatus("Locked by another user — cannot save", "err");
    } else {
      setStatus("Save failed: " + e.message, "err");
    }
  }
}

async function autoLabel() {
  if (!state.currentId || state.readOnly) return;
  setStatus("Running model…", "");
  try {
    const res = await api.predict(state.currentId, 0.25);
    const drafts = res.boxes.map((b) => ({
      class_id: b.class_id,
      cx: b.cx,
      cy: b.cy,
      w: b.w,
      h: b.h,
      source: "assist",
    }));
    board.setBoxes([...board.getBoxes(), ...drafts]);
    setStatus(`Model added ${drafts.length} suggestion(s) — review & save`, "ok");
  } catch (e) {
    setStatus("Auto-label failed: " + e.message, "err");
  }
}

async function doUpload(e) {
  const files = e.target.files;
  if (!files.length) return;
  setStatus("Uploading…", "");
  const res = await api.upload(files);
  e.target.value = "";
  setStatus(`Uploaded ${res.created.length}, skipped ${res.skipped.length}`, "ok");
  await refreshGallery();
}

async function doScan() {
  const folder = prompt("Server folder path to scan (blank = configured default):", "");
  if (folder === null) return;
  try {
    const res = await api.scan(folder.trim());
    setStatus(`Scanned: ${res.created.length} new image(s)`, "ok");
    await refreshGallery();
  } catch (e) {
    setStatus("Scan failed: " + e.message, "err");
  }
}

async function doExport() {
  setStatus("Building dataset…", "");
  try {
    const res = await fetch(api.exportUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "dataset.zip";
    a.click();
    URL.revokeObjectURL(url);
    setStatus("Dataset exported", "ok");
  } catch (e) {
    setStatus("Export failed: " + e.message, "err");
  }
}

function renderClassList() {
  els.classList.innerHTML = "";
  for (const id of Object.keys(state.classes).map(Number).sort((a, b) => a - b)) {
    const b = document.createElement("button");
    b.className = "class-btn";
    b.innerHTML = `<span class="swatch" style="background:${board._color(id)}"></span>${state.classes[id]}`;
    b.onclick = () => {
      board.setCurrentClass(id);
      if (board.selected >= 0) board.assignClassToSelected(id);
      [...els.classList.children].forEach((c) => c.classList.remove("active"));
      b.classList.add("active");
    };
    if (id === board.currentClass) b.classList.add("active");
    els.classList.appendChild(b);
  }
}

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

document.addEventListener("DOMContentLoaded", init);
