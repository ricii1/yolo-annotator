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
  filter: { include: new Set(), exclude: new Set(), onlyUnlabeled: false, stage: "annotating" },
  selected: new Set(),
  currentStage: "annotating",
  page: 0,
  pageSize: 200,
  total: 0,
  gridView: false, // sidebar gallery: list (default) vs grid
  search: null, // {ids:[...], scores:Map} when an image search is active
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
  els.uploadFolder = $("upload-folder");
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
  els.batchBar = $("batch-bar");
  els.batchCount = $("batch-count");
  els.batchMove = $("batch-move");
  els.batchClear = $("batch-clear");
  els.batchSelall = $("batch-selall");
  els.batchSelallMatching = $("batch-selall-matching");
  els.stageToggle = $("stage-toggle");
  els.searchAnnotate = $("search-annotate");
  els.searchBanner = $("search-banner");
  els.searchBannerText = $("search-banner-text");
  els.searchClear = $("search-clear");
  els.gridToggle = $("grid-toggle");
  els.editorBack = $("editor-back");

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
  els.uploadFolder.onchange = doUploadFolder;
  els.import.onchange = doImport;
  els.scan.onclick = doScan;
  initDropZone();
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
  els.batchMove.onclick = doBatchMove;
  els.batchClear.onclick = () => {
    state.selected.clear();
    renderWorkspace();
  };
  els.batchSelall.onchange = () => {
    if (els.batchSelall.checked) visibleImages().forEach((i) => state.selected.add(i.id));
    else state.selected.clear();
    renderWorkspace();
  };
  els.batchSelallMatching.onclick = doMoveAllMatching;
  els.stageToggle.onclick = toggleCurrentStage;
  els.searchAnnotate.onchange = (e) => doImageSearch(e, "annotating");
  els.searchClear.onclick = clearSearch;
  els.gridToggle.onclick = () => {
    state.gridView = !state.gridView;
    els.gridToggle.classList.toggle("active", state.gridView);
    renderGallery();
  };
  els.editorBack.onclick = async () => {
    if (!(await leaveCurrent())) return;
    goTo("annotate");
  };

  document.addEventListener("keydown", (e) => {
    if (document.activeElement && document.activeElement.tagName === "INPUT") return;
    // Editor-only shortcuts: ignore them on the grid landing / other pages.
    if (location.hash !== "#/editor") return;
    if ((e.key === "Delete" || e.key === "Backspace") && state.currentId && !state.readOnly) {
      e.preventDefault();
      board.deleteSelected();
    } else if (e.key === "ArrowRight" || e.key === "s" || e.key === "S") {
      // → or 's' moves to the next image
      e.preventDefault();
      navigate(1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      navigate(-1);
    } else if (/^[0-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // 1-9 then 0 selects the Nth class (0 = 10th), matching keyboard layout
      const slot = e.key === "0" ? 9 : Number(e.key) - 1;
      const target = sortedClassIds()[slot];
      if (target !== undefined) {
        e.preventDefault();
        selectClass(target);
      }
    } else if ((e.key === "a" || e.key === "A") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // 'a' runs auto model detection on the current image
      e.preventDefault();
      autoLabel();
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

// Move to the prev/next image in the current (filtered) listing or search
// results, crossing page boundaries as needed.
async function navigate(dir) {
  const list = visibleImages();
  if (!list.length) return;
  const idx = list.findIndex((i) => i.id === state.currentId);
  if (idx === -1) {
    return openImage(list[0].id);
  }
  const next = idx + dir;
  if (next >= 0 && next < list.length) {
    return openImage(list[next].id);
  }
  if (state.search) return; // search results aren't paginated
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

// Re-render every surface that reflects the shared image listing: the editor
// sidebar gallery + pager, and (when present) the full-page grid landing page.
function renderWorkspace() {
  renderGallery();
  renderPager();
  if (typeof galleryRender === "function") galleryRender();
}

async function refreshGallery() {
  // When an image search is active, the gallery shows ranked results, not a page.
  if (state.search) {
    renderWorkspace();
    return;
  }
  const f = state.filter;
  const data = await api.listImages({
    limit: state.pageSize,
    offset: state.page * state.pageSize,
    include: [...f.include],
    exclude: [...f.exclude],
    onlyUnlabeled: f.onlyUnlabeled,
    stage: f.stage,
  });
  // guard against landing past the last page after deletions/filtering
  if (data.images.length === 0 && state.page > 0 && data.total > 0) {
    state.page = Math.max(0, Math.ceil(data.total / state.pageSize) - 1);
    return refreshGallery();
  }
  state.images = data.images;
  state.total = data.total;
  renderWorkspace();
}

// Images currently shown in the sidebar (search results or the listing page).
function visibleImages() {
  return state.search ? state.search.images : state.images;
}

function renderPager() {
  const searching = !!state.search;
  els.pageInfo.textContent = searching
    ? ""
    : state.total
    ? `page ${state.page + 1}/${Math.max(1, Math.ceil(state.total / state.pageSize))}`
    : "";
  els.pagePrev.disabled = searching || state.page === 0;
  els.pageNext.disabled = searching || (state.page + 1) * state.pageSize >= state.total;
}

function renderGallery() {
  const images = visibleImages();
  els.imageCount.textContent = state.search ? `${images.length} results` : `${state.total}`;
  // drop selections for ids no longer visible
  const visible = new Set(images.map((i) => i.id));
  for (const id of [...state.selected]) if (!visible.has(id)) state.selected.delete(id);

  const onToggle = (id, checked) => {
    if (checked) state.selected.add(id);
    else state.selected.delete(id);
    renderBatchBar();
  };

  if (state.gridView || state.search) {
    els.gallery.className = "gallery grid compact";
    renderGrid(els.gallery, images, {
      selected: state.selected,
      currentId: state.currentId,
      onOpen: openImage,
      onToggle,
      onFindSimilar: (id) => runSimilar(id, "annotating"),
      scores: state.search ? state.search.scores : null,
      emptyHtml: '<p class="empty">No matches.</p>',
    });
  } else {
    els.gallery.className = "gallery";
    els.gallery.innerHTML = "";
    for (const img of images) {
      const li = document.createElement("div");
      li.className = "thumb" + (img.id === state.currentId ? " active" : "");
      const pick = document.createElement("input");
      pick.type = "checkbox";
      pick.className = "pick";
      pick.checked = state.selected.has(img.id);
      pick.onclick = (e) => {
        e.stopPropagation();
        onToggle(img.id, e.target.checked);
      };
      li.appendChild(pick);
      const lockMark = img.locked_by && !img.locked_by_me ? " 🔒" : "";
      const splitMark = img.split ? `<span class="split">${img.split}</span>` : "";
      const rest = document.createElement("span");
      rest.style.cssText = "display:flex;align-items:center;gap:8px;flex:1;min-width:0;";
      rest.innerHTML =
        `<span class="dot ${img.status}"></span>` +
        `<span class="name">${img.filename}</span>${splitMark}<span class="badge">${img.status}${lockMark}</span>`;
      rest.onclick = () => openImage(img.id);
      li.appendChild(rest);
      els.gallery.appendChild(li);
    }
    if (images.length === 0) {
      const f = state.filter;
      const filtering = f.include.size || f.exclude.size || f.onlyUnlabeled;
      els.gallery.innerHTML = filtering
        ? '<p class="empty">No images match the filter.</p>'
        : '<p class="empty">No images. Upload, import a Roboflow zip, or scan a folder.</p>';
    }
  }
  renderBatchBar();
}

function renderBatchBar() {
  const n = state.selected.size;
  els.batchBar.hidden = n === 0;
  const images = visibleImages();
  els.batchSelall.checked = images.length > 0 && n >= images.length;
  if (n > 0) {
    els.batchCount.textContent = `${n} selected`;
    els.batchMove.textContent = "Move to Database";
  }
  // Offer "select all N matching" only on a plain (non-search) listing that spans
  // more than one page and where the whole current page is already selected.
  const pageFull = images.length > 0 && n >= images.length;
  const more = !state.search && state.total > images.length;
  els.batchSelallMatching.hidden = !(pageFull && more);
  if (!els.batchSelallMatching.hidden) {
    els.batchSelallMatching.textContent = `Move all ${state.total} matching to Database`;
  }
}

async function doBatchMove() {
  if (!state.selected.size) return;
  const ids = [...state.selected];
  try {
    await api.setStage(ids, "database");
    state.selected.clear();
    if (ids.includes(state.currentId)) {
      state.currentStage = "database";
      renderStageToggle();
    }
    setStatus(`Moved ${ids.length} image(s) to Database`, "ok");
    await refreshGallery();
  } catch (e) {
    setStatus("Move failed: " + e.message, "err");
  }
}

// Promote every image matching the current filter (across all pages) to Database.
async function doMoveAllMatching() {
  const f = state.filter;
  try {
    const res = await api.setStageAll({
      stage: "database",
      sourceStage: "annotating",
      include: [...f.include],
      exclude: [...f.exclude],
      onlyUnlabeled: f.onlyUnlabeled,
    });
    state.selected.clear();
    setStatus(`Moved ${res.updated} image(s) to Database`, "ok");
    await refreshGallery();
  } catch (e) {
    setStatus("Move failed: " + e.message, "err");
  }
}

// ---- Image search (sidebar) -------------------------------------------------

async function doImageSearch(e, stage) {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  setStatus("Searching by image…", "");
  try {
    const res = await api.searchByUpload(file, stage);
    applySearchResults(res.results, "uploaded image");
  } catch (err) {
    setStatus("Search failed: " + err.message, "err");
  }
}

async function runSimilar(imageId, stage) {
  setStatus("Finding similar images…", "");
  try {
    const res = await api.searchSimilar(imageId, stage);
    applySearchResults(res.results, "selected image");
  } catch (err) {
    setStatus("Search failed: " + err.message, "err");
  }
}

function applySearchResults(results, label) {
  const scores = new Map(results.map((r) => [r.image_id, r.score]));
  state.search = { images: results, scores, label };
  state.selected.clear();
  els.searchBanner.hidden = false;
  els.searchBannerText.textContent = `Similar to ${label} — ${results.length} result(s)`;
  renderWorkspace();
  setStatus(`${results.length} similar image(s)`, "ok");
}

function clearSearch() {
  state.search = null;
  state.selected.clear();
  els.searchBanner.hidden = true;
  refreshGallery();
}

// Reflect the open image's stage on the editor toolbar button.
function renderStageToggle() {
  const open = state.currentId != null;
  els.stageToggle.disabled = !open;
  els.stageToggle.textContent =
    open && state.currentStage === "database" ? "➖ Remove from Database" : "➕ Add to Database";
}

async function toggleCurrentStage() {
  if (state.currentId == null) return;
  const target = state.currentStage === "database" ? "annotating" : "database";
  try {
    await api.setStage([state.currentId], target);
    state.currentStage = target;
    renderStageToggle();
    setStatus(`Image moved to ${target}`, "ok");
    await refreshGallery();
  } catch (e) {
    setStatus("Move failed: " + e.message, "err");
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

  goTo("editor"); // opening an image always shows the dedicated editor page
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
  state.currentStage = detail.image.stage || "annotating";
  renderStageToggle();
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
    imgEl.src = api.imageFileUrl(id);
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
    const existing = board.getBoxes();
    const imgW = (board.img && board.img.naturalWidth) || 1;
    const imgH = (board.img && board.img.naturalHeight) || 1;
    // Suppress draft boxes that overlap an existing box of the SAME class by
    // >= the overlap threshold (extends NMS to boxes already labeled).
    const all = res.boxes.map((b) => ({
      class_id: b.class_id,
      cx: b.cx,
      cy: b.cy,
      w: b.w,
      h: b.h,
      source: "assist",
    }));
    const drafts = all.filter(
      (d) => !existing.some((e) => e.class_id === d.class_id && boxIoU(d, e, imgW, imgH) >= iou)
    );
    const suppressed = all.length - drafts.length;
    board.setBoxes([...existing, ...drafts]); // marks dirty via onChange
    let msg = `Model added ${drafts.length} suggestion(s)`;
    if (suppressed) msg += ` (${suppressed} skipped, overlap existing)`;
    if (!els.autoSave.checked) msg += " — review & save";
    setStatus(msg, "ok");
  } catch (e) {
    if (state.currentId === targetId) setStatus("Auto-label failed: " + e.message, "err");
  }
}

function clamp01(v, fallback) {
  if (isNaN(v)) return fallback;
  return Math.min(1, Math.max(0, v));
}

// IoU of two normalized boxes, computed in pixel space (scaled by the image
// dimensions) so it matches the model's own pixel-space NMS rather than the
// distorted IoU you'd get straight from normalized coords.
function boxIoU(a, b, imgW, imgH) {
  const ax1 = (a.cx - a.w / 2) * imgW, ay1 = (a.cy - a.h / 2) * imgH;
  const ax2 = (a.cx + a.w / 2) * imgW, ay2 = (a.cy + a.h / 2) * imgH;
  const bx1 = (b.cx - b.w / 2) * imgW, by1 = (b.cy - b.h / 2) * imgH;
  const bx2 = (b.cx + b.w / 2) * imgW, by2 = (b.cy + b.h / 2) * imgH;
  const iw = Math.max(0, Math.min(ax2, bx2) - Math.max(ax1, bx1));
  const ih = Math.max(0, Math.min(ay2, by2) - Math.max(ay1, by1));
  const inter = iw * ih;
  if (inter <= 0) return 0;
  const union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter;
  return union > 0 ? inter / union : 0;
}

async function uploadFiles(files) {
  setStatus("Uploading…", "");
  let res;
  try {
    res = await api.upload(files);
  } catch (e) {
    setStatus("Upload failed: " + e.message, "err");
    return;
  }
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
    dragDepth = Math.max(0, dragDepth - 1);
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

const UPLOAD_FOLDER_BATCH = 50;
const SUPPORTED_EXTS = new Set([".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"]);

async function doUploadFolder(e) {
  const all = [...e.target.files].filter((f) => {
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    return SUPPORTED_EXTS.has(ext);
  });
  e.target.value = "";
  if (!all.length) {
    setStatus("No supported images found in folder", "warn");
    return;
  }

  let created = 0, skipped = 0, done = 0;
  const total = all.length;

  for (let i = 0; i < total; i += UPLOAD_FOLDER_BATCH) {
    const batch = all.slice(i, i + UPLOAD_FOLDER_BATCH);
    setStatus(`Uploading ${done}/${total} files…`, "");
    try {
      const res = await api.upload(batch);
      created += res.created.length;
      skipped += res.skipped.length;
    } catch (err) {
      setStatus(`Upload failed at file ${done + 1}: ${err.message}`, "err");
      return;
    }
    done += batch.length;
  }

  setStatus(`Folder upload done: ${created} added, ${skipped} skipped`, "ok");
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
    const key = i < 10 ? `<span class="keycap">${(i + 1) % 10}</span>` : "";
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
