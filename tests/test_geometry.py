import pytest

from app.geometry import pixel_to_yolo, yolo_to_pixel, clamp_normalized


def test_pixel_to_yolo_center_box():
    # A 100x100 box at top-left (50,50) in a 200x200 image.
    cx, cy, w, h = pixel_to_yolo(50, 50, 100, 100, 200, 200)
    assert cx == pytest.approx(0.5)   # center x = (50+50)/200
    assert cy == pytest.approx(0.5)
    assert w == pytest.approx(0.5)
    assert h == pytest.approx(0.5)


def test_yolo_to_pixel_round_trip():
    cx, cy, w, h = pixel_to_yolo(30, 40, 60, 80, 300, 400)
    x, y, bw, bh = yolo_to_pixel(cx, cy, w, h, 300, 400)
    assert x == pytest.approx(30)
    assert y == pytest.approx(40)
    assert bw == pytest.approx(60)
    assert bh == pytest.approx(80)


def test_pixel_to_yolo_clamps_box_exceeding_bounds():
    # Box runs off the right/bottom edge; result must stay within 0..1.
    cx, cy, w, h = pixel_to_yolo(150, 150, 100, 100, 200, 200)
    assert 0.0 <= cx <= 1.0
    assert 0.0 <= cy <= 1.0
    assert cx + w / 2 <= 1.0 + 1e-9
    assert cy + h / 2 <= 1.0 + 1e-9


def test_pixel_to_yolo_clamps_negative_origin():
    cx, cy, w, h = pixel_to_yolo(-20, -20, 50, 50, 200, 200)
    assert cx - w / 2 >= -1e-9
    assert cy - h / 2 >= -1e-9


def test_pixel_to_yolo_rejects_zero_image_size():
    with pytest.raises(ValueError):
        pixel_to_yolo(0, 0, 10, 10, 0, 100)


def test_clamp_normalized_keeps_box_inside_unit_square():
    cx, cy, w, h = clamp_normalized(0.9, 0.9, 0.4, 0.4)
    assert cx - w / 2 >= -1e-9
    assert cy - h / 2 >= -1e-9
    assert cx + w / 2 <= 1.0 + 1e-9
    assert cy + h / 2 <= 1.0 + 1e-9


def test_clamp_normalized_passthrough_when_inside():
    assert clamp_normalized(0.5, 0.5, 0.2, 0.2) == (0.5, 0.5, 0.2, 0.2)
