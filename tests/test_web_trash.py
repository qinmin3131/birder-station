from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo
from src.web import app as web_app


class FakeTrashService:
    last_init = None
    list_result = {"count": 2, "total_bytes": 1234, "sample_filenames": ["a.jpg", "b.jpg"]}
    empty_result = {"moved": 2, "deleted": 2, "skipped": 0, "errors": []}

    def __init__(self, session, source_dirs, processed_dir=None, **kwargs):
        FakeTrashService.last_init = {"source_dirs": source_dirs, "processed_dir": processed_dir}

    def list_rejected(self, outing_id: int = 0):
        self.last_outing_id = outing_id
        return FakeTrashService.list_result

    def empty(self, outing_id: int = 0):
        self.last_outing_id = outing_id
        return FakeTrashService.empty_result


def _create_temp_db(tmp_path: Path) -> str:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return str(db_path)


def test_trash_preview_endpoint(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(web_app, "TrashService", FakeTrashService)

    result = web_app.trash_preview(outing_id=7)

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["sample_filenames"] == ["a.jpg", "b.jpg"]


def test_trash_empty_endpoint(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(web_app, "TrashService", FakeTrashService)

    result = web_app.trash_empty(web_app.EmptyTrashRequest(outing_id=3))

    assert result["status"] == "success"
    assert result["moved"] == 2
    assert result["errors"] == []


def test_select_and_gallery_pages_have_trash_button(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    session_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(session_engine)
    SessionLocal = sessionmaker(bind=session_engine)
    monkeypatch.setattr(web_app, "get_sqlalchemy_session", lambda: SessionLocal())

    with TestClient(web_app.app) as client:
        select_resp = client.get("/select")
        gallery_resp = client.get("/gallery")

    assert select_resp.status_code == 200
    assert "清空淘汰" in select_resp.text
    assert gallery_resp.status_code == 200
    assert "清空淘汰" in gallery_resp.text
