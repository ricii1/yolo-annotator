import datetime

import pytest

from app import repo

_NOW = datetime.datetime(2026, 6, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)


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


def test_create_image_stores_split(conn):
    img_id = repo.create_image(conn, "x.jpg", "images/x.jpg", 10, 10, "import", split="val")
    assert repo.get_image(conn, img_id)["split"] == "val"


def test_create_image_defaults_split_none(conn):
    img_id = repo.create_image(conn, "y.jpg", "images/y.jpg", 10, 10, "upload")
    assert repo.get_image(conn, img_id)["split"] is None


def test_list_images_includes_class_ids(conn, make_image):
    img = make_image()
    repo.save_annotations(
        conn,
        img,
        [_box(class_id=1), _box(class_id=3), _box(class_id=1)],
        expected_version=0,
    )
    listed = repo.list_images(conn, _NOW)
    assert sorted(listed[0]["class_ids"]) == [1, 3]  # distinct


def test_list_images_empty_class_ids_when_no_boxes(conn, make_image):
    make_image()
    assert repo.list_images(conn, _NOW)[0]["class_ids"] == []


def test_labeled_images_with_boxes_only_returns_labeled(conn, make_image):
    a = make_image(filename="a.jpg")
    make_image(filename="b.jpg")  # stays unlabeled
    repo.save_annotations(conn, a, [_box(class_id=1)], expected_version=0)
    result = repo.labeled_images_with_boxes(conn)
    assert len(result) == 1
    assert result[0]["filename"] == "a.jpg"
    assert len(result[0]["boxes"]) == 1
