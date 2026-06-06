// Reusable thumbnail grid: image preview, status/split badges, optional selection
// checkbox, optional similarity score, and a hover "find similar" button.
function renderGrid(container, images, opts = {}) {
  const {
    selected = null, // Set<id> or null to hide checkboxes
    currentId = null,
    onOpen = null, // (id) => void
    onToggle = null, // (id, checked) => void
    onFindSimilar = null, // (id) => void
    scores = null, // Map<id, number> for search results
    emptyHtml = '<p class="empty">No images.</p>',
  } = opts;

  container.innerHTML = "";
  if (!images.length) {
    container.innerHTML = emptyHtml;
    return;
  }
  for (const img of images) {
    const card = document.createElement("div");
    card.className = "card" + (img.id === currentId ? " active" : "");

    if (selected) {
      const pick = document.createElement("input");
      pick.type = "checkbox";
      pick.className = "card-pick";
      pick.checked = selected.has(img.id);
      pick.onclick = (e) => {
        e.stopPropagation();
        if (onToggle) onToggle(img.id, e.target.checked);
      };
      card.appendChild(pick);
    }

    const thumb = document.createElement("img");
    thumb.className = "card-thumb";
    thumb.loading = "lazy";
    thumb.src = api.thumbUrl(img.id);
    thumb.alt = img.filename;
    if (onOpen) thumb.onclick = () => onOpen(img.id);
    card.appendChild(thumb);

    const meta = document.createElement("div");
    meta.className = "card-meta";
    const scoreBadge =
      scores && scores.has(img.id)
        ? `<span class="score">${scores.get(img.id).toFixed(2)}</span>`
        : "";
    const splitBadge = img.split ? `<span class="split">${img.split}</span>` : "";
    meta.innerHTML =
      `<span class="dot ${img.status}"></span>${splitBadge}${scoreBadge}` +
      `<span class="card-name" title="${img.filename}">${img.filename}</span>`;
    card.appendChild(meta);

    if (onFindSimilar) {
      const sim = document.createElement("button");
      sim.className = "card-sim";
      sim.title = "Find similar images";
      sim.textContent = "⌕";
      sim.onclick = (e) => {
        e.stopPropagation();
        onFindSimilar(img.id);
      };
      card.appendChild(sim);
    }
    container.appendChild(card);
  }
}
