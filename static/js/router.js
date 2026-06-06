// Top-level navigation between the Annotate, Database, and Splits pages.
const VIEWS = ["annotate", "database", "splits"];

function showView(name) {
  for (const v of VIEWS) {
    const el = document.getElementById("view-" + v);
    const nav = document.getElementById("nav-" + v);
    const active = v === name;
    if (el) el.hidden = !active;
    if (nav) nav.classList.toggle("active", active);
  }
  if (name === "database") {
    initDatabase();
    dbRefresh();
  } else if (name === "splits") {
    initSplits();
    refreshSplits();
  }
}

function initRouter() {
  for (const v of VIEWS) {
    const nav = document.getElementById("nav-" + v);
    if (nav) nav.onclick = () => showView(v);
  }
}

document.addEventListener("DOMContentLoaded", initRouter);
