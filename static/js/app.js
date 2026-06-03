// Orchestrates the annotator: gallery, lock lifecycle, save, assist, export.
const state = {
  classes: {},
  images: [],
  currentId: null,
  version: 0,
  locked: false,
  readOnly: false,
  dirty: false,
  heartbeat: null,
  filter: { include: new Set(), exclude: new Set(), onlyUnlabeled: false },
  page: 0,
  pageSize: 200,
  total: 0,
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
  els.import = $("import");
  els.scan = $("scan");
  els.title = $("image-title");
  els.filterClasses = $("filter-classes");
  els.filterUnlabeled = $("filter-unlabeled");
  els.filterClear = $("filter-clear");
  els.imageCount = $("image-count");
  els.pagePrev = $("page-prev");
  els.pageNext = $("page-next");
  els.pageInfo = $("page-info");
  els.conf = $("conf");
  els.iou = $("iou");
  els.autoOnOpen = $("auto-on-open");
  els.autoSave = $("auto-save");

  // restore persisted assist settings
  const saved = JSON.parse(localStorage.getItem("annotatorPrefs") || "{}");
  if (saved.conf != null) els.conf.value = saved.conf;
  if (saved.iou != null) els.iou.value = saved.iou;
  if (saved.autoOnOpen != null) els.autoOnOpen.checked = saved.autoOnOpen;
  if (saved.autoSave != null) els.autoSave.checked = saved.autoSave;

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
  renderFilterClasses();

  els.save.onclick = save;
  els.autolabel.onclick = autoLabel;
  els.export.onclick = doExport;
  els.upload.onchange = doUpload;
  els.import.onchange = doImport;
  els.scan.onclick = doScan;
  els.filterUnlabeled.onchange = () => {
    state.filter.onlyUnlabeled = els.filterUnlabeled.checked;
    reloadFromFilter();
  };
  els.filterClear.onclick = () => {
    state.filter.include.clear();
    state.filter.exclude.clear();
    state.filter.onlyUnlabeled = false;
    els.filterUnlabeled.checked = false;
    renderFilterClasses();
    reloadFromFilter();
  };
  els.pagePrev.onclick = () => {
    if (state.page > 0) {
      state.page -= 1;
      refreshGallery();
    }
  };
  els.pageNext.onclick = () => {
    if ((state.page + 1) * state.pageSize < state.total) {
      state.page += 1;
      refreshGallery();
    }
  };
  for (const el of [els.conf, els.iou, els.autoOnOpen, els.autoSave]) {
    el.onchange = savePrefs;
  }

  document.addEventListener("keydown", (e) => {
    if (document.activeElement && document.activeElement.tagName === "INPUT") return;
    if ((e.key === "Delete" || e.key === "Backspace") && state.currentId && !state.readOnly) {
      e.preventDefault();
      board.deleteSelected();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      navigate(1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      navigate(-1);
    } else if (e.key >= "1" && e.key <= "9" && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // 1-9 selects the Nth class (in id-sorted order)
      const ids = sortedClassIds();
      const target = ids[Number(e.key) - 1];
      if (target !== undefined) {
        e.preventDefault();
        selectClass(target);
      }
    }
  });
  // On tab close we stop heart-beating; the lock then expires by TTL server-side.

  await refreshGallery();
}

function savePrefs() {
  localStorage.setItem(
    "annotatorPrefs",
    JSON.stringify({
      conf: els.conf.value,
      iou: els.iou.value,
      autoOnOpen: els.autoOnOpen.checked,
      autoSave: els.autoSave.checked,
    })
  );
}

// Move to the prev/next image in the current (filtered) listing, crossing
// page boundaries as needed.
async function navigate(dir) {
  if (!state.images.length) return;
  const idx = state.images.findIndex((i) => i.id === state.currentId);
  if (idx === -1) {
    return openImage(state.images[0].id);
  }
  const next = idx + dir;
  if (next >= 0 && next < state.images.length) {
    return openImage(state.images[next].id);
  }
  // cross a page boundary
  if (dir > 0 && (state.page + 1) * state.pageSize < state.total) {
    if (!(await leaveCurrent())) return;
    state.page += 1;
    await refreshGallery();
    if (state.images.length) openImage(state.images[0].id);
  } else if (dir < 0 && state.page > 0) {
    if (!(await leaveCurrent())) return;
    state.page -= 1;
    await refreshGallery();
    if (state.images.length) openImage(state.images[state.images.length - 1].id);
  }
}

function normalizeClasses(raw) {
  // server returns {"0":"cat",...}; coerce keys to numbers
  const out = {};
  for (const k of Object.keys(raw)) out[Number(k)] = raw[k];
  return out;
}

function reloadFromFilter() {
  state.page = 0;
  refreshGallery();
}

async function refreshGallery() {
  const f = state.filter;
  const data = await api.listImages({
    limit: state.pageSize,
    offset: state.page * state.pageSize,
    include: [...f.include],
    exclude: [...f.exclude],
    onlyUnlabeled: f.onlyUnlabeled,
  });
  // guard against landing past the last page after deletions/filtering
  if (data.images.length === 0 && state.page > 0 && data.total > 0) {
    state.page = Math.max(0, Math.ceil(data.total / state.pageSize) - 1);
    return refreshGallery();
  }
  state.images = data.images;
  state.total = data.total;
  renderGallery();
  renderPager();
}

function renderPager() {
  const pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  els.pageInfo.textContent = state.total
    ? `page ${state.page + 1}/${pages}`
    : "";
  els.pagePrev.disabled = state.page === 0;
  els.pageNext.disabled = (state.page + 1) * state.pageSize >= state.total;
}

function renderGallery() {
  els.imageCount.textContent = `${state.total}`;
  els.gallery.innerHTML = "";
  for (const img of state.images) {
    const li = document.createElement("div");
    li.className = "thumb" + (img.id === state.currentId ? " active" : "");
    const lockMark = img.locked_by && !img.locked_by_me ? " 🔒" : "";
    const splitMark = img.split ? `<span class="split">${img.split}</span>` : "";
    li.innerHTML = `<span class="dot ${img.status}"></span>` +
      `<span class="name">${img.filename}</span>${splitMark}<span class="badge">${img.status}${lockMark}</span>`;
    li.onclick = () => openImage(img.id);
    els.gallery.appendChild(li);
  }
  if (state.total === 0) {
    const f = state.filter;
    const filtering = f.include.size || f.exclude.size || f.onlyUnlabeled;
    els.gallery.innerHTML = filtering
      ? '<p class="empty">No images match the filter.</p>'
      : '<p class="empty">No images. Upload, import a Roboflow zip, or scan a folder.</p>';
  }
}

function renderFilterClasses() {
  els.filterClasses.innerHTML = "";
  for (const id of Object.keys(state.classes).map(Number).sort((a, b) => a - b)) {
    const chip = document.createElement("button");
    const f = state.filter;
    const cls = f.include.has(id) ? "inc" : f.exclude.has(id) ? "exc" : "";
    chip.className = "fchip " + cls;
    chip.innerHTML = `<span class="swatch" style="background:${board._color(id)}"></span>${state.classes[id]}`;
    chip.onclick = () => {
      // cycle: off -> include -> exclude -> off
      if (f.include.has(id)) {
        f.include.delete(id);
        f.exclude.add(id);
      } else if (f.exclude.has(id)) {
        f.exclude.delete(id);
      } else {
        f.include.add(id);
      }
      renderFilterClasses();
      reloadFromFilter();
    };
    els.filterClasses.appendChild(chip);
  }
}

async function doImport(e) {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  setStatus("Importing Roboflow dataset…", "");
  try {
    const s = await api.importRoboflow(file);
    let msg = `Imported ${s.images_imported} images, ${s.boxes_imported} boxes`;
    if (s.boxes_skipped) msg += `, skipped ${s.boxes_skipped} box(es)`;
    if (s.classes_skipped && s.classes_skipped.length)
      msg += ` — classes not in model ignored: ${s.classes_skipped.join(", ")}`;
    setStatus(msg, "ok");
    await refreshGallery();
  } catch (err) {
    setStatus("Import failed: " + err.message, "err");
  }
}

// Leave the current image: auto-save (or confirm) pending changes, release lock.
// Returns false if the user cancelled.
async function leaveCurrent() {
  if (state.currentId && state.dirty && !state.readOnly) {
    if (els.autoSave.checked && state.locked) {
      await save();
    } else if (!confirm("Discard unsaved changes?")) {
      return false;
    }
  }
  await releaseCurrent();
  return true;
}

async function openImage(id) {
  if (!(await leaveCurrent())) return;

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
  const hadBoxes = detail.annotations.length > 0;
  await loadImageEl(id, detail.annotations);
  els.title.textContent = detail.image.filename + lockMsg;
  setDirty(false);
  setStatus(state.readOnly ? "Read-only" : "Editing", state.readOnly ? "warn" : "ok");
  await refreshGallery();

  // Auto-label freshly-opened images that have no labels yet.
  if (!state.readOnly && els.autoOnOpen.checked && !hadBoxes) {
    autoLabel();
  }
}

function loadImageEl(id, annotations) {
  return new Promise((resolve) => {
    const imgEl = new Image();
    imgEl.onload = () => {
      board.load(imgEl, annotations, state.readOnly);
      renderBoxList();
      resolve();
    };
    imgEl.onerror = () => resolve();
    imgEl.src = `/api/images/${id}/file`;
  });
}

async function reloadAnnotations() {
  const detail = await api.getImage(state.currentId);
  state.version = detail.version;
  await loadImageEl(state.currentId, detail.annotations);
  setDirty(false);
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
      await reloadAnnotations();
    } else if (e.status === 423) {
      setStatus("Locked by another user — cannot save", "err");
    } else {
      setStatus("Save failed: " + e.message, "err");
    }
  }
}

