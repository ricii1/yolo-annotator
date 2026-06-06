// Hash-based routing between the pages. The Annotate experience is split into a
// full-page image grid (#/annotate, the landing page) and a dedicated editor
// (#/editor) reached by opening an image. Database and Splits are their own
// routes too, so the URL reflects the view and back/forward + refresh work.
const VIEWS = ["annotate", "editor", "database", "splits"];

function viewFromHash() {
  const name = (location.hash || "").replace(/^#\/?/, "");
  return VIEWS.includes(name) ? name : "annotate";
}

function showView(name) {
  for (const v of VIEWS) {
    const el = document.getElementById("view-" + v);
    const nav = document.getElementById("nav-" + v);
    const active = v === name;
    if (el) el.hidden = !active;
    // The editor has no nav button of its own; keep "Annotate" lit while editing.
    if (nav) nav.classList.toggle("active", active || (v === "annotate" && name === "editor"));
  }
  if (name === "annotate") {
    initGallery();
    galleryRefresh();
  } else if (name === "database") {
    initDatabase();
    dbRefresh();
  } else if (name === "splits") {
    initSplits();
    refreshSplits();
  }
}

// Programmatic navigation: change the route, which drives showView via hashchange.
function goTo(name) {
  const target = "#/" + name;
  if (location.hash === target) showView(name);
  else location.hash = target;
}

function initRouter() {
  for (const v of VIEWS) {
    const nav = document.getElementById("nav-" + v);
    if (nav) nav.onclick = () => goTo(v);
  }
  window.addEventListener("hashchange", () => showView(viewFromHash()));
  showView(viewFromHash());
}

document.addEventListener("DOMContentLoaded", initRouter);
