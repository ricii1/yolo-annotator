import pytest

from app.export import split_images, build_data_yaml, format_label_lines


def test_split_is_deterministic_for_same_seed():
    ids = list(range(10))
    a = split_images(ids, val_ratio=0.2, seed=42)
    b = split_images(ids, val_ratio=0.2, seed=42)
    assert a == b


def test_split_val_ratio_count():
    ids = list(range(10))
    train, val = split_images(ids, val_ratio=0.2, seed=1)
    assert len(val) == 2
    assert len(train) == 8


def test_split_is_a_partition():
    ids = list(range(7))
    train, val = split_images(ids, val_ratio=0.3, seed=3)
    assert sorted(train + val) == ids
    assert set(train).isdisjoint(val)


def test_split_single_labeled_image_goes_to_train():
    # With one image, val rounds to 0 so the image trains; never an empty train.
    train, val = split_images([99], val_ratio=0.2, seed=1)
    assert train == [99]
    assert val == []


def test_build_data_yaml_contains_classes():
    text = build_data_yaml({0: "cat", 1: "dog"})
    assert "nc: 2" in text
    assert "train: images/train" in text
    assert "val: images/val" in text
    assert "cat" in text and "dog" in text


def test_format_label_lines_yolo_format():
    boxes = [
        {"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.3},
        {"class_id": 2, "cx": 0.1, "cy": 0.1, "w": 0.05, "h": 0.05},
    ]
    lines = format_label_lines(boxes)
    assert lines[0].split() == ["0", "0.5", "0.5", "0.2", "0.3"]
    assert lines[1].startswith("2 ")


def test_format_label_lines_empty_is_empty_list():
    assert format_label_lines([]) == []
