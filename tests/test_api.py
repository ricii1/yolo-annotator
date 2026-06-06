import hashlib
import io
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.embeddings import EmbeddingService
from app.inference import ModelService
from app.main import create_app


def _png(w=64, h=48, color=(0, 128, 255)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _fake_model(captured=None):
    def predictor(path, conf, iou):
        if captured is not None:
            captured["conf"] = conf
            captured["iou"] = iou
        return [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2, "conf": 0.9}]

    return ModelService(predictor=predictor, names={0: "cat", 1: "dog"})


def _fake_embedder(dim=16):
    """Deterministic, content-derived unit vectors — no CLIP, no GPU.

    Identical image bytes yield identical vectors, so a query that matches a
    stored image scores ~1.0 and ranks first.
    """
    def embedder(image_path):
        raw = open(image_path, "rb").read()
        seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
        vec = np.random.default_rng(seed).standard_normal(dim).astype("float32")
        return vec / np.linalg.norm(vec)

    return EmbeddingService(embedder=embedder, dim=dim, model_name="fake")


@pytest.fixture
def settings(tmp_path):
    return Settings(
        model_path="unused.pt",
        data_dir=tmp_path,
        device="cpu",
        lock_ttl=60,
        scan_dir=None,
        default_val_ratio=0.2,
        embed_model="fake",
    )


@pytest.fixture
def app(settings):
    application = create_app(
        settings=settings, model_service=_fake_model(), embedding_service=_fake_embedder()
    )
    with TestClient(application) as _started:  # runs lifespan (schema + classes)
        yield application


@pytest.fixture
def client(app):
    return TestClient(app)


def _upload(client, name="a.png", data=None):
    if data is None:
        seed = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
        data = _png(color=(seed % 256, (seed >> 8) % 256, (seed >> 16) % 256))
    return client.post(
        "/api/images/upload",
        files=[("files", (name, data, "image/png"))],
    )


def test_classes_loaded_from_model(client):
    r = client.get("/api/classes")
    assert r.status_code == 200
    assert r.json()["classes"] == {"0": "cat", "1": "dog"}


def test_upload_then_list(client):
    r = _upload(client)
    assert r.status_code == 200
    assert len(r.json()["created"]) == 1
    listing = client.get("/api/images").json()
    assert len(listing["images"]) == 1
    assert listing["images"][0]["width"] == 64


def test_upload_rejects_non_image(client):
    r = client.post(
        "/api/images/upload",
        files=[("files", ("bad.png", b"nope", "image/png"))],
    )
    assert r.status_code == 200
    skipped = r.json()["skipped"]
    assert len(skipped) == 1
    assert skipped[0]["filename"] == "bad.png"
    assert skipped[0]["reason"] == "invalid"
    assert r.json()["created"] == []


def test_upload_duplicate_is_blocked_with_existing_id(client):
    data = _png()
    first_id = _upload(client, name="orig.png", data=data).json()["created"][0]["id"]
    r = _upload(client, name="copy.png", data=data)
    assert r.status_code == 200
    assert r.json()["created"] == []
    skipped = r.json()["skipped"]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "duplicate"
    assert skipped[0]["existing_id"] == first_id


def test_scan_skips_hash_duplicate(client, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    data = _png(20, 20)
    (incoming / "s1.png").write_bytes(data)
    # Upload same bytes under a different name so filename-dedup doesn't trigger
    _upload(client, name="already.png", data=data)
    r = client.post("/api/images/scan", json={"folder": str(incoming)})
    assert r.status_code == 200
    assert r.json()["created"] == []


def test_save_and_reload_annotations(client):
    img_id = _upload(client).json()["created"][0]["id"]
    save = client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 1, "cx": 0.5, "cy": 0.5, "w": 0.3, "h": 0.3}]},
    )
    assert save.status_code == 200
    assert save.json()["version"] == 1
    detail = client.get(f"/api/images/{img_id}").json()
    assert detail["version"] == 1
    assert len(detail["annotations"]) == 1
    assert detail["annotations"][0]["class_id"] == 1