async function autoLabel() {
  if (!state.currentId || state.readOnly) return;
  const targetId = state.currentId;
  const conf = clamp01(parseFloat(els.conf.value), 0.25);
  const iou = clamp01(parseFloat(els.iou.value), 0.45);
  setStatus("Running model…", "");
  try {
    const res = await api.predict(targetId, conf, iou);
    if (state.currentId !== targetId) return; // navigated away — ignore stale result
    const drafts = res.boxes.map((b) => ({
      class_id: b.class_id,
      cx: b.cx,
      cy: b.cy,
      w: b.w,
      h: b.h,
      source: "assist",
    }));
    board.setBoxes([...board.getBoxes(), ...drafts]); // marks dirty via onChange
    setStatus(
      `Model added ${drafts.length} suggestion(s)` +
        (els.autoSave.checked ? "" : " — review & save"),
      "ok"
    );
  } catch (e) {
    if (state.currentId === targetId) setStatus("Auto-label failed: " + e.message, "err");
  }
}

function clamp01(v, fallback) {
  if (isNaN(v)) return fallback;
  return Math.min(1, Math.max(0, v));
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

function sortedClassIds() {
  return Object.keys(state.classes)
    .map(Number)
    .sort((a, b) => a - b);
}

// Make `id` the active class (for new boxes) and, if a box is selected,
// reassign it. Used by both the class buttons and the 1-9 shortcuts.
function selectClass(id) {
  if (!(id in state.classes)) return;
  board.setCurrentClass(id);
  if (board.selected >= 0) board.assignClassToSelected(id);
  [...els.classList.children].forEach((c) =>
    c.classList.toggle("active", Number(c.dataset.classId) === id)
  );
}

function renderClassList() {
  els.classList.innerHTML = "";
  sortedClassIds().forEach((id, i) => {
    const b = document.createElement("button");
    b.className = "class-btn";
    b.dataset.classId = id;
    const key = i < 9 ? `<span class="keycap">${i + 1}</span>` : "";
    b.innerHTML = `<span class="swatch" style="background:${board._color(id)}"></span>` +
      `<span class="cname">${state.classes[id]}</span>${key}`;
    b.onclick = () => selectClass(id);
    if (id === board.currentClass) b.classList.add("active");
    els.classList.appendChild(b);
  });
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
