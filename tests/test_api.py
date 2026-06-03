import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.inference import ModelService
from app.main import create_app


def _png(w=64, h=48, color=(0, 128, 255)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _fake_model():
    def predictor(path, conf):
        return [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2, "conf": 0.9}]

    return ModelService(predictor=predictor, names={0: "cat", 1: "dog"})


@pytest.fixture
def settings(tmp_path):
    return Settings(
        model_path="unused.pt",
        data_dir=tmp_path,
        device="cpu",
        lock_ttl=60,
        scan_dir=None,
        default_val_ratio=0.2,
    )


@pytest.fixture
def app(settings):
    application = create_app(settings=settings, model_service=_fake_model())
    with TestClient(application) as _started:  # runs lifespan (schema + classes)
        yield application


@pytest.fixture
def client(app):
    return TestClient(app)


def _upload(client, name="a.png", data=None):
    return client.post(
        "/api/images/upload",
        files=[("files", (name, data or _png(), "image/png"))],
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
    assert r.json()["skipped"] == ["bad.png"]
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


def test_export_produces_valid_yolo_zip(client):
    img_id = _upload(client).json()["created"][0]["id"]
    client.put(
        f"/api/images/{img_id}/annotations",
        json={"version": 0, "boxes": [{"class_id": 0, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}]},
    )
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


def test_export_without_labeled_images_is_400(client):
    _upload(client)  # uploaded but not labeled
    r = client.post("/api/export", json={})
    assert r.status_code == 400


def test_frontend_is_served(client):
    root = client.get("/")
    assert root.status_code == 200
    assert "YOLO Annotator" in root.text
    for asset in ("/js/api.js", "/js/canvas.js", "/js/app.js", "/css/app.css"):
        assert client.get(asset).status_code == 200, asset


def test_scan_folder_ingests_from_server_path(client, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "s1.png").write_bytes(_png(20, 20))
    r = client.post("/api/images/scan", json={"folder": str(incoming)})
    assert r.status_code == 200
    assert len(r.json()["created"]) == 1
