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


def _label(conn, make_image, filename, class_ids):
    img = make_image(filename=filename)
    boxes = [_box(class_id=c) for c in class_ids]
    repo.save_annotations(conn, img, boxes, expected_version=0)
    return img


def test_list_images_page_returns_total_and_bounded_page(conn, make_image):
    for i in range(10):
        make_image(filename=f"i{i}.jpg")
    page = repo.list_images_page(conn, _NOW, limit=3, offset=0)
    assert page["total"] == 10
    assert len(page["images"]) == 3
    assert [i["filename"] for i in page["images"]] == ["i0.jpg", "i1.jpg", "i2.jpg"]


def test_list_images_page_offset(conn, make_image):
    for i in range(10):
        make_image(filename=f"i{i}.jpg")
    page = repo.list_images_page(conn, _NOW, limit=3, offset=9)
    assert len(page["images"]) == 1
    assert page["images"][0]["filename"] == "i9.jpg"


def test_list_images_page_include_filter(conn, make_image):
    _label(conn, make_image, "cat.jpg", [0])
    _label(conn, make_image, "dog.jpg", [1])
    _label(conn, make_image, "both.jpg", [0, 1])
    page = repo.list_images_page(conn, _NOW, limit=50, offset=0, include=[0])
    names = {i["filename"] for i in page["images"]}
    assert names == {"cat.jpg", "both.jpg"}
    assert page["total"] == 2


def test_list_images_page_exclude_filter(conn, make_image):
    _label(conn, make_image, "cat.jpg", [0])
    _label(conn, make_image, "dog.jpg", [1])
    _label(conn, make_image, "both.jpg", [0, 1])
    page = repo.list_images_page(conn, _NOW, limit=50, offset=0, exclude=[1])
    names = {i["filename"] for i in page["images"]}
    assert names == {"cat.jpg"}


def test_list_images_page_include_and_exclude_combined(conn, make_image):
    _label(conn, make_image, "cat.jpg", [0])
    _label(conn, make_image, "both.jpg", [0, 1])
    page = repo.list_images_page(conn, _NOW, limit=50, offset=0, include=[0], exclude=[1])
    names = {i["filename"] for i in page["images"]}
    assert names == {"cat.jpg"}


def test_list_images_page_only_unlabeled(conn, make_image):
    _label(conn, make_image, "labeled.jpg", [0])
    make_image(filename="empty.jpg")  # no annotations
    page = repo.list_images_page(conn, _NOW, limit=50, offset=0, only_unlabeled=True)
    names = {i["filename"] for i in page["images"]}
    assert names == {"empty.jpg"}


def test_list_images_page_includes_class_ids_and_lock(conn, make_image):
    img = _label(conn, make_image, "x.jpg", [2, 4])
    from app import locks
    locks.claim_lock(conn, img, "sessZ", _NOW, ttl=60)
    page = repo.list_images_page(conn, _NOW, limit=50, offset=0)
    item = page["images"][0]
    assert sorted(item["class_ids"]) == [2, 4]
    assert item["locked_by"] == "sessZ"


def test_list_images_page_expired_lock_not_reported(conn, make_image):
    import datetime
    img = make_image()
    from app import locks
    locks.claim_lock(conn, img, "sessZ", _NOW, ttl=60)
    later = _NOW + datetime.timedelta(seconds=120)
    page = repo.list_images_page(conn, later, limit=50, offset=0)
    assert page["images"][0]["locked_by"] is None


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


def test_database_images_with_boxes_only_returns_database_stage(conn, make_image):
    a = make_image(filename="a.jpg")
    b = make_image(filename="b.jpg")  # labeled but not promoted
    repo.save_annotations(conn, a, [_box(class_id=1)], expected_version=0)
    repo.save_annotations(conn, b, [_box(class_id=2)], expected_version=0)
    repo.set_stage(conn, [a], "database")
    result = repo.database_images_with_boxes(conn)
    assert len(result) == 1  # b is labeled but still in 'annotating'
    assert result[0]["filename"] == "a.jpg"
    assert len(result[0]["boxes"]) == 1


def test_new_image_defaults_to_annotating_stage(conn, make_image):
    img = make_image()
    assert repo.get_image(conn, img)["stage"] == "annotating"


def test_set_stage_updates_single_and_many(conn, make_image):
    a = make_image(filename="a.jpg")
    b = make_image(filename="b.jpg")
    c = make_image(filename="c.jpg")
    assert repo.set_stage(conn, [a], "database") == 1
    assert repo.get_image(conn, a)["stage"] == "database"
    assert repo.set_stage(conn, [b, c], "database") == 2
    assert repo.get_image(conn, b)["stage"] == "database"
    assert repo.get_image(conn, c)["stage"] == "database"


def test_set_stage_empty_list_is_noop(conn):
    assert repo.set_stage(conn, [], "database") == 0


def test_list_images_page_filters_by_stage(conn, make_image):
    a = make_image(filename="a.jpg")
    make_image(filename="b.jpg")
    repo.set_stage(conn, [a], "database")
    db_page = repo.list_images_page(conn, _NOW, limit=50, offset=0, stage="database")
    assert {i["filename"] for i in db_page["images"]} == {"a.jpg"}
    assert db_page["total"] == 1
    ann_page = repo.list_images_page(conn, _NOW, limit=50, offset=0, stage="annotating")
    assert {i["filename"] for i in ann_page["images"]} == {"b.jpg"}
