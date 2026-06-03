import pytest

from app.export import split_images, build_data_yaml, format_label_lines, assign_splits


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


def test_build_data_yaml_adds_test_when_requested():
    text = build_data_yaml({0: "cat"}, include_test=True)
    assert "test: images/test" in text


def test_build_data_yaml_omits_test_by_default():
    assert "test:" not in build_data_yaml({0: "cat"})


def test_assign_splits_honors_explicit_splits():
    images = [
        {"id": 1, "split": "train"},
        {"id": 2, "split": "val"},
        {"id": 3, "split": "test"},
    ]
    result = assign_splits(images, val_ratio=0.5, seed=1)
    assert result["train"] == [1]
    assert result["val"] == [2]
    assert result["test"] == [3]


def test_assign_splits_random_splits_unassigned():
    images = [{"id": i, "split": None} for i in range(10)]
    result = assign_splits(images, val_ratio=0.2, seed=1)
    assert len(result["val"]) == 2
    assert len(result["train"]) == 8
    assert result["test"] == []
    assert sorted(result["train"] + result["val"]) == list(range(10))


def test_assign_splits_mixes_explicit_and_random():
    images = [
        {"id": 1, "split": "test"},
        {"id": 2, "split": None},
        {"id": 3, "split": None},
    ]
    result = assign_splits(images, val_ratio=0.0, seed=1)
    assert result["test"] == [1]
    # val_ratio 0 -> both unassigned go to train
    assert result["train"] == [2, 3]
    assert result["val"] == []


def test_assign_splits_is_deterministic():
    images = [{"id": i, "split": None} for i in range(20)]
    assert assign_splits(images, 0.25, 7) == assign_splits(images, 0.25, 7)


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
