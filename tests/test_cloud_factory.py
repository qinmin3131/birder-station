from types import SimpleNamespace

import pytest

from src.recognition.cloud.factory import RecognizerFactory, get_default_config
from src.recognition.protocol import RecognitionPlatform


def test_create_local_recognizer_passes_hf_mirror(monkeypatch):
    created = {}

    class StubLocalRecognizer:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(
        "src.recognition.cloud.factory.get_config",
        lambda: {"recognition": {"hf_mirror": "https://mirror.example"}},
    )
    monkeypatch.setattr(
        "src.recognition.inference_local.LocalBirdRecognizer",
        StubLocalRecognizer,
    )

    # 清空单例缓存，避免被其他测试污染
    saved = RecognizerFactory._local_recognizer
    RecognizerFactory._local_recognizer = None
    try:
        recognizer = RecognizerFactory.create(
            RecognitionPlatform.local.value,
            model_name="bioclip",
            device="cpu",
        )

        assert isinstance(recognizer, StubLocalRecognizer)
        assert created == {
            "model_name": "bioclip",
            "device": "cpu",
            "hf_mirror": "https://mirror.example",
        }
    finally:
        RecognizerFactory._local_recognizer = saved


def test_create_local_recognizer_caches_singleton_when_no_kwargs(monkeypatch):
    """无 kwargs 调用 create('local') 应复用进程级单例，避免每次请求都重建模型。"""
    created_count = {"n": 0}

    class StubLocalRecognizer:
        def __init__(self, **kwargs):
            created_count["n"] += 1
            self.kwargs = kwargs

    monkeypatch.setattr(
        "src.recognition.cloud.factory.get_config",
        lambda: {"recognition": {"hf_mirror": "https://mirror.example"}},
    )
    monkeypatch.setattr(
        "src.recognition.inference_local.LocalBirdRecognizer",
        StubLocalRecognizer,
    )

    saved = RecognizerFactory._local_recognizer
    RecognizerFactory._local_recognizer = None
    try:
        first = RecognizerFactory.create(RecognitionPlatform.local.value)
        second = RecognizerFactory.create(RecognitionPlatform.local.value)

        # 两次调用应返回同一实例，构造器只被调用一次
        assert first is second
        assert created_count["n"] == 1
        assert first.kwargs == {"hf_mirror": "https://mirror.example"}
    finally:
        RecognizerFactory._local_recognizer = saved


def test_create_local_recognizer_bypasses_cache_when_kwargs_passed(monkeypatch):
    """显式传 kwargs 时应绕过单例缓存，每次新建以尊重调用方参数。"""
    created_count = {"n": 0}

    class StubLocalRecognizer:
        def __init__(self, **kwargs):
            created_count["n"] += 1
            self.kwargs = kwargs

    monkeypatch.setattr(
        "src.recognition.cloud.factory.get_config",
        lambda: {"recognition": {"hf_mirror": "https://mirror.example"}},
    )
    monkeypatch.setattr(
        "src.recognition.inference_local.LocalBirdRecognizer",
        StubLocalRecognizer,
    )

    saved = RecognizerFactory._local_recognizer
    RecognizerFactory._local_recognizer = None
    try:
        first = RecognizerFactory.create(
            RecognitionPlatform.local.value, model_name="bioclip", device="cpu"
        )
        second = RecognizerFactory.create(
            RecognitionPlatform.local.value, model_name="bioclip-2", device="cuda"
        )

        # 两次都是新实例，构造器被调用两次
        assert first is not second
        assert created_count["n"] == 2
    finally:
        RecognizerFactory._local_recognizer = saved


def test_create_unknown_platform_raises_value_error():
    with pytest.raises(ValueError, match="Unknown platform: unknown"):
        RecognizerFactory.create("unknown")


def test_create_unavailable_recognizer_raises_runtime_error():
    class UnavailableRecognizer:
        def __init__(self, **kwargs):
            self.is_available = False

    original = RecognizerFactory._recognizers.copy()
    RecognizerFactory._recognizers["custom-test"] = UnavailableRecognizer
    try:
        with pytest.raises(RuntimeError, match="custom-test recognizer is not available"):
            RecognizerFactory.create("custom-test")
    finally:
        RecognizerFactory._recognizers = original


def test_create_wraps_unexpected_errors_in_runtime_error():
    class BrokenRecognizer:
        def __init__(self, **kwargs):
            raise RuntimeError("boom")

    original = RecognizerFactory._recognizers.copy()
    RecognizerFactory._recognizers["broken-test"] = BrokenRecognizer
    try:
        with pytest.raises(RuntimeError, match="Failed to initialize broken-test recognizer: boom"):
            RecognizerFactory.create("broken-test")
    finally:
        RecognizerFactory._recognizers = original


def test_create_from_request_uses_request_platform(monkeypatch):
    captured = {}

    def fake_create(platform, **kwargs):
        captured["platform"] = platform
        captured["kwargs"] = kwargs
        return "recognizer"

    monkeypatch.setattr(RecognizerFactory, "create", fake_create)
    request = SimpleNamespace(platform=RecognitionPlatform.huggingface)

    recognizer = RecognizerFactory.create_from_request(request)

    assert recognizer == "recognizer"
    assert captured == {"platform": "huggingface", "kwargs": {}}


def test_register_and_get_all_platforms():
    class CustomRecognizer:
        pass

    original = RecognizerFactory._recognizers.copy()
    try:
        RecognizerFactory.register("custom-added", CustomRecognizer)
        assert "custom-added" in RecognizerFactory.get_all_platforms()
    finally:
        RecognizerFactory._recognizers = original


def test_get_available_platforms_filters_unavailable_and_failures():
    class AvailableRecognizer:
        def __init__(self):
            self.is_available = True

    class UnavailableRecognizer:
        def __init__(self):
            self.is_available = False

    class BrokenRecognizer:
        def __init__(self):
            raise ValueError("bad init")

    original = RecognizerFactory._recognizers.copy()
    RecognizerFactory._recognizers = {
        "available-test": AvailableRecognizer,
        "unavailable-test": UnavailableRecognizer,
        "broken-test": BrokenRecognizer,
    }
    try:
        assert RecognizerFactory.get_available_platforms() == ["available-test"]
    finally:
        RecognizerFactory._recognizers = original


def test_get_default_config_reads_cloud_settings(monkeypatch):
    monkeypatch.setattr(
        "src.recognition.cloud.factory.get_config",
        lambda: {
            "cloud": {
                "huggingface": {"api_token": "hf-token", "model_id": "hf-model"},
                "modelscope": {"api_token": "ms-token", "model_id": "ms-model"},
                "aliyun": {"access_key_id": "ak", "access_key_secret": "secret"},
                "baidu": {"api_key": "bk", "secret_key": "bs"},
            }
        },
    )

    assert get_default_config() == {
        "huggingface": {"api_token": "hf-token", "model_id": "hf-model"},
        "modelscope": {"api_token": "ms-token", "model_id": "ms-model"},
        "aliyun": {"access_key_id": "ak", "access_key_secret": "secret"},
        "baidu": {"api_key": "bk", "secret_key": "bs"},
    }
