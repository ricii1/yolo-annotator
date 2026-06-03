// BoxCanvas: draws an image plus normalized bounding boxes and handles
// drawing, selecting, moving, resizing, and deleting boxes.
//
// Boxes are kept in normalized YOLO form: {class_id, cx, cy, w, h, source}.
// All rendering converts normalized <-> canvas pixels using the displayed size.

const HANDLE = 8; // px hit radius for resize handles

class BoxCanvas {
  constructor(canvas, { onChange, onSelect }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onChange = onChange || (() => {});
    this.onSelect = onSelect || (() => {});
    this.img = null;
    this.boxes = [];
    this.classes = {}; // {id: name}
    this.currentClass = 0;
    this.selected = -1;
    this.readOnly = false;
    this.drag = null; // active interaction state
    this._bind();
  }

  setClasses(classes) {
    this.classes = classes;
  }
  setCurrentClass(id) {
    this.currentClass = id;
  }

  load(imgEl, boxes, readOnly) {
    this.img = imgEl;
    this.boxes = boxes.map((b) => ({ ...b }));
    this.selected = -1;
    this.readOnly = !!readOnly;
    this._resize();
    this.render();
    this.onSelect(-1);
  }

  setBoxes(boxes) {
    this.boxes = boxes.map((b) => ({ ...b }));
    this.selected = -1;
    this.render();
    this.onSelect(-1);
    this.onChange();
  }

  getBoxes() {
    return this.boxes.map((b) => ({
      class_id: b.class_id,
      cx: b.cx,
      cy: b.cy,
      w: b.w,
      h: b.h,
      source: b.source || "manual",
    }));
  }

  deleteSelected() {
    if (this.selected >= 0) {
      this.boxes.splice(this.selected, 1);
      this.selected = -1;
      this.render();
      this.onSelect(-1);
      this.onChange();
    }
  }

  assignClassToSelected(classId) {
    if (this.selected >= 0) {
      this.boxes[this.selected].class_id = classId;
      this.boxes[this.selected].source = "manual";
      this.render();
      this.onSelect(this.selected);
      this.onChange();
    }
  }

  selectIndex(i) {
    this.selected = i;
    this.render();
    this.onSelect(i);
  }

  // ---- geometry helpers (canvas px space) ----
  _resize() {
    const maxW = this.canvas.parentElement.clientWidth - 2;
    const maxH = this.canvas.parentElement.clientHeight - 2;
    const iw = this.img.naturalWidth;
    const ih = this.img.naturalHeight;
    const scale = Math.min(maxW / iw, maxH / ih, 1);
    this.canvas.width = Math.max(1, Math.round(iw * scale));
    this.canvas.height = Math.max(1, Math.round(ih * scale));
  }

  _boxPx(b) {
    const W = this.canvas.width;
    const H = this.canvas.height;
    return {
      x: (b.cx - b.w / 2) * W,
      y: (b.cy - b.h / 2) * H,
      w: b.w * W,
      h: b.h * H,
    };
  }

  _pxToNorm(x, y, w, h) {
    const W = this.canvas.width;
    const H = this.canvas.height;
    let cx = (x + w / 2) / W;
    let cy = (y + h / 2) / H;
    let nw = w / W;
    let nh = h / H;
    return this._clamp(cx, cy, nw, nh);
  }

  _clamp(cx, cy, w, h) {
    w = Math.min(Math.max(w, 0), 1);
    h = Math.min(Math.max(h, 0), 1);
    cx = Math.min(Math.max(cx, w / 2), 1 - w / 2);
    cy = Math.min(Math.max(cy, h / 2), 1 - h / 2);
    return { cx, cy, w, h };
  }

