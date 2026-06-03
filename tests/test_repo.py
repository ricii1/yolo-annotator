import pytest

from app import repo


def _box(class_id=0, cx=0.5, cy=0.5, w=0.2, h=0.2, source="manual"):
    return {"class_id": class_id, "cx": cx, "cy": cy, "w": w, "h": h, "source": source}


def test_save_annotations_bumps_version_from_zero(conn, make_image):
    img = make_image()
    new_version = repo.save_annotations(conn, img, [_box()], expected_version=0)
    assert new_version == 1
    assert repo.get_image(conn, img)["status"] == "labeled"


def test_save_annotations_persists_boxes(conn, make_image):
    img = make_image()
    repo.save_annotations(conn, img, [_box(class_id=3)], expected_version=0)
    boxes = repo.get_annotations(conn, img)
    assert len(boxes) == 1
    assert boxes[0]["class_id"] == 3


def test_save_replaces_previous_boxes(conn, make_image):
    img = make_image()
    v1 = repo.save_annotations(conn, img, [_box(), _box(class_id=1)], expected_version=0)
    repo.save_annotations(conn, img, [_box(class_id=2)], expected_version=v1)
    boxes = repo.get_annotations(conn, img)
    assert len(boxes) == 1
    assert boxes[0]["class_id"] == 2


def test_stale_version_save_is_rejected(conn, make_image):
    img = make_image()
    repo.save_annotations(conn, img, [_box()], expected_version=0)  # now version 1
    with pytest.raises(repo.StaleVersionError):
        repo.save_annotations(conn, img, [_box()], expected_version=0)


def test_saving_empty_set_marks_labeled(conn, make_image):
    img = make_image()
    new_version = repo.save_annotations(conn, img, [], expected_version=0)
    assert new_version == 1
    assert repo.get_annotations(conn, img) == []
    assert repo.get_image(conn, img)["status"] == "labeled"


def test_classes_round_trip(conn):
    repo.set_classes(conn, {0: "cat", 1: "dog"})
    assert repo.get_classes(conn) == {0: "cat", 1: "dog"}


def test_set_classes_replaces_existing(conn):
    repo.set_classes(conn, {0: "cat"})
    repo.set_classes(conn, {0: "bird", 1: "fish"})
    assert repo.get_classes(conn) == {0: "bird", 1: "fish"}


def test_labeled_images_with_boxes_only_returns_labeled(conn, make_image):
    a = make_image(filename="a.jpg")
    make_image(filename="b.jpg")  # stays unlabeled
    repo.save_annotations(conn, a, [_box(class_id=1)], expected_version=0)
    result = repo.labeled_images_with_boxes(conn)
    assert len(result) == 1
    assert result[0]["filename"] == "a.jpg"
    assert len(result[0]["boxes"]) == 1