def test_stale_save_returns_409(client):
    img_id = _upload(client).json()["created"][0]["id"]
    client.put(f"/api/images/{img_id}/annotations", json={"version": 0, "boxes": []})
    second = client.put(f"/api/images/{img_id}/annotations", json={"version": 0, "boxes": []})
    assert second.status_code == 409
    assert second.json()["detail"]["current_version"] == 1


def test_lock_blocks_other_session_from_saving(app):
    alice = TestClient(app)
    bob = TestClient(app)
    img_id = _upload(alice).json()["created"][0]["id"]

    assert alice.post(f"/api/locks/{img_id}").status_code == 200
    # Bob cannot claim the lock...
    assert bob.post(f"/api/locks/{img_id}").status_code == 423
    # ...nor save over it.
    blocked = bob.put(f"/api/images/{img_id}/annotations", json={"version": 0, "boxes": []})
    assert blocked.status_code == 423
    # Alice, the holder, can save.
    assert alice.put(f"/api/images/{img_id}/annotations", json={"version": 0, "boxes": []}).status_code == 200


def test_lock_release_allows_other_session(app):
    alice = TestClient(app)
    bob = TestClient(app)
    img_id = _upload(alice).json()["created"][0]["id"]
    alice.post(f"/api/locks/{img_id}")
    alice.delete(f"/api/locks/{img_id}")
    assert bob.post(f"/api/locks/{img_id}").status_code == 200


def test_assist_predict_returns_boxes(client):
    img_id = _upload(client).json()["created"][0]["id"]
    r = client.post("/api/assist/predict", json={"image_id": img_id, "conf": 0.25})
    assert r.status_code == 200
    boxes = r.json()["boxes"]
    assert boxes[0]["class_id"] == 0
    assert boxes[0]["conf"] == 0.9


def test_assist_predict_forwards_conf_and_iou(settings):
    captured = {}
    app = create_app(settings=settings, model_service=_fake_model(captured))
    with TestClient(app) as client:
        img_id = _upload(client).json()["created"][0]["id"]
        r = client.post(
            "/api/assist/predict",
            json={"image_id": img_id, "conf": 0.6, "iou": 0.3},
        )
        assert r.status_code == 200
    assert captured == {"conf": 0.6, "iou": 0.3}


def test_export_produces_valid_yolo_zip(client):
    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
    client.post("/api/images/stage", json={"image_ids": [img_id], "stage": "database"})
    r = client.post("/api/export", json={"val_ratio": 0.0, "seed": 1})
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "data.yaml" in names
    assert any(n.startswith("images/train/") for n in names)
    assert any(n.startswith("labels/train/") and n.endswith(".txt") for n in names)
    label_name = next(n for n in names if n.startswith("labels/train/"))
    assert zf.read(label_name).decode().strip() == "0 0.5 0.5 0.2 0.2"
    assert "nc: 2" in zf.read("data.yaml").decode()


def test_export_without_database_images_is_400(client):
    _upload(client)  # uploaded but never promoted to the Database stage
    r = client.post("/api/export", json={})
    assert r.status_code == 400


