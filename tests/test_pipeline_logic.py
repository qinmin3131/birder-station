import pytest
import os
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.pipeline_runner import WingScribePipeline
from src.core.io.local import LocalProvider

# Mocking the pipeline to avoid loading heavy models during init
class MockPipeline(WingScribePipeline):
    def __init__(self):
        # Skip super init
        pass


def _make_entry(path: Path):
    return SimpleNamespace(path=str(path), name=path.name, size=path.stat().st_size, is_dir=False)

def test_file_hash(tmp_path):
    # Create a dummy file
    p = tmp_path / "test_file.jpg"
    p.write_bytes(b"A" * 5000 + b"B" * 5000 + b"C" * 5000)

    pipeline = MockPipeline()
    provider = LocalProvider(str(tmp_path))
    h1 = pipeline._calculate_file_hash(provider, str(p), 15000)

    # Create duplicate file
    p2 = tmp_path / "test_file_2.jpg"
    p2.write_bytes(b"A" * 5000 + b"B" * 5000 + b"C" * 5000)
    h2 = pipeline._calculate_file_hash(provider, str(p2), 15000)

    assert h1 == h2

    # Create diff file (diff at end)
    p3 = tmp_path / "test_file_3.jpg"
    p3.write_bytes(b"A" * 5000 + b"B" * 5000 + b"D" * 5000)
    h3 = pipeline._calculate_file_hash(provider, str(p3), 15000)

    assert h1 != h3


def test_recognize_batch_uses_supplied_candidate_labels(tmp_path):
    class FakeRecognizer:
        def __init__(self):
            self.calls = []

        def predict_batch(self, image_paths, candidate_labels, top_k=5):
            self.calls.append((list(image_paths), list(candidate_labels), top_k))
            return [[{"scientific_name": "Passer montanus", "confidence": 0.95}] for _ in image_paths]

    pipeline = MockPipeline()
    pipeline.recognizer = FakeRecognizer()
    pipeline.config = {"recognition": {"top_k": 3, "alternatives_threshold": 70, "low_confidence_threshold": 60}}

    archived = []
    pipeline._archive_item = lambda item, results, alt_threshold, low_conf_threshold: archived.append(
        (item["crop_path"], results, alt_threshold, low_conf_threshold)
    )

    crop_a = tmp_path / "a.jpg"
    crop_b = tmp_path / "b.jpg"
    crop_a.write_bytes(b"a")
    crop_b.write_bytes(b"b")

    items = [
        {"crop_path": str(crop_a)},
        {"crop_path": str(crop_b)},
    ]

    pipeline._recognize_batch(items, ["label-a", "label-b"])

    assert pipeline.recognizer.calls == [([str(crop_a), str(crop_b)], ["label-a", "label-b"], 3)]
    assert len(archived) == 2
    assert all(entry[2:] == (70, 60) for entry in archived)


def test_process_image_keeps_candidate_labels_per_image(tmp_path, monkeypatch):
    class FakeDetector:
        def detect(self, image_path):
            return [([0, 0, 5, 5], 0.9)]

    pipeline = MockPipeline()
    pipeline.existing_hashes = set()
    pipeline.db = SimpleNamespace(check_hash_exists=lambda _: False)
    pipeline._detector = FakeDetector()
    pipeline._detector_loaded = True
    pipeline._detector_lock = threading.Lock()
    pipeline.recognizer = object()
    pipeline.batch_lock = threading.Lock()
    pipeline.output_root = str(tmp_path / "out")
    pipeline.output_root and Path(pipeline.output_root).mkdir(parents=True, exist_ok=True)
    pipeline.config = {
        "processing": {"target_size": 224, "crop_padding": 0, "blur_threshold": 0},
        "recognition": {"top_k": 5, "local": {"inference_batch_size": 16}},
    }

    captured_labels = []
    pipeline._select_candidate_labels = lambda location_tag: [f"candidate:{location_tag}"]
    pipeline._recognize_batch = lambda items, candidate_labels: captured_labels.append(list(candidate_labels))

    def fake_crop(src, box, dest, target_size, padding):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        return True

    monkeypatch.setattr("src.pipeline_runner.ImageProcessor.crop_and_resize", fake_crop)

    image_path_a = tmp_path / "img_a.jpg"
    image_path_b = tmp_path / "img_b.jpg"
    Image.new("RGB", (10, 10), color="white").save(image_path_a)
    Image.new("RGB", (10, 10), color="white").save(image_path_b)

    provider = LocalProvider(str(tmp_path))
    entry_a = SimpleNamespace(path=str(image_path_a), name=image_path_a.name, size=image_path_a.stat().st_size)
    entry_b = SimpleNamespace(path=str(image_path_b), name=image_path_b.name, size=image_path_b.stat().st_size)

    pipeline.process_image(provider, entry_a, {"location_tag": "Beijing", "captured_date": "20260320"})
    pipeline.process_image(provider, entry_b, {"location_tag": "Yunnan", "captured_date": "20260320"})

    assert captured_labels == [["candidate:Beijing"], ["candidate:Yunnan"]]


