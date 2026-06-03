from app.config import resolve_device


def test_resolve_device_auto_prefers_cuda():
    assert resolve_device("auto", cuda_available=True) == "cuda"


def test_resolve_device_auto_falls_back_to_cpu():
    assert resolve_device("auto", cuda_available=False) == "cpu"


def test_resolve_device_explicit_is_respected():
    assert resolve_device("cpu", cuda_available=True) == "cpu"
    assert resolve_device("cuda:0", cuda_available=True) == "cuda:0"
