from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from fastapi import HTTPException

from src.web import import_service


class FakeTaskManager:
    def __init__(self):
        self.is_running = False
        self.logs = []
        self.started_args = None

    def start_import(self, folder_path, recursive=True, run_recognition=True, overwrite=False, config=None, location_info=None, outing_id=None):
        if self.is_running:
            return False
        self.is_running = True
        self.started_args = {
            "folder_path": folder_path,
            "recursive": recursive,
            "run_recognition": run_recognition,
            "overwrite": overwrite,
            "config": config,
            "location_info": location_info,
            "outing_id": outing_id,
        }
        return True


@pytest.fixture
def service(tmp_path):
    config = {"paths": {"supported_formats": [".jpg", ".jpeg", ".orf"], "db_path": str(tmp_path / "birder.db")}}
    return import_service.ImportService(FakeTaskManager(), config)


def test_scan_folder_counts_supported_files(service, tmp_path):
    # Create files
    (tmp_path / "a.jpg").write_bytes(b"1")
    (tmp_path / "b.jpg").write_bytes(b"22")
    (tmp_path / "c.orf").write_bytes(b"333")
    (tmp_path / "skip.txt").write_bytes(b"skip")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.jpg").write_bytes(b"4444")

    result = service.scan_folder(str(tmp_path), recursive=True)
    assert result["total_files"] == 4
    assert result["jpeg_files"] == 3
    assert result["raw_files"] == 1
    assert result["total_size_mb"] >= 0
    assert set(result["extensions"]) == {".jpg", ".orf"}


def test_scan_folder_non_recursive_only_top_level(service, tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"1")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.jpg").write_bytes(b"2")

    result = service.scan_folder(str(tmp_path), recursive=False)
    assert result["total_files"] == 1
    assert "b.jpg" not in result["sample_files"]


def test_scan_folder_rejects_missing_directory(service):
    with pytest.raises(ValueError):
        service.scan_folder("/nonexistent/path/xyz")


def test_start_import_returns_success_when_idle(service, tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    result = service.start_import(str(tmp_path), recursive=True, run_recognition=True)
    assert result["status"] == "success"
    assert result["outing_id"] is not None
    assert isinstance(result["outing_id"], int)
    assert service.task_manager.is_running is True
    assert service.task_manager.started_args["folder_path"] == str(tmp_path)
    assert service.task_manager.started_args["run_recognition"] is True
    assert service.task_manager.started_args["outing_id"] == result["outing_id"]


def test_start_import_returns_error_when_busy(service, tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    service.task_manager.is_running = True
    result = service.start_import(str(tmp_path), recursive=True, run_recognition=True)
    assert result["status"] == "error"
    assert "already running" in result["message"].lower()


def test_start_import_returns_error_for_missing_folder(service):
    result = service.start_import("/nonexistent/path/xyz")
    assert result["status"] == "error"


def test_get_status(service):
    service.task_manager.is_running = True
    service.task_manager.logs = ["log1", "log2"]
    status = service.get_status()
    assert status["is_running"] is True
    assert status["logs"] == ["log1", "log2"]


def test_scan_folder_returns_location_info(service, tmp_path):
    location_dir = tmp_path / "20260102_北京_玉渊潭公园"
    location_dir.mkdir()
    (location_dir / "a.jpg").write_bytes(b"1")

    result = service.scan_folder(str(location_dir.parent), recursive=True)
    assert result["location"]["tag"] == "北京_玉渊潭公园"
    assert result["location"]["level1"] == "北京"
    assert result["location"]["level2"] == "玉渊潭公园"
    assert result["location"]["level3"] is None


def test_parse_location_from_folder_path(service):
    location = service.parse_location("D:/Photos/20260102_北京_玉渊潭公园")
    assert location["tag"] == "北京_玉渊潭公园"
    assert location["level1"] == "北京"
    assert location["level2"] == "玉渊潭公园"
    assert location["level3"] is None


def test_start_import_passes_location_info(service, tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    location_info = {"location_tag": "福建_福州_森林公园", "location_level1": "福建", "location_level2": "福州", "location_level3": "森林公园"}
    result = service.start_import(str(tmp_path), recursive=True, run_recognition=True, location_info=location_info)
    assert result["status"] == "success"
    assert service.task_manager.started_args["location_info"] == location_info


