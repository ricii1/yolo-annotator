// Splits page: shows the train/val/test distribution of the Database set and
// rebalances it to target ratios.
const splitsEls = {};
let splitsInitialized = false;

function initSplits() {
  if (splitsInitialized) return;
  splitsInitialized = true;
  splitsEls.bars = $("splits-bars");
  splitsEls.train = $("split-train");
  splitsEls.val = $("split-val");
  splitsEls.test = $("split-test");
  splitsEls.seed = $("split-seed");
  splitsEls.rebalance = $("splits-rebalance");
  splitsEls.status = $("splits-status");
  splitsEls.export = $("splits-export");
  splitsEls.rebalance.onclick = doRebalance;
  splitsEls.export.onclick = doExport; // reuse app.js exporter
}

async function refreshSplits() {
  try {
    renderSplits(await api.getSplits());
  } catch (e) {
    splitsEls.bars.innerHTML = '<p class="empty">Failed to load splits.</p>';
  }
}

function renderSplits(c) {
  const groups = [
    ["train", c.train],
    ["val", c.val],
    ["test", c.test],
    ["unassigned", c.unassigned],
  ];
  const total = c.total || 0;
  const rows = groups
    .map(([name, n]) => {
      const pct = total ? Math.round((n / total) * 100) : 0;
      return (
        `<div class="split-row"><span class="split-label">${name}</span>` +
        `<div class="split-track"><div class="split-fill ${name}" style="width:${pct}%"></div></div>` +
        `<span class="split-num">${n} (${pct}%)</span></div>`
      );
    })
    .join("");
  splitsEls.bars.innerHTML = rows + `<p class="muted-note">${total} image(s) in Database</p>`;
}

async function doRebalance() {
  const train = (parseFloat(splitsEls.train.value) || 0) / 100;
  const val = (parseFloat(splitsEls.val.value) || 0) / 100;
  const test = (parseFloat(splitsEls.test.value) || 0) / 100;
  const seed = parseInt(splitsEls.seed.value, 10) || 42;
  if (val + test > 1.0001) {
    splitsEls.status.textContent = "val + test must not exceed 100%";
    splitsEls.status.className = "status err";
    return;
  }
  splitsEls.status.textContent = "Rebalancing…";
  splitsEls.status.className = "status";
  try {
    renderSplits(await api.rebalance({ train, val, test, seed }));
    splitsEls.status.textContent = "Rebalanced";
    splitsEls.status.className = "status ok";
  } catch (e) {
    splitsEls.status.textContent = "Rebalance failed: " + e.message;
    splitsEls.status.className = "status err";
  }
}