  _mouse(e) {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  _handles(p) {
    // 8 resize handles around a px rect
    return {
      nw: { x: p.x, y: p.y },
      n: { x: p.x + p.w / 2, y: p.y },
      ne: { x: p.x + p.w, y: p.y },
      e: { x: p.x + p.w, y: p.y + p.h / 2 },
      se: { x: p.x + p.w, y: p.y + p.h },
      s: { x: p.x + p.w / 2, y: p.y + p.h },
      sw: { x: p.x, y: p.y + p.h },
      w: { x: p.x, y: p.y + p.h / 2 },
    };
  }

  _hitHandle(m) {
    if (this.selected < 0) return null;
    const p = this._boxPx(this.boxes[this.selected]);
    const hs = this._handles(p);
    for (const [name, pt] of Object.entries(hs)) {
      if (Math.abs(m.x - pt.x) <= HANDLE && Math.abs(m.y - pt.y) <= HANDLE) return name;
    }
    return null;
  }

  _hitBox(m) {
    // topmost box under the cursor
    for (let i = this.boxes.length - 1; i >= 0; i--) {
      const p = this._boxPx(this.boxes[i]);
      if (m.x >= p.x && m.x <= p.x + p.w && m.y >= p.y && m.y <= p.y + p.h) return i;
    }
    return -1;
  }

  // ---- interaction ----
  _bind() {
    this.canvas.addEventListener("mousedown", (e) => this._down(e));
    window.addEventListener("mousemove", (e) => this._move(e));
    window.addEventListener("mouseup", (e) => this._up(e));
  }

  _down(e) {
    if (!this.img || this.readOnly) return;
    const m = this._mouse(e);
    const handle = this._hitHandle(m);
    if (handle) {
      const p = this._boxPx(this.boxes[this.selected]);
      this.drag = { mode: "resize", handle, start: m, orig: p };
      return;
    }
    const hit = this._hitBox(m);
    if (hit >= 0) {
      this.selectIndex(hit);
      const p = this._boxPx(this.boxes[hit]);
      this.drag = { mode: "move", start: m, orig: p };
      return;
    }
    // start a new box
    this.selectIndex(-1);
    this.drag = { mode: "create", start: m, cur: m };
    this.render();
  }

  _move(e) {
    if (!this.drag) return;
    const m = this._mouse(e);
    if (this.drag.mode === "create") {
      this.drag.cur = m;
      this.render();
      this._drawRect(this.drag.start, m, "#22d3ee");
    } else if (this.drag.mode === "move") {
      const dx = m.x - this.drag.start.x;
      const dy = m.y - this.drag.start.y;
      const o = this.drag.orig;
      const n = this._pxToNorm(o.x + dx, o.y + dy, o.w, o.h);
      Object.assign(this.boxes[this.selected], n);
      this.render();
    } else if (this.drag.mode === "resize") {
      this._applyResize(m);
      this.render();
    }
  }

  _up(e) {
    if (!this.drag) return;
    const d = this.drag;
    this.drag = null;
    if (d.mode === "create") {
      const m = this._mouse(e);
      const x = Math.min(d.start.x, m.x);
      const y = Math.min(d.start.y, m.y);
      const w = Math.abs(m.x - d.start.x);
      const h = Math.abs(m.y - d.start.y);
      if (w < 4 || h < 4) {
        this.render();
        return; // ignore accidental clicks
      }
      const n = this._pxToNorm(x, y, w, h);
      this.boxes.push({ class_id: this.currentClass, source: "manual", ...n });
      this.selectIndex(this.boxes.length - 1);
      this.onChange();
    } else if (d.mode === "move" || d.mode === "resize") {
      this.onChange();
    }
  }

  _applyResize(m) {
    const o = this.drag.orig;
    let { x, y, w, h } = o;
    let x2 = x + w;
    let y2 = y + h;
    const hdl = this.drag.handle;
    if (hdl.includes("w")) x = m.x;
    if (hdl.includes("e")) x2 = m.x;
    if (hdl.includes("n")) y = m.y;
    if (hdl.includes("s")) y2 = m.y;
    const nx = Math.min(x, x2);
    const ny = Math.min(y, y2);
    const nw = Math.abs(x2 - x);
    const nh = Math.abs(y2 - y);
    const n = this._pxToNorm(nx, ny, nw, nh);
    Object.assign(this.boxes[this.selected], n);
  }

  // ---- rendering ----
  _color(classId) {
    const palette = [
      "#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6",
      "#ec4899", "#14b8a6", "#eab308", "#f97316", "#a855f7",
    ];
    return palette[classId % palette.length];
  }

  _drawRect(a, b, color) {
    const ctx = this.ctx;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 4]);
    ctx.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
    ctx.restore();
  }

  render() {
    if (!this.img) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.drawImage(this.img, 0, 0, this.canvas.width, this.canvas.height);
    this.boxes.forEach((b, i) => {
      const p = this._boxPx(b);
      const isDraft = b.source === "assist";
      const color = this._color(b.class_id);
      ctx.save();
      ctx.lineWidth = i === this.selected ? 3 : 2;
      ctx.strokeStyle = color;
      if (isDraft) ctx.setLineDash([6, 4]);
      ctx.strokeRect(p.x, p.y, p.w, p.h);
      // label
      const name = this.classes[b.class_id] ?? b.class_id;
      const text = isDraft ? `${name} ?` : `${name}`;
      ctx.setLineDash([]);
      ctx.font = "12px system-ui, sans-serif";
      const tw = ctx.measureText(text).width + 8;
      ctx.fillStyle = color;
      ctx.fillRect(p.x, Math.max(0, p.y - 16), tw, 16);
      ctx.fillStyle = "#fff";
      ctx.fillText(text, p.x + 4, Math.max(11, p.y - 4));
      ctx.restore();
      if (i === this.selected && !this.readOnly) this._drawHandles(p);
    });
  }

  _drawHandles(p) {
    const ctx = this.ctx;
    ctx.save();
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#111";
    for (const pt of Object.values(this._handles(p))) {
      ctx.beginPath();
      ctx.rect(pt.x - 4, pt.y - 4, 8, 8);
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }
}
