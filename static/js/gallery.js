// Full-page image grid: the Roboflow-style landing page for the Annotating set.
// It shares app.js's `state` (filters, search, selection, pagination) so the grid
// and the editor sidebar stay in sync, and reuses the same mutators
// (refreshGallery, reloadFromFilter, doBatchMove, doImageSearch, ...). Clicking a
// card opens the dedicated editor via openImage().
const galleryEls = {};
let galleryInitialized = false;

function initGallery() {
  if (galleryInitialized) return;
  galleryInitialized = true;
  galleryEls.grid = $("gal-grid");
  galleryEls.count = $("gal-count");
  galleryEls.filterClasses = $("gal-filter-classes");
  galleryEls.filterUnlabeled = $("gal-filter-unlabeled");
  galleryEls.filterClear = $("gal-filter-clear");
  galleryEls.search = $("gal-search");
  galleryEls.searchBanner = $("gal-search-banner");
  galleryEls.searchText = $("gal-search-text");
  galleryEls.searchClear = $("gal-search-clear");
  galleryEls.batch = $("gal-batch");
  galleryEls.selall = $("gal-selall");
  galleryEls.selcount = $("gal-selcount");
  galleryEls.move = $("gal-move");
  galleryEls.selclear = $("gal-selclear");
  galleryEls.selallMatching = $("gal-selall-matching");
  galleryEls.prev = $("gal-prev");
  galleryEls.pageinfo = $("gal-pageinfo");
  galleryEls.next = $("gal-next");

  galleryEls.filterUnlabeled.onchange = () => {
    state.filter.onlyUnlabeled = galleryEls.filterUnlabeled.checked;
    reloadFromFilter();
  };
  galleryEls.filterClear.onclick = () => {
    state.filter.include.clear();
    state.filter.exclude.clear();
    state.filter.onlyUnlabeled = false;
    reloadFromFilter();
  };
  galleryEls.search.onchange = (e) => doImageSearch(e, "annotating");
  galleryEls.searchClear.onclick = clearSearch;
  galleryEls.selall.onchange = () => {
    if (galleryEls.selall.checked) visibleImages().forEach((i) => state.selected.add(i.id));
    else state.selected.clear();
    renderWorkspace();
  };
  galleryEls.move.onclick = doBatchMove;
  galleryEls.selclear.onclick = () => {
    state.selected.clear();
    renderWorkspace();
  };
  galleryEls.selallMatching.onclick = doMoveAllMatching;
  galleryEls.prev.onclick = () => {
    if (state.page > 0) {
      state.page -= 1;
      refreshGallery();
    }
  };
  galleryEls.next.onclick = () => {
    if ((state.page + 1) * state.pageSize < state.total) {
      state.page += 1;
      refreshGallery();
    }
  };
}

// Fetch + render the current Annotating listing (shared with the editor sidebar).
function galleryRefresh() {
  refreshGallery();
}

function galleryRender() {
  if (!galleryInitialized) return;
  const images = visibleImages();
  galleryEls.count.textContent = state.search ? `${images.length} results` : `${state.total} images`;
  galleryEls.filterUnlabeled.checked = state.filter.onlyUnlabeled;

  galleryRenderFilterClasses();

  renderGrid(galleryEls.grid, images, {
    selected: state.selected,
    currentId: state.currentId,
    onOpen: openImage,
    onToggle: (id, checked) => {
      if (checked) state.selected.add(id);
      else state.selected.delete(id);
      galleryRenderBatch();
    },
    onFindSimilar: (id) => runSimilar(id, "annotating"),
    scores: state.search ? state.search.scores : null,
    emptyHtml: state.search
      ? '<p class="empty">No matches.</p>'
      : '<p class="empty">No images. Upload, import a Roboflow zip, or scan a folder.</p>',
  });

  galleryEls.searchBanner.hidden = !state.search;
  if (state.search) {
    galleryEls.searchText.textContent = `Similar to ${state.search.label} — ${images.length} result(s)`;
  }

  galleryRenderBatch();
  galleryRenderPager();
}

// Class filter chips: cycle off -> include -> exclude -> off (mirrors the sidebar).
function galleryRenderFilterClasses() {
  galleryEls.filterClasses.innerHTML = "";
  for (const id of Object.keys(state.classes).map(Number).sort((a, b) => a - b)) {
    const f = state.filter;
    const chip = document.createElement("button");
    const cls = f.include.has(id) ? "inc" : f.exclude.has(id) ? "exc" : "";
    chip.className = "fchip " + cls;
    chip.innerHTML = `<span class="swatch" style="background:${board._color(id)}"></span>${state.classes[id]}`;
    chip.onclick = () => {
      if (f.include.has(id)) {
        f.include.delete(id);
        f.exclude.add(id);
      } else if (f.exclude.has(id)) {
        f.exclude.delete(id);
      } else {
        f.include.add(id);
      }
      reloadFromFilter();
    };
    galleryEls.filterClasses.appendChild(chip);
  }
}

function galleryRenderBatch() {
  const n = state.selected.size;
  galleryEls.batch.hidden = n === 0;
  const images = visibleImages();
  galleryEls.selall.checked = images.length > 0 && n >= images.length;
  if (n > 0) galleryEls.selcount.textContent = `${n} selected`;
  const pageFull = images.length > 0 && n >= images.length;
  const more = !state.search && state.total > images.length;
  galleryEls.selallMatching.hidden = !(pageFull && more);
  if (!galleryEls.selallMatching.hidden) {
    galleryEls.selallMatching.textContent = `Move all ${state.total} matching to Database`;
  }
}

function galleryRenderPager() {
  const searching = !!state.search;
  galleryEls.pageinfo.textContent = searching
    ? ""
    : state.total
    ? `page ${state.page + 1}/${Math.max(1, Math.ceil(state.total / state.pageSize))}`
    : "";
  galleryEls.prev.disabled = searching || state.page === 0;
  galleryEls.next.disabled = searching || (state.page + 1) * state.pageSize >= state.total;
}
