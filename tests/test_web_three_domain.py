from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo, Species
from src.web import app as web_app


def _mock_metadata_writer(monkeypatch):
    def fake_write_metadata_for_photo(photo, writer, write_mode):
        return True

    monkeypatch.setattr(web_app, "write_metadata_for_photo", fake_write_metadata_for_photo)


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


def _create_temp_db(tmp_path: Path) -> str:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return str(db_path)


def _create_session(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    return Session(), engine


def test_select_page_renders_template(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.select_page(request=object(), date="")

    assert result == {"template": "select.html", "context": {"request": ANY, "groups": [], "current_date": ""}}


def test_select_page_groups_photos_by_date(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", captured_date="2026-07-20", quality_score=75))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", captured_date="2026-07-20", quality_score=85))
    session.add(Photo(file_path="c.jpg", filename="c.jpg", captured_date="2026-07-21", quality_score=60))
    session.commit()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.select_page(request=object(), date="")

    context = templates.calls[0]["context"]
    assert len(context["groups"]) == 2
    assert context["groups"][0]["date"] == "2026-07-21"
    assert len(context["groups"][0]["photos"]) == 1
    assert context["groups"][1]["date"] == "2026-07-20"
    assert len(context["groups"][1]["photos"]) == 2

    session.close()


def test_select_mark_api_updates_status(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg"))
    session.commit()
    photo_id = session.query(Photo).first().id
    session.close()

    result = web_app.select_mark(web_app.SelectMarkRequest(photo_id=photo_id, action="select"))
    assert result["status"] == "success"

    session, _ = _create_session(db_path)
    photo = session.query(Photo).filter(Photo.id == photo_id).first()
    assert photo.is_selected is True
    session.close()


def test_gallery_page_renders_template(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.gallery_page(request=object(), q="", filter="", date="", limit=50, offset=0)

    assert result == {
        "template": "gallery.html",
        "context": {
            "request": ANY,
            "photos": [],
            "query": "",
            "current_filter": "",
            "current_date": "",
            "limit": 50,
            "offset": 0,
            "total_count": 0,
            "available_dates": [],
            "has_next": False,
            "has_prev": False,
            "next_offset": 50,
            "prev_offset": 0,
        },
    }


def test_gallery_page_filters_selected(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", is_selected=True, captured_date="2026-07-20"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", is_selected=False, captured_date="2026-07-20"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(request=object(), q="", filter="selected", date="", limit=50, offset=0)
    context = templates.calls[0]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["is_selected"] is True


def test_guide_page_renders_template(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.guide_page(request=object(), q="")

    assert result == {
        "template": "guide.html",
        "context": {
            "request": ANY,
            "families": [],
            "total_species": 0,
            "total_families": 0,
            "query": "",
        },
    }


def test_guide_page_groups_species_by_family(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Species(scientific_name="Passer domesticus", chinese_name="家麻雀", family_cn="雀科", family_sci="Passeridae", photo_count=2))
    session.add(Species(scientific_name="Passer montanus", chinese_name="树麻雀", family_cn="雀科", family_sci="Passeridae", photo_count=1))
    session.add(Species(scientific_name="Cyanocitta cristata", chinese_name="冠蓝鸦", family_cn="鸦科", family_sci="Corvidae", photo_count=1))
    session.add(Photo(file_path="a.jpg", filename="a.jpg", scientific_name="Passer domesticus", quality_score=80, captured_date="2026-07-20"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.guide_page(request=object(), q="")
    context = templates.calls[0]["context"]
    assert context["total_species"] == 3
    assert context["total_families"] == 2
    families = context["families"]
    assert len(families) == 2
    # sorted by family_cn
    assert families[0]["family_cn"] == "雀科"
    assert len(families[0]["species"]) == 2
    assert families[1]["family_cn"] == "鸦科"


def test_write_photo_metadata_api(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(
        file_path="a.jpg",
        filename="a.jpg",
        original_path="a.jpg",
        primary_bird_cn="麻雀",
        scientific_name="Passer montanus",
        quality_score=85,
        is_selected=True,
    ))
    session.commit()
    photo_id = session.query(Photo).first().id
    session.close()

    _mock_metadata_writer(monkeypatch)

    result = web_app.write_photo_metadata(photo_id=photo_id)
    assert result["status"] == "success"
    assert result["photo_id"] == photo_id


def test_write_gallery_metadata_api(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", original_path="a.jpg", is_selected=True, quality_score=90))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", original_path="b.jpg", is_selected=False, quality_score=60))
    session.add(Photo(file_path="c.jpg", filename="c.jpg", original_path="c.jpg", is_selected=True, quality_score=75))
    session.commit()
    session.close()

    _mock_metadata_writer(monkeypatch)

    result = web_app.write_gallery_metadata(filter="selected")
    assert result["status"] == "success"
    assert result["total"] == 2
    assert result["success_count"] == 2
