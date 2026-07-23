from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch
from urllib.parse import parse_qs

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo, PhotoGroup, Species, Outing
from src.web import app as web_app
from fastapi import HTTPException


class TemplateRecorder:
    def __init__(self):
        self.calls = []

    def TemplateResponse(self, request, *args, **kwargs):
        template_name = args[0] if args else kwargs.get("name")
        context = args[1] if len(args) > 1 else kwargs.get("context", {})
        payload = {"template": template_name, "context": context}
        self.calls.append(payload)
        return payload


def _create_temp_db(tmp_path: Path) -> str:
    db_path = tmp_path / "test_log.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return str(db_path)


def _create_session(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _create_test_data(db_path: str):
    session, _ = _create_session(db_path)

    outing1 = Outing(name="测试外拍一", start_date="20260720", end_date="20260720", location_tag="植物园")
    outing2 = Outing(name="测试外拍二", start_date="20260722", end_date="20260722", location_tag="湿地公园")
    session.add_all([outing1, outing2])
    session.flush()

    session.add(Photo(
        file_path="a.jpg", filename="a.jpg", original_path="a.jpg",
        captured_date="20260720", primary_bird_cn="麻雀", scientific_name="Passer montanus",
        outing_id=outing1.id, quality_score=75,
    ))
    session.add(Photo(
        file_path="b.jpg", filename="b.jpg", original_path="b.jpg",
        captured_date="20260720", primary_bird_cn="喜鹊", scientific_name="Pica pica",
        outing_id=outing1.id, quality_score=85,
    ))
    session.add(Photo(
        file_path="c.jpg", filename="c.jpg", original_path="c.jpg",
        captured_date="20260722", primary_bird_cn="麻雀", scientific_name="Passer montanus",
        outing_id=outing2.id, quality_score=60,
    ))
    session.add(Photo(
        file_path="d.jpg", filename="d.jpg", original_path="d.jpg",
        captured_date="20260722", primary_bird_cn="白鹭", scientific_name="Egretta garzetta",
        outing_id=outing2.id, quality_score=90,
    ))
    session.commit()
    session.close()


def test_log_page_renders_template(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.birding_log_page(request=object())

    assert result == {
        "template": "log.html",
        "context": {"request": ANY},
    }


def test_api_log_aggregates_outings_and_species(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    _create_test_data(db_path)

    result = web_app.api_birding_log()

    assert result["status"] == "success"
    assert result["summary"] == {"total_outings": 2, "total_species": 3, "total_photos": 4}

    records = result["records"]
    assert len(records) == 2

    # Most recent outing first
    recent = records[0]
    assert recent["outing_name"] == "测试外拍二"
    assert recent["start_date"] == "20260722"
    assert recent["location"] == "湿地公园"
    assert recent["photo_count"] == 2
    assert recent["species_count"] == 2
    # 白鹭 is new in outing2; 麻雀 was already seen in outing1
    assert recent["new_species_count"] == 1
    species_names = {s["cn"] for s in recent["species"]}
    assert species_names == {"麻雀", "白鹭"}

    older = records[1]
    assert older["outing_name"] == "测试外拍一"
    assert older["new_species_count"] == 2
    assert older["species_count"] == 2


def test_api_log_filters_by_year(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    _create_test_data(db_path)

    result = web_app.api_birding_log(year=2026)
    assert result["summary"]["total_outings"] == 2

    result = web_app.api_birding_log(year=2025)
    assert result["summary"]["total_outings"] == 0


def test_api_log_years_returns_unique_years(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    _create_test_data(db_path)

    result = web_app.api_birding_log_years()
    assert result["status"] == "success"
    assert result["years"] == ["2026"]


def test_api_log_empty_database(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))

    result = web_app.api_birding_log()
    assert result["status"] == "success"
    assert result["records"] == []
    assert result["summary"] == {"total_outings": 0, "total_species": 0, "total_photos": 0}