def test_select_candidate_labels_respects_region_filter_modes():
    pipeline = MockPipeline()
    pipeline.all_labels = ["Passer montanus", "Parus minor", "Corvus macrorhynchos"]
    pipeline.china_allowlist = {"Passer montanus", "Parus minor"}
    pipeline.foreign_countries = {"Japan", "USA"}

    pipeline.config = {"recognition": {"region_filter": "china"}}
    assert pipeline._select_candidate_labels("Beijing") == ["Passer montanus", "Parus minor"]

    pipeline.config = {"recognition": {"region_filter": "auto"}}
    assert pipeline._select_candidate_labels("Beijing") == ["Passer montanus", "Parus minor"]
    assert pipeline._select_candidate_labels("Japan_Tokyo") == pipeline.all_labels

    pipeline.config = {"recognition": {"region_filter": "global"}}
    assert pipeline._select_candidate_labels("Anywhere") == pipeline.all_labels


def test_init_recognizer_selects_backend(monkeypatch):
    pipeline = MockPipeline()
    pipeline.device = "auto"
    pipeline.config = {
        "recognition": {
            "mode": "local",
            "hf_mirror": "https://mirror.example",
            "local": {"model_type": "bioclip-2"},
            "dongniao": {"key": "k1", "url": "https://dongniao.example"},
            "api": {"key": "k2", "url": "https://api.example"},
        }
    }

    created = {}

    class FakeLocal:
        def __init__(self, model_name, device, hf_mirror):
            created["local"] = (model_name, device, hf_mirror)

    class FakeDongniao:
        def __init__(self, api_key, api_url):
            created["dongniao"] = (api_key, api_url)

    class FakeApi:
        def __init__(self, api_url, api_key):
            created["api"] = (api_key, api_url)

    monkeypatch.setattr("src.pipeline_runner.LocalBirdRecognizer", FakeLocal)
    monkeypatch.setattr("src.pipeline_runner.DongniaoRecognizer", FakeDongniao)
    monkeypatch.setattr("src.pipeline_runner.APIBirdRecognizer", FakeApi)

    pipeline._init_recognizer()
    assert created["local"] == ("bioclip-2", "auto", "https://mirror.example")

    pipeline.config["recognition"]["mode"] = "dongniao"
    pipeline._init_recognizer()
    assert created["dongniao"] == ("k1", "https://dongniao.example")

    pipeline.config["recognition"]["mode"] = "api"
    pipeline._init_recognizer()
    assert created["api"] == ("k2", "https://api.example")

    pipeline.config["recognition"]["mode"] = "unknown"
    with pytest.raises(ValueError):
        pipeline._init_recognizer()


