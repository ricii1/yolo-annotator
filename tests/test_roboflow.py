import datetime
import io
import zipfile

import pytest
from PIL import Image

from app import db, repo, roboflow

_NOW = datetime.datetime(2026, 6, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _png(w=32, h=32):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (123, 50, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _make_roboflow_zip():
    """A minimal Roboflow export: names cat/dog/bird, train + valid splits."""
    files = {
        "data.yaml": "nc: 3\nnames: ['cat', 'dog', 'bird']\n",
        "train/images/a.png": _png(),
        "train/labels/a.txt": "0 0.5 0.5 0.2 0.2\n1 0.3 0.3 0.1 0.1\n2 0.4 0.4 0.1 0.1\n",
        "valid/images/b.png": _png(),
        "valid/labels/b.txt": "1 0.2 0.2 0.1 0.1\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content if isinstance(content, bytes) else content)
    return buf.getvalue()


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()


def test_parse_names_list_form():
    text = "nc: 2\nnames: ['cat', 'dog']\n"
    assert roboflow.parse_names(text) == {0: "cat", 1: "dog"}


def test_parse_names_dict_form():
    text = "names:\n  0: cat\n  1: dog\n"
    assert roboflow.parse_names(text) == {0: "cat", 1: "dog"}


def test_parse_names_missing_raises():
    with pytest.raises(ValueError):
        roboflow.parse_names("train: images/train\n")


def test_normalize_split_maps_valid_to_val():
    assert roboflow.normalize_split("valid") == "val"
    assert roboflow.normalize_split("train") == "train"
    assert roboflow.normalize_split("test") == "test"


def test_build_class_remap_by_name_case_insensitive():
    zip_names = {0: "Cat", 1: "Dog", 2: "Bird"}
    model_names = {0: "dog", 1: "cat"}  # different order, no bird
    remap = roboflow.build_class_remap(zip_names, model_names)
    assert remap == {0: 1, 1: 0}  # cat->1, dog->0; bird omitted


def test_parse_label_file_reads_yolo_lines():
    text = "0 0.5 0.5 0.2 0.3\n2 0.1 0.1 0.05 0.05\n"
    boxes = roboflow.parse_label_file(text)
    assert boxes == [
        {"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.3},
        {"class_id": 2, "cx": 0.1, "cy": 0.1, "w": 0.05, "h": 0.05},
    ]


def test_parse_label_file_skips_blank_and_malformed():
    text = "0 0.5 0.5 0.2 0.3\n\n  \nbad line\n1 0.2 0.2 0.1\n"
    boxes = roboflow.parse_label_file(text)
    assert len(boxes) == 1  # only the first valid 5-field line


def test_remap_boxes_drops_unmatched_classes():
    boxes = [
        {"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2},
        {"class_id": 2, "cx": 0.1, "cy": 0.1, "w": 0.1, "h": 0.1},  # unmatched
    ]
    remap = {0: 5}  # only class 0 maps, to model id 5
    kept, skipped = roboflow.remap_boxes(boxes, remap)
    assert skipped == 1
    assert len(kept) == 1
    assert kept[0]["class_id"] == 5
    assert kept[0]["source"] == "manual"


def test_discover_splits_finds_roboflow_layout(tmp_path):
    for split in ("train", "valid", "test"):
        (tmp_path / split / "images").mkdir(parents=True)
        (tmp_path / split / "labels").mkdir(parents=True)
    found = roboflow.discover_splits(tmp_path)
    assert set(found.keys()) == {"train", "val", "test"}
    assert found["val"]["images"] == tmp_path / "valid" / "images"


def test_discover_splits_ignores_missing(tmp_path):
    (tmp_path / "train" / "images").mkdir(parents=True)
    (tmp_path / "train" / "labels").mkdir(parents=True)
    found = roboflow.discover_splits(tmp_path)
    assert set(found.keys()) == {"train"}


def test_discover_splits_handles_nested_root(tmp_path):
    # Roboflow zips often extract into a single subfolder.
    inner = tmp_path / "MyDataset.v1"
    for split in ("train", "valid"):
        (inner / split / "images").mkdir(parents=True)
        (inner / split / "labels").mkdir(parents=True)
    found = roboflow.discover_splits(tmp_path)
    assert set(found.keys()) == {"train", "val"}


def test_import_dataset_imports_images_labels_and_splits(conn, tmp_path):
    images_dir = tmp_path / "images"
    model_names = {0: "dog", 1: "cat"}  # note: no 'bird'
    summary = roboflow.import_dataset(
        _make_roboflow_zip(), conn, images_dir, model_names
    )

    assert summary["images_imported"] == 2
    assert summary["boxes_imported"] == 3  # a: cat+dog kept (bird dropped), b: dog
    assert summary["boxes_skipped"] == 1  # the 'bird' box
    assert summary["classes_skipped"] == ["bird"]

    images = repo.list_images(conn, _NOW)
    by_name = {i["filename"]: i for i in images}
    assert by_name["a.png"]["split"] == "train"
    assert by_name["b.png"]["split"] == "val"
    assert all(i["status"] == "labeled" for i in images)
    # 'a' boxes remapped: zip cat(0)->1, dog(1)->0
    assert sorted(by_name["a.png"]["class_ids"]) == [0, 1]
    # files actually copied to the store
    assert (images_dir / "a.png").exists()
    assert (images_dir / "b.png").exists()


def test_import_dataset_marks_unlabeled_image_as_labeled_background(conn, tmp_path):
    # an image whose label file is empty becomes a background sample (labeled, 0 boxes)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.yaml", "names: ['cat']\n")
        zf.writestr("train/images/c.png", _png())
        zf.writestr("train/labels/c.txt", "")
    summary = roboflow.import_dataset(buf.getvalue(), conn, tmp_path / "img", {0: "cat"})
    assert summary["images_imported"] == 1
    img = repo.list_images(conn, _NOW)[0]
    assert img["status"] == "labeled"
    assert img["class_ids"] == []
