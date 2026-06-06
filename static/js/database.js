// Database page: a thumbnail-grid browser of the curated (database-stage) set,
// with image search, bulk move back to Annotating, and per-image "find similar".
const dbState = {
  images: [],
  total: 0,
  page: 0,
  pageSize: 200,
  selected: new Set(),
  search: null, // {images, scores}
  initialized: false,
};
const dbEls = {};

function initDatabase() {
  if (dbState.initialized) return;
  dbState.initialized = true;
  dbEls.grid = $("db-grid");
  dbEls.count = $("db-count");
  dbEls.prev = $("db-prev");
  dbEls.next = $("db-next");
  dbEls.pageinfo = $("db-pageinfo");
  dbEls.search = $("db-search");
  dbEls.searchBanner = $("db-search-banner");
  dbEls.searchText = $("db-search-text");
  dbEls.searchClear = $("db-search-clear");
  dbEls.batch = $("db-batch");
  dbEls.selall = $("db-selall");
  dbEls.selcount = $("db-selcount");
  dbEls.move = $("db-move");
  dbEls.selclear = $("db-selclear");
  dbEls.selallMatching = $("db-selall-matching");

  dbEls.prev.onclick = () => {
    if (dbState.page > 0) {
      dbState.page -= 1;
      dbRefresh();
    }
  };
  dbEls.next.onclick = () => {
    if ((dbState.page + 1) * dbState.pageSize < dbState.total) {
      dbState.page += 1;
      dbRefresh();
    }
  };
  dbEls.search.onchange = dbDoSearch;
  dbEls.searchClear.onclick = dbClearSearch;
  dbEls.selall.onchange = () => {
    if (dbEls.selall.checked) dbVisible().forEach((i) => dbState.selected.add(i.id));
    else dbState.selected.clear();
    dbRender();
  };
  dbEls.move.onclick = dbMoveSelected;
  dbEls.selclear.onclick = () => {
    dbState.selected.clear();
    dbRender();
  };
  dbEls.selallMatching.onclick = dbMoveAllMatching;
}

function dbVisible() {
  return dbState.search ? dbState.search.images : dbState.images;
}

async function dbRefresh() {
  if (dbState.search) {
    dbRender();
    return;
  }
  const data = await api.listImages({
    limit: dbState.pageSize,
    offset: dbState.page * dbState.pageSize,
    stage: "database",
  });
  if (data.images.length === 0 && dbState.page > 0 && data.total > 0) {
    dbState.page = Math.max(0, Math.ceil(data.total / dbState.pageSize) - 1);
    return dbRefresh();
  }
  dbState.images = data.images;
  dbState.total = data.total;
  dbRender();
}

function dbRender() {
  const images = dbVisible();
  const visible = new Set(images.map((i) => i.id));
  for (const id of [...dbState.selected]) if (!visible.has(id)) dbState.selected.delete(id);
  dbEls.count.textContent = dbState.search ? `${images.length} results` : `${dbState.total} images`;
  renderGrid(dbEls.grid, images, {
    selected: dbState.selected,
    onOpen: dbOpen,
    onToggle: (id, checked) => {
      if (checked) dbState.selected.add(id);
      else dbState.selected.delete(id);
      dbRenderBatch();
    },
    onFindSimilar: dbRunSimilar,
    scores: dbState.search ? dbState.search.scores : null,
    emptyHtml: dbState.search
      ? '<p class="empty">No matches.</p>'
      : '<p class="empty">No images in the Database yet. Promote validated images from Annotating.</p>',
  });
  dbRenderBatch();
  dbRenderPager();
}

function dbRenderPager() {
  const searching = !!dbState.search;
  dbEls.pageinfo.textContent = searching
    ? ""
    : dbState.total
    ? `page ${dbState.page + 1}/${Math.max(1, Math.ceil(dbState.total / dbState.pageSize))}`
    : "";
  dbEls.prev.disabled = searching || dbState.page === 0;
  dbEls.next.disabled = searching || (dbState.page + 1) * dbState.pageSize >= dbState.total;
}

function dbRenderBatch() {
  const n = dbState.selected.size;
  dbEls.batch.hidden = n === 0;
  const images = dbVisible();
  dbEls.selall.checked = images.length > 0 && n >= images.length;
  if (n > 0) dbEls.selcount.textContent = `${n} selected`;
  const pageFull = images.length > 0 && n >= images.length;
  const more = !dbState.search && dbState.total > images.length;
  dbEls.selallMatching.hidden = !(pageFull && more);
  if (!dbEls.selallMatching.hidden) {
    dbEls.selallMatching.textContent = `Move all ${dbState.total} to Annotating`;
  }
}

async function dbMoveSelected() {
  if (!dbState.selected.size) return;
  const ids = [...dbState.selected];
  try {
    await api.setStage(ids, "annotating");
    dbState.selected.clear();
    setStatus(`Moved ${ids.length} image(s) to Annotating`, "ok");
    await dbRefresh();
  } catch (e) {
    setStatus("Move failed: " + e.message, "err");
  }
}

async function dbMoveAllMatching() {
  try {
    const res = await api.setStageAll({ stage: "annotating", sourceStage: "database" });
    dbState.selected.clear();
    setStatus(`Moved ${res.updated} image(s) to Annotating`, "ok");
    await dbRefresh();
  } catch (e) {
    setStatus("Move failed: " + e.message, "err");
  }
}

async function dbDoSearch(e) {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const res = await api.searchByUpload(file, "database");
    dbApplySearch(res.results, "uploaded image");
  } catch (err) {
    setStatus("Search failed: " + err.message, "err");
  }
}

async function dbRunSimilar(id) {
  try {
    const res = await api.searchSimilar(id, "database");
    dbApplySearch(res.results, "selected image");
  } catch (err) {
    setStatus("Search failed: " + err.message, "err");
  }
}

function dbApplySearch(results, label) {
  dbState.search = { images: results, scores: new Map(results.map((r) => [r.image_id, r.score])) };
  dbState.selected.clear();
  dbEls.searchBanner.hidden = false;
  dbEls.searchText.textContent = `Similar to ${label} — ${results.length} result(s)`;
  dbRender();
}

function dbClearSearch() {
  dbState.search = null;
  dbState.selected.clear();
  dbEls.searchBanner.hidden = true;
  dbRefresh();
}

// Open a Database image in the editor for editing.
function dbOpen(id) {
  openImage(id); // navigates to the editor route on its own
}
