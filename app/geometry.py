"""Coordinate conversion between pixel boxes and YOLO normalized boxes.

A pixel box is (x, y, w, h) where (x, y) is the top-left corner.
A YOLO box is (cx, cy, w, h) with the center point and size, all normalized
to 0..1 relative to image dimensions.
"""
from __future__ import annotations


def clamp_normalized(cx: float, cy: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Clamp a normalized box so it stays fully inside the unit square.

    Width/height are clamped to 0..1 first, then the center is pulled in so the
    box edges do not cross 0 or 1.
    """
    w = min(max(w, 0.0), 1.0)
    h = min(max(h, 0.0), 1.0)
    half_w = w / 2
    half_h = h / 2
    cx = min(max(cx, half_w), 1.0 - half_w)
    cy = min(max(cy, half_h), 1.0 - half_h)
    return (cx, cy, w, h)


def pixel_to_yolo(
    x: float, y: float, w: float, h: float, img_w: int, img_h: int
) -> tuple[float, float, float, float]:
    """Convert a top-left pixel box to a clamped YOLO normalized box."""
    if img_w <= 0 or img_h <= 0:
        raise ValueError("image dimensions must be positive")
    cx = (x + w / 2) / img_w
    cy = (y + h / 2) / img_h
    nw = w / img_w
    nh = h / img_h
    return clamp_normalized(cx, cy, nw, nh)


def yolo_to_pixel(
    cx: float, cy: float, w: float, h: float, img_w: int, img_h: int
) -> tuple[float, float, float, float]:
    """Convert a YOLO normalized box to a top-left pixel box."""
    if img_w <= 0 or img_h <= 0:
        raise ValueError("image dimensions must be positive")
    pw = w * img_w
    ph = h * img_h
    px = cx * img_w - pw / 2
    py = cy * img_h - ph / 2
    return (px, py, pw, ph)
