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

  listImages() {
    return this._json("GET", "/api/images");
  },
  getImage(id) {
    return this._json("GET", `/api/images/${id}`);
  },
  saveAnnotations(id, version, boxes) {
    return this._json("PUT", `/api/images/${id}/annotations`, { version, boxes });
  },
  scan(folder) {
    return this._json("POST", "/api/images/scan", { folder: folder || null });
  },
  predict(imageId, conf) {
    return this._json("POST", "/api/assist/predict", { image_id: imageId, conf });
  },
  claimLock(id) {
    return this._json("POST", `/api/locks/${id}`);
  },
  heartbeat(id) {
    return this._json("POST", `/api/locks/${id}/heartbeat`);
  },
  releaseLock(id) {
    return this._json("DELETE", `/api/locks/${id}`);
  },
  classes() {
    return this._json("GET", "/api/classes");
  },
  async upload(files) {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const res = await fetch("/api/images/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error("upload failed");
    return res.json();
  },
  exportUrl() {
    return "/api/export";
  },
};
