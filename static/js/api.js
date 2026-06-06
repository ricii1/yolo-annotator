// Thin wrappers around the backend JSON API.
const api = {
  async _json(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      /* no body */
    }
    if (!res.ok) {
      const err = new Error((data && data.detail) || res.statusText);
      err.status = res.status;
      err.detail = data && data.detail;
      throw err;
    }
    return data;
  },

  listImages({ limit = 200, offset = 0, include = [], exclude = [], onlyUnlabeled = false, stage = "" } = {}) {
    const p = new URLSearchParams();
    p.set("limit", limit);
    p.set("offset", offset);
    if (include.length) p.set("include", include.join(","));
    if (exclude.length) p.set("exclude", exclude.join(","));
    if (onlyUnlabeled) p.set("only_unlabeled", "true");
    if (stage) p.set("stage", stage);
    return this._json("GET", `api/images?${p.toString()}`);
  },
  setStage(imageIds, stage) {
    return this._json("POST", "api/images/stage", { image_ids: imageIds, stage });
  },
  setStageAll({ stage, sourceStage = null, include = [], exclude = [], onlyUnlabeled = false }) {
    return this._json("POST", "api/images/stage/all", {
      stage,
      source_stage: sourceStage,
      include,
      exclude,
      only_unlabeled: onlyUnlabeled,
    });
  },
  thumbUrl(id) {
    return `api/images/${id}/thumb`;
  },
  async searchByUpload(file, stage = "", k = 200) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("stage", stage || "");
    fd.append("k", String(k));
    const res = await fetch("api/search/by-upload", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data && data.detail) || "search failed");
    return data;
  },
  searchSimilar(imageId, stage = null, k = 200) {
    return this._json("POST", "api/search/similar", { image_id: imageId, stage, k });
  },
  getSplits() {
    return this._json("GET", "api/splits");
  },
  rebalance({ train, val, test, seed }) {
    return this._json("POST", "api/splits/rebalance", { train, val, test, seed });
  },
  getImage(id) {
    return this._json("GET", `api/images/${id}`);
  },
  saveAnnotations(id, version, boxes) {
    return this._json("PUT", `api/images/${id}/annotations`, { version, boxes });
  },
  scan(folder) {
    return this._json("POST", "api/images/scan", { folder: folder || null });
  },
  predict(imageId, conf, iou) {
    return this._json("POST", "api/assist/predict", { image_id: imageId, conf, iou });
  },
  claimLock(id) {
    return this._json("POST", `api/locks/${id}`);
  },
  heartbeat(id) {
    return this._json("POST", `api/locks/${id}/heartbeat`);
  },
  releaseLock(id) {
    return this._json("DELETE", `api/locks/${id}`);
  },
  classes() {
    return this._json("GET", "api/classes");
  },
  async upload(files) {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const res = await fetch("api/images/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error("upload failed");
    return res.json();
  },
  async importRoboflow(file) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("api/images/import-roboflow", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error((data && data.detail) || "import failed");
    return data;
  },
  exportUrl() {
    return "api/export";
  },
};