def test_run_processes_valid_entries_and_records_scan_history(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    valid_a = source_root / "20260320_Beijing" / "a.jpg"
    valid_b = source_root / "20260321_Beijing" / "b.jpeg"
    skipped_txt = source_root / "20260320_Beijing" / "note.txt"
    output_file = tmp_path / "output" / "ignored.jpg"
    valid_a.parent.mkdir(parents=True, exist_ok=True)
    valid_b.parent.mkdir(parents=True, exist_ok=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")
    skipped_txt.write_text("x", encoding="utf-8")
    output_file.write_bytes(b"y")

    pipeline = MockPipeline()
    pipeline.config = {
        "paths": {
            "sources": [{"path": str(source_root), "recursive": False, "enabled": True}],
        }
    }
    pipeline.source_dir = str(source_root)
    pipeline.output_root = str(output_file.parent)
    pipeline.total_files = 0
    pipeline.processed_count = 0
    emitted = []
    pipeline._progress_callback = lambda processed, total: emitted.append((processed, total))
    pipeline.existing_hashes = set()
    recorded = []
    pipeline.process_image = lambda provider, entry, meta: recorded.append((entry.name, meta["captured_date"], meta["location_tag"]))

    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: set(),
        add_scan_history=lambda record: history.append(record),
    )

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def get_local_path(self, path):
            return path

        def list_dir(self, path, recursive=False):
            return [
                _make_entry(valid_a),
                _make_entry(valid_b),
                _make_entry(skipped_txt),
                _make_entry(output_file),
            ]

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs
            self.structure_pattern = structure_pattern

        def parse(self, entry_path):
            name = Path(entry_path).name
            if name == "a.jpg":
                return {"captured_date": "20260320", "location_tag": "Beijing"}
            return {"captured_date": "20260321", "location_tag": "Beijing"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run(start_date="20260320", end_date="20260320", existing_hashes={"already"})

    assert recorded == [("a.jpg", "20260320", "Beijing")]
    assert pipeline.total_files == 2
    assert emitted[0] == (0, 2)
    assert history[0]["range_start"] == "20260320"
    assert history[0]["range_end"] == "20260320"
    assert history[0]["processed_count"] == 1


def test_run_by_folders_uses_configured_raw_formats(tmp_path, monkeypatch):
    """run_by_folders 应该处理 supported_formats 中配置的 RAW 格式。"""
    source_root = tmp_path / "source"
    target_folder = source_root / "trip"
    target_folder.mkdir(parents=True)
    orf_file = target_folder / "bird.orf"
    jpg_file = target_folder / "bird.jpg"
    txt_file = target_folder / "note.txt"
    orf_file.write_bytes(b"fake orf")
    jpg_file.write_bytes(b"j")
    txt_file.write_text("x", encoding="utf-8")

    pipeline = MockPipeline()
    pipeline.config = {
        "paths": {
            "sources": [{"path": str(source_root), "enabled": True}],
            "supported_formats": [".jpg", ".jpeg", ".orf"],
        }
    }
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = None
    processed = []
    pipeline.process_image = lambda provider, entry, meta: processed.append(entry.name)
    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: {"old"},
        add_scan_history=lambda record: history.append(record),
    )
    pipeline._scan_folder_recursive = lambda provider, folder_path: [
        _make_entry(orf_file), _make_entry(jpg_file), _make_entry(txt_file)
    ]

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def list_dir(self, path, recursive=False):
            return []

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs

        def parse(self, entry_path):
            return {"captured_date": "20260322", "location_tag": "Trip"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run_by_folders([str(target_folder)], recursive=True)

    assert processed == ["bird.orf", "bird.jpg"]
    assert history[0]["processed_count"] == 2


def test_run_by_folders_uses_recursive_scanner_and_records_history(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    target_folder = source_root / "trip"
    target_folder.mkdir(parents=True)
    valid_a = target_folder / "a.jpg"
    valid_b = target_folder / "b.jpeg"
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")

    pipeline = MockPipeline()
    pipeline.config = {
        "paths": {
            "sources": [{"path": str(source_root), "enabled": True}],
        }
    }
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = None
    processed = []
    pipeline.process_image = lambda provider, entry, meta: processed.append((entry.name, meta["captured_date"]))
    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: {"old"},
        add_scan_history=lambda record: history.append(record),
    )
    pipeline._scan_folder_recursive = lambda provider, folder_path: [_make_entry(valid_a), _make_entry(valid_b)]

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def list_dir(self, path, recursive=False):
            return []

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs

        def parse(self, entry_path):
            return {"captured_date": "20260322", "location_tag": "Trip"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run_by_folders([str(target_folder)], recursive=True)

    assert pipeline.existing_hashes == {"old"}
    assert processed == [("a.jpg", "20260322"), ("b.jpeg", "20260322")]
    assert history[0]["range_start"] == f"Folders: {target_folder}"
    assert history[0]["processed_count"] == 2


def test_run_stops_submitting_new_tasks_when_stop_requested(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    valid_a = source_root / "20260320_Beijing" / "a.jpg"
    valid_b = source_root / "20260320_Beijing" / "b.jpg"
    valid_a.parent.mkdir(parents=True, exist_ok=True)
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")

    pipeline = MockPipeline()
    pipeline.config = {"paths": {"sources": [{"path": str(source_root), "recursive": False, "enabled": True}]}}
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = set()

    stop_state = {"requested": False}
    pipeline.set_stop_checker(lambda: stop_state["requested"])

    processed = []

    def process_image(provider, entry, meta):
        processed.append(entry.name)
        stop_state["requested"] = True

    pipeline.process_image = process_image

    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: set(),
        add_scan_history=lambda record: history.append(record),
    )

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def get_local_path(self, path):
            return path

        def list_dir(self, path, recursive=False):
            return [_make_entry(valid_a), _make_entry(valid_b)]

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs
            self.structure_pattern = structure_pattern

        def parse(self, entry_path):
            return {"captured_date": "20260320", "location_tag": "Beijing"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run(existing_hashes=set())

    assert processed == ["a.jpg"]
    assert history[0]["processed_count"] == 1
    assert history[0]["status"] == "Stopped"


def test_run_by_folders_stops_submitting_new_tasks_when_stop_requested(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    target_folder = source_root / "trip"
    target_folder.mkdir(parents=True)
    valid_a = target_folder / "a.jpg"
    valid_b = target_folder / "b.jpg"
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")

    pipeline = MockPipeline()
    pipeline.config = {"paths": {"sources": [{"path": str(source_root), "enabled": True}]}}
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = None

    stop_state = {"requested": False}
    pipeline.set_stop_checker(lambda: stop_state["requested"])

    processed = []

    def process_image(provider, entry, meta):
        processed.append(entry.name)
        stop_state["requested"] = True

    pipeline.process_image = process_image

    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: set(),
        add_scan_history=lambda record: history.append(record),
    )
    pipeline._scan_folder_recursive = lambda provider, folder_path: [_make_entry(valid_a), _make_entry(valid_b)]

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def list_dir(self, path, recursive=False):
            return []

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs

        def parse(self, entry_path):
            return {"captured_date": "20260322", "location_tag": "Trip"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run_by_folders([str(target_folder)], recursive=True)

    assert processed == ["a.jpg"]
    assert history[0]["processed_count"] == 1
    assert history[0]["status"] == "Stopped"


def test_run_accepts_configured_raw_formats(tmp_path, monkeypatch):
    """Pipeline 应该处理 supported_formats 中配置的 RAW 格式。"""
    source_root = tmp_path / "source"
    source_root.mkdir()
    orf_file = source_root / "test.orf"
    jpg_file = source_root / "test.jpg"
    txt_file = source_root / "note.txt"
    orf_file.write_bytes(b"fake orf")
    jpg_file.write_bytes(b"j")
    txt_file.write_text("x", encoding="utf-8")

    pipeline = MockPipeline()
    pipeline.config = {
        "paths": {
            "sources": [{"path": str(source_root), "recursive": False, "enabled": True}],
            "supported_formats": [".jpg", ".jpeg", ".orf"],
        }
    }
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = set()
    recorded = []
    pipeline.process_image = lambda provider, entry, meta: recorded.append(entry.name)
    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: set(),
        add_scan_history=lambda record: history.append(record),
    )

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir
        def exists(self, path): return True
        def get_local_path(self, path): return path
        def list_dir(self, path, recursive=False):
            return [_make_entry(orf_file), _make_entry(jpg_file), _make_entry(txt_file)]

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern): pass
        def parse(self, entry_path): return {"captured_date": "20260320", "location_tag": "Beijing"}

    class ImmediateExecutor:
        def __init__(self, max_workers): self.max_workers = max_workers
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run()

    assert recorded == ["test.orf", "test.jpg"]
    assert pipeline.total_files == 2


def test_process_image_decodes_raw_to_temp_jpg_before_detection(tmp_path, monkeypatch):
    """RAW 文件应该先解码为临时 JPG，再用 YOLO 检测和裁剪。"""
    source_root = tmp_path / "source"
    source_root.mkdir()
    raw_path = source_root / "bird.orf"
    raw_path.write_bytes(b"fake raw")
    decoded_jpg = tmp_path / "bird_decoded.jpg"
    Image.new("RGB", (10, 10), color="white").save(decoded_jpg)

    class FakeDetector:
        def detect(self, image_path):
            detections.append(image_path)
            return [([0, 0, 5, 5], 0.9)]

    pipeline = MockPipeline()
    pipeline.existing_hashes = set()
    pipeline.db = SimpleNamespace(check_hash_exists=lambda _: False)
    pipeline._detector = FakeDetector()
    pipeline._detector_loaded = True
    pipeline._detector_lock = threading.Lock()
    pipeline.recognizer = object()
    pipeline.batch_lock = threading.Lock()
    pipeline.output_root = str(tmp_path / "out")
    Path(pipeline.output_root).mkdir(parents=True, exist_ok=True)
    pipeline.config = {
        "processing": {"target_size": 224, "crop_padding": 0, "blur_threshold": 0},
        "recognition": {"top_k": 5},
    }

    detections = []
    cropped_sources = []
    decode_calls = []

    def fake_decode(raw_path_arg, temp_dir_arg):
        decode_calls.append((raw_path_arg, temp_dir_arg))
        return str(decoded_jpg)

    def fake_crop(src, box, dest, target_size, padding):
        cropped_sources.append(src)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        return True

    fake_image_processor = type("FakeImageProcessor", (), {
        "is_raw": staticmethod(lambda p: Path(p).suffix.lower() == ".orf"),
        "decode_raw_to_temp_jpg": staticmethod(fake_decode),
        "crop_and_resize": staticmethod(fake_crop),
    })

    fake_quality_checker = type("FakeQualityChecker", (), {
        "calculate_blur_score": staticmethod(lambda p: 100.0)
    })

    monkeypatch.setattr("src.pipeline_runner.ImageProcessor", fake_image_processor)
    monkeypatch.setattr("src.pipeline_runner.QualityChecker", fake_quality_checker)

    captured = []
    pipeline._select_candidate_labels = lambda location_tag: ["label"]
    pipeline._recognize_batch = lambda items, labels: captured.append((items, labels))

    provider = LocalProvider(str(source_root))
    entry = SimpleNamespace(path=str(raw_path), name=raw_path.name, size=raw_path.stat().st_size)

    pipeline.process_image(provider, entry, {"location_tag": "Beijing", "captured_date": "20260320"})

    assert len(decode_calls) == 1
    assert Path(decode_calls[0][0]).name == "bird.orf"
    assert len(detections) == 1
    assert Path(detections[0]).name == "bird_decoded.jpg"
    assert len(cropped_sources) == 1
    assert Path(cropped_sources[0]).name == "bird_decoded.jpg"
    assert len(captured) == 1


def test_archive_item_normalizes_processed_extension_to_jpg(tmp_path):
    """处理后的裁剪图应该统一保存为 JPG，无论原始文件是什么格式。"""
    pipeline = MockPipeline()
    pipeline.output_root = str(tmp_path / "out")
    Path(pipeline.output_root).mkdir(parents=True, exist_ok=True)
    pipeline.db = SimpleNamespace(
        get_bird_info=lambda sci: {"chinese_name": "麻雀"},
        add_photo_record=lambda **kwargs: None,
    )
    pipeline.exif_writer = SimpleNamespace(write_metadata=lambda path, meta: None)
    pipeline.path_generator = type("FakePathGenerator", (), {
        "generate_path": staticmethod(lambda meta, filename: str(tmp_path / "out" / filename))
    })()

    crop_path = tmp_path / "out" / "temp_test.ORF_0.jpg"
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), color="white").save(crop_path)

    entry = SimpleNamespace(path="D:/照片/test.ORF", name="test.ORF")
    item = {
        "entry": entry,
        "meta": {"captured_date": "20260320", "location_tag": "Beijing", "source_structure": "."},
        "crop_path": str(crop_path),
        "file_hash": "hash",
        "width": 100,
        "height": 100,
        "detection_index": 0,
        "detections_count": 1,
    }

    pipeline._archive_item(
        item,
        [{"scientific_name": "Passer montanus", "confidence": 0.95}],
        alt_threshold=70,
        low_conf_threshold=60,
    )

    assert (tmp_path / "out" / "test.jpg").exists()
    assert not (tmp_path / "out" / "test.ORF").exists()


def test_archive_item_stores_quality_score_and_details(tmp_path):
    """_archive_item 应将 quality_score 和 quality_details 存入数据库。"""
    pipeline = MockPipeline()
    pipeline.output_root = str(tmp_path / "out")
    Path(pipeline.output_root).mkdir(parents=True, exist_ok=True)
    pipeline.log_level = "info"
    recorded = {}
    pipeline.db = SimpleNamespace(
        get_bird_info=lambda sci: {"chinese_name": "麻雀"},
        add_photo_record=lambda record: recorded.update(record),
    )
    pipeline.exif_writer = SimpleNamespace(write_metadata=lambda path, meta: None)
    pipeline.path_generator = type("FakePathGenerator", (), {
        "generate_path": staticmethod(lambda meta, filename: str(tmp_path / "out" / filename))
    })()

    crop_path = tmp_path / "out" / "temp_test.jpg"
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), color="white").save(crop_path)

    entry = SimpleNamespace(path="D:/照片/test.jpg", name="test.jpg")
    item = {
        "entry": entry,
        "meta": {"captured_date": "20260320", "location_tag": "Beijing", "source_structure": "."},
        "crop_path": str(crop_path),
        "file_hash": "hash",
        "width": 100,
        "height": 100,
        "detection_index": 0,
        "detections_count": 1,
        "quality_score": 73,
        "quality_details": {"clarity": 0.8, "contrast": 0.6},
    }

    pipeline._archive_item(
        item,
        [{"scientific_name": "Passer montanus", "confidence": 0.95}],
        alt_threshold=70,
        low_conf_threshold=60,
    )

    assert recorded.get("quality_score") == 73
    assert recorded.get("quality_details") == {"clarity": 0.8, "contrast": 0.6}