def _roboflow_zip():
    files = {
        "data.yaml": "names: ['cat', 'dog']\n",
        "train/images/a.png": _png(color=(10, 20, 30)),
        "train/labels/a.txt": "0 0.5 0.5 0.2 0.2\n",
        "valid/images/b.png": _png(color=(40, 50, 60)),
        "valid/labels/b.txt": "1 0.3 0.3 0.1 0.1\n",
        "test/images/c.png": _png(color=(70, 80, 90)),
        "test/labels/c.txt": "0 0.4 0.4 0.2 0.2\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_import_roboflow_then_list_with_class_ids(client):
    r = client.post(
        "/api/images/import-roboflow",
        files=[("file", ("ds.zip", _roboflow_zip(), "application/zip"))],
    )
    assert r.status_code == 200
    summary = r.json()
    assert summary["images_imported"] == 3
    assert summary["boxes_imported"] == 3
    listing = client.get("/api/images").json()["images"]
    splits = {i["filename"]: i["split"] for i in listing}
    assert splits == {"a.png": "train", "b.png": "val", "c.png": "test"}
    # every listed image carries its class ids for filtering
    assert all("class_ids" in i for i in listing)


def test_import_roboflow_rejects_bad_zip(client):
    r = client.post(
        "/api/images/import-roboflow",
        files=[("file", ("x.zip", b"not a zip", "application/zip"))],
    )
    assert r.status_code == 400


def test_roboflow_import_skips_hash_duplicate(client):
    # Pre-upload one of the zip images (same bytes as train/a.png)
    _upload(client, name="pre.png", data=_png(color=(10, 20, 30)))
    r = client.post(
        "/api/images/import-roboflow",
        files=[("file", ("ds.zip", _roboflow_zip(), "application/zip"))],
    )
    assert r.status_code == 200
    # a.png (color 10,20,30) already in DB → only b.png and c.png imported
    assert r.json()["images_imported"] == 2


def test_export_preserves_imported_splits(client):
    client.post(
        "/api/images/import-roboflow",
        files=[("file", ("ds.zip", _roboflow_zip(), "application/zip"))],
    )
    ids = [i["id"] for i in client.get("/api/images").json()["images"]]
    client.post("/api/images/stage", json={"image_ids": ids, "stage": "database"})
    r = client.post("/api/export", json={})
    assert r.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert any(n.startswith("images/train/") for n in names)
    assert any(n.startswith("images/val/") for n in names)
    assert any(n.startswith("images/test/") for n in names)
    yaml_text = zipfile.ZipFile(io.BytesIO(r.content)).read("data.yaml").decode()
    assert "test: images/test" in yaml_text


def test_list_images_paginates(client):
    for i in range(5):
        _upload(client, name=f"p{i}.png")
    page = client.get("/api/images?limit=2&offset=0").json()
    assert page["total"] == 5
    assert len(page["images"]) == 2
    assert page["limit"] == 2
    page2 = client.get("/api/images?limit=2&offset=4").json()
    assert len(page2["images"]) == 1


def test_list_images_server_side_class_filter(client):
    a = _upload(client, name="a.png").json()["created"][0]["id"]
    b = _upload(client, name="b.png").json()["created"][0]["id"]
    client.put(f"/api/images/{a}/annotations",
               json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]})
    client.put(f"/api/images/{b}/annotations",
               json={"version": 0, "boxes": [{"class_id": 1, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]})
    inc = client.get("/api/images?include=0").json()
    assert {i["filename"] for i in inc["images"]} == {"a.png"}
    exc = client.get("/api/images?exclude=1").json()
    assert {i["filename"] for i in exc["images"]} == {"a.png"}
    unl = client.get("/api/images?only_unlabeled=true").json()
    assert unl["total"] == 0  # both labeled


def test_new_image_defaults_to_annotating_stage(client):
    _upload(client)
    img = client.get("/api/images").json()["images"][0]
    assert img["stage"] == "annotating"


def test_set_stage_promotes_and_is_filterable(client):
    a = _upload(client, name="a.png").json()["created"][0]["id"]
    b = _upload(client, name="b.png").json()["created"][0]["id"]
    r = client.post("/api/images/stage", json={"image_ids": [a], "stage": "database"})
    assert r.status_code == 200
    assert r.json()["updated"] == 1

    db_list = client.get("/api/images?stage=database").json()
    assert {i["filename"] for i in db_list["images"]} == {"a.png"}
    ann_list = client.get("/api/images?stage=annotating").json()
    assert {i["filename"] for i in ann_list["images"]} == {"b.png"}


def test_set_stage_is_reversible(client):
    a = _upload(client, name="a.png").json()["created"][0]["id"]
    client.post("/api/images/stage", json={"image_ids": [a], "stage": "database"})
    client.post("/api/images/stage", json={"image_ids": [a], "stage": "annotating"})
    assert client.get("/api/images?stage=database").json()["total"] == 0
    assert client.get("/api/images?stage=annotating").json()["total"] == 1


def test_set_stage_rejects_invalid_stage(client):
    a = _upload(client).json()["created"][0]["id"]
    r = client.post("/api/images/stage", json={"image_ids": [a], "stage": "bogus"})
    assert r.status_code == 422


def test_labeled_image_stays_in_annotating_until_promoted(client):
    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
    img = client.get("/api/images").json()["images"][0]
    assert img["status"] == "labeled"
    assert img["stage"] == "annotating"  # labeling does not auto-promote


def test_thumb_returns_jpeg(client):
    img_id = _upload(client).json()["created"][0]["id"]
    r = client.get(f"/api/images/{img_id}/thumb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    Image.open(io.BytesIO(r.content)).verify()  # decodable image


def test_stage_all_promotes_every_matching_image(client):
    for i in range(3):
        _upload(client, name=f"s{i}.png")
    r = client.post("/api/images/stage/all", json={"stage": "database", "source_stage": "annotating"})
    assert r.json()["updated"] == 3
    assert client.get("/api/images?stage=database").json()["total"] == 3
    assert client.get("/api/images?stage=annotating").json()["total"] == 0


def test_search_by_upload_ranks_exact_match_first(client):
    match = _png(color=(10, 20, 30))
    a = _upload(client, name="a.png", data=match).json()["created"][0]["id"]
    _upload(client, name="b.png", data=_png(color=(200, 100, 50)))
    r = client.post(
        "/api/search/by-upload",
        files=[("file", ("q.png", match, "image/png"))],
        data={"k": "10"},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["image_id"] == a
    assert results[0]["score"] > 0.99


def test_search_similar_finds_self_first(client):
    a = _upload(client, name="a.png", data=_png(color=(10, 20, 30))).json()["created"][0]["id"]
    _upload(client, name="b.png", data=_png(color=(200, 100, 50)))
    r = client.post("/api/search/similar", json={"image_id": a, "k": 10})
    assert r.status_code == 200
    assert r.json()["results"][0]["image_id"] == a


def test_search_similar_unknown_image_is_404(client):
    r = client.post("/api/search/similar", json={"image_id": 999999})
    assert r.status_code == 404


def test_search_disabled_without_embedder(settings):
    # No embedding_service injected → search returns 503, app still serves.
    application = create_app(settings=settings, model_service=_fake_model())
    with TestClient(application) as c:
        img_id = _upload(c).json()["created"][0]["id"]
        r = c.post("/api/search/similar", json={"image_id": img_id})
        assert r.status_code == 503


def test_splits_counts_and_rebalance(client):
    for i in range(10):
        _upload(client, name=f"r{i}.png")
    client.post("/api/images/stage/all", json={"stage": "database"})
    before = client.get("/api/splits").json()
    assert before["total"] == 10 and before["unassigned"] == 10

    r = client.post("/api/splits/rebalance", json={"train": 0.7, "val": 0.2, "test": 0.1, "seed": 1})
    after = r.json()
    assert after["total"] == 10 and after["unassigned"] == 0
    assert (after["train"], after["val"], after["test"]) == (7, 2, 1)


def test_rebalance_rejects_ratios_over_one(client):
    r = client.post("/api/splits/rebalance", json={"train": 0.1, "val": 0.7, "test": 0.5})
    assert r.status_code == 422


def test_export_uses_rebalanced_test_split(client):
    for i in range(10):
        _upload(client, name=f"e{i}.png")
    client.post("/api/images/stage/all", json={"stage": "database"})
    client.post("/api/splits/rebalance", json={"train": 0.6, "val": 0.2, "test": 0.2, "seed": 3})
    r = client.post("/api/export", json={})
    assert r.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert any(n.startswith("images/test/") for n in names)


def test_frontend_is_served(client):
    root = client.get("/")
    assert root.status_code == 200
    assert "YOLO Annotator" in root.text
    for asset in (
        "/js/api.js", "/js/canvas.js", "/js/app.js", "/js/grid.js",
        "/js/database.js", "/js/splits.js", "/js/router.js", "/css/app.css",
    ):
        assert client.get(asset).status_code == 200, asset


def test_scan_folder_ingests_from_server_path(client, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "s1.png").write_bytes(_png(20, 20))
    r = client.post("/api/images/scan", json={"folder": str(incoming)})
    assert r.status_code == 200
    assert len(r.json()["created"]) == 1
