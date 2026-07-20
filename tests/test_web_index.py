from pathlib import Path
from unittest.mock import ANY

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.web import app as web_app


def _create_temp_db(tmp_path: Path) -> str:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return str(db_path)


class TemplateRecorder:
    def __init__(self):
        self.calls = []

    def TemplateResponse(self, template_name=None, context=None, *, name=None, **kwargs):
        if name is not None:
            template_name = name
        if context is None:
            context = {}
        payload = {"template": template_name, "context": context}
        self.calls.append(payload)
        return payload


def test_admin_index_page_renders_template(monkeypatch):
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.admin_index_page(request=object())

    assert result == {
        "template": "admin_index.html",
        "context": {"request": ANY},
    }


def test_api_index_counts_indexed_and_skipped(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(
        web_app,
        "config",
        {"paths": {"supported_formats": [".jpg", ".jpeg"]}},
    )

    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (100, 100), color="red").save(folder / "a.jpg")
    Image.new("RGB", (100, 100), color="green").save(folder / "b.jpg")

    result = web_app.index_photos(
        web_app.IndexRequest(folder=str(folder), recursive=True)
    )

    assert result == {"indexed": 2, "skipped": 0, "errors": 0}


def test_api_index_skips_duplicate_photos(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    monkeypatch.setattr(
        web_app,
        "config",
        {"paths": {"supported_formats": [".jpg"]}},
    )

    folder = tmp_path / "photos"
    folder.mkdir()
    Image.new("RGB", (100, 100), color="blue").save(folder / "bird.jpg")

    first = web_app.index_photos(web_app.IndexRequest(folder=str(folder)))
    second = web_app.index_photos(web_app.IndexRequest(folder=str(folder)))

    assert first == {"indexed": 1, "skipped": 0, "errors": 0}
    assert second == {"indexed": 0, "skipped": 1, "errors": 0}


def test_api_index_rejects_missing_folder(monkeypatch):
    monkeypatch.setattr(web_app, "config", {"paths": {"supported_formats": [".jpg"]}})

    with pytest.raises(web_app.HTTPException) as exc_info:
        web_app.index_photos(
            web_app.IndexRequest(folder="/non/existent/path", recursive=True)
        )

    assert exc_info.value.status_code == 400
    assert "does not exist" in exc_info.value.detail
