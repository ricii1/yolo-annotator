import asyncio

from app.inference import ModelService, boxes_from_result


class _FakeBoxes:
    def __init__(self, xywhn, cls, conf):
        self.xywhn = xywhn
        self.cls = cls
        self.conf = conf


class _FakeResult:
    def __init__(self, xywhn, cls, conf):
        self.boxes = _FakeBoxes(xywhn, cls, conf)


def test_boxes_from_result_converts_to_normalized_dicts():
    result = _FakeResult(
        xywhn=[[0.5, 0.5, 0.2, 0.3], [0.1, 0.2, 0.05, 0.05]],
        cls=[0.0, 2.0],
        conf=[0.9, 0.42],
    )
    boxes = boxes_from_result(result)
    assert boxes[0] == {
        "class_id": 0,
        "cx": 0.5,
        "cy": 0.5,
        "w": 0.2,
        "h": 0.3,
        "conf": 0.9,
    }
    assert boxes[1]["class_id"] == 2
    assert boxes[1]["conf"] == 0.42


def test_boxes_from_result_handles_no_detections():
    assert boxes_from_result(_FakeResult([], [], [])) == []


def test_model_service_returns_predictor_output():
    service = ModelService(
        predictor=lambda path, conf: [{"class_id": 1, "cx": 0.5, "cy": 0.5, "w": 0.1, "h": 0.1, "conf": 0.8}],
        names={0: "cat", 1: "dog"},
    )
    boxes = asyncio.run(service.predict("img.jpg", conf=0.25))
    assert boxes[0]["class_id"] == 1


def test_model_service_serializes_concurrent_calls():
    state = {"active": 0, "max_active": 0}

    def predictor(path, conf):
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        # busy work while "holding" the GPU
        for _ in range(1000):
            pass
        state["active"] -= 1
        return []

    service = ModelService(predictor=predictor, names={})

    async def run_many():
        await asyncio.gather(*(service.predict("x", 0.25) for _ in range(8)))

    asyncio.run(run_many())
    assert state["max_active"] == 1  # never two predicts at once
