from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch
from urllib.parse import parse_qs

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo, PhotoGroup, Species, Outing
from src.web import app as web_app
from fastapi import HTTPException


def _mock_metadata_writer(monkeypatch):
    def fake_write_metadata_for_photo(photo, writer, write_mode):
        return True

    monkeypatch.setattr(web_app, "write_metadata_for_photo", fake_write_metadata_for_photo)


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

    assert result == {
        "template": "select.html",
        "context": {
            "request": ANY, "groups": [], "current_date": "",
            "current_rating": "", "current_outing": None, "outing_id": 0,
        },
    }


def test_select_page_filters_by_rating(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="five.jpg", filename="five.jpg", captured_date="2026-07-20", primary_bird_cn="麻雀", quality_score=85))
    session.add(Photo(file_path="four.jpg", filename="four.jpg", captured_date="2026-07-20", primary_bird_cn="麻雀", quality_score=65))
    session.add(Photo(file_path="three.jpg", filename="three.jpg", captured_date="2026-07-20", primary_bird_cn="麻雀", quality_score=30))
    session.add(Photo(file_path="one.jpg", filename="one.jpg", captured_date="2026-07-20", primary_bird_cn="麻雀", quality_score=90, rating=-1))
    session.add(Photo(file_path="zero.jpg", filename="zero.jpg", captured_date="2026-07-20", primary_bird_cn="", quality_score=70))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.select_page(request=object(), date="", rating="5")
    assert len(templates.calls[-1]["context"]["groups"]) == 1
    assert templates.calls[-1]["context"]["groups"][0]["photos"][0]["id"] == 1
    assert templates.calls[-1]["context"]["current_rating"] == "5"

    web_app.select_page(request=object(), date="", rating="4")
    assert len(templates.calls[-1]["context"]["groups"]) == 1
    assert templates.calls[-1]["context"]["groups"][0]["photos"][0]["id"] == 2

    web_app.select_page(request=object(), date="", rating="3")
    assert len(templates.calls[-1]["context"]["groups"]) == 1
    assert templates.calls[-1]["context"]["groups"][0]["photos"][0]["id"] == 3

    web_app.select_page(request=object(), date="", rating="1")
    assert len(templates.calls[-1]["context"]["groups"]) == 1
    assert templates.calls[-1]["context"]["groups"][0]["photos"][0]["id"] == 4

    web_app.select_page(request=object(), date="", rating="0")
    assert len(templates.calls[-1]["context"]["groups"]) == 1
    assert templates.calls[-1]["context"]["groups"][0]["photos"][0]["id"] == 5


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


def test_select_auto_pick_picks_best_per_group_and_high_quality_ungrouped(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    g1 = PhotoGroup(outing_id=1, best_photo_id=0)
    session.add(g1)
    session.flush()

    session.add(Photo(file_path="g1_low.jpg", filename="g1_low.jpg", group_id=g1.id, quality_score=60, outing_id=1))
    session.add(Photo(file_path="g1_high.jpg", filename="g1_high.jpg", group_id=g1.id, quality_score=85, outing_id=1))
    session.add(Photo(file_path="solo.jpg", filename="solo.jpg", quality_score=82, outing_id=1))
    session.add(Photo(file_path="weak.jpg", filename="weak.jpg", quality_score=40, outing_id=1))
    session.commit()

    result = web_app.select_auto_pick(web_app.AutoPickRequest(outing_id=1, min_quality=80))
    assert result["status"] == "success"
    assert result["selected_count"] == 2

    selected_paths = set()
    session, _ = _create_session(db_path)
    for p in session.query(Photo).filter(Photo.is_selected == True).all():
        selected_paths.add(p.file_path)
    session.close()
    assert selected_paths == {"g1_high.jpg", "solo.jpg"}

def test_gallery_page_renders_template(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="",
        date="",
        date_from="",
        date_to="",
        species=[""],
        families=[""],
        locations=[""],
        outing_id=0,
        limit=50,
        offset=0,
    )

    assert result == {
        "template": "gallery.html",
        "context": {
            "request": ANY,
            "photos": [],
            "query": "",
            "current_view": "",
            "current_date": "",
            "date_from": "",
            "date_to": "",
            "selected_species": [],
            "selected_families": [],
            "selected_locations": [],
            "selected_level1": [],
            "selected_level2": [],
            "selected_level3": [],
            "limit": 50,
            "offset": 0,
            "total_count": 0,
            "available_dates": [],
            "available_species": [],
            "available_families": [],
            "available_locations": [],
            "available_level1": [],
            "available_level2": [],
            "available_level3": [],
            "base_query": "",
            "has_next": False,
            "has_prev": False,
            "next_offset": 50,
            "prev_offset": 0,
            "outing_id": 0,
            "current_outing": None,
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

    web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="selected",
        date="",
        date_from="",
        date_to="",
        species="",
        families="",
        locations="",
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[0]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["is_selected"] is True


def test_gallery_page_filters_date_range(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", captured_date="2026-07-20"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", captured_date="2026-07-25"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="",
        date="",
        date_from="2026-07-18",
        date_to="2026-07-22",
        species="",
        families="",
        locations="",
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[0]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["captured_date"] == "2026-07-20"


def test_gallery_page_filters_species_and_family(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Species(scientific_name="Passer montanus", chinese_name="麻雀", family_cn="雀科", photo_count=1))
    session.add(Species(scientific_name="Turdus merula", chinese_name="乌鸫", family_cn="鸫科", photo_count=1))
    session.add(Photo(file_path="a.jpg", filename="a.jpg", primary_bird_cn="麻雀", scientific_name="Passer montanus"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", primary_bird_cn="乌鸫", scientific_name="Turdus merula"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="",
        date="",
        date_from="",
        date_to="",
        species=["麻雀"],
        families=[""],
        locations=[""],
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[0]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["primary_bird_cn"] == "麻雀"

    web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="",
        date="",
        date_from="",
        date_to="",
        species=[""],
        families=["鸫科"],
        locations=[""],
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[-1]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["primary_bird_cn"] == "乌鸫"


def test_gallery_page_filters_locations_and_unselected_view(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", location_tag="福州-森林公园", is_selected=True))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", location_tag="厦门-鼓浪屿", is_selected=False))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="",
        date="",
        date_from="",
        date_to="",
        species=[""],
        families=[""],
        locations=["福州-森林公园"],
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[0]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["location_tag"] == "福州-森林公园"

    web_app.gallery_page(
        request=object(),
        q="",
        view="unselected",
        filter="",
        date="",
        date_from="",
        date_to="",
        species=[""],
        families=[""],
        locations=[""],
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[-1]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["is_selected"] is False


def test_gallery_page_search_includes_filename(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="sparrow.jpg", filename="sparrow.jpg", primary_bird_cn="麻雀"))
    session.add(Photo(file_path="thrush.jpg", filename="thrush.jpg", primary_bird_cn="乌鸫"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(
        request=object(),
        q="sparrow",
        view="",
        filter="",
        date="",
        date_from="",
        date_to="",
        species="",
        families="",
        locations="",
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[0]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["filename"] == "sparrow.jpg"


def test_gallery_page_pagination_preserves_filters(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(
        request=object(),
        q="",
        view="selected",
        filter="",
        date="",
        date_from="2026-07-01",
        date_to="2026-07-31",
        species=["麻雀"],
        families=[""],
        locations=["福州"],
        outing_id=0,
        limit=20,
        offset=40,
    )
    context = templates.calls[0]["context"]
    parsed = parse_qs(context["base_query"])
    assert parsed.get("date_from") == ["2026-07-01"]
    assert parsed.get("date_to") == ["2026-07-31"]
    assert parsed.get("species") == ["麻雀"]
    assert parsed.get("locations") == ["福州"]
    assert parsed.get("limit") == ["20"]
    assert context["next_offset"] == 60
    assert context["prev_offset"] == 20


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
            "current_outing": None,
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


def test_guide_page_highlights_new_species(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    from datetime import datetime, timedelta
    old_outing = Outing(name="旧外拍", start_date="20260720", created_at=datetime.utcnow() - timedelta(days=1))
    new_outing = Outing(name="新外拍", start_date="20260721", created_at=datetime.utcnow())
    session.add(old_outing)
    session.add(new_outing)
    session.commit()

    session.add(Species(scientific_name="Passer domesticus", chinese_name="家麻雀", family_cn="雀科", family_sci="Passeridae", photo_count=2))
    session.add(Species(scientific_name="Cyanocitta cristata", chinese_name="冠蓝鸦", family_cn="鸦科", family_sci="Corvidae", photo_count=1))
    session.add(Photo(file_path="a.jpg", filename="a.jpg", scientific_name="Passer domesticus", outing_id=old_outing.id, captured_date="2026-07-20"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", scientific_name="Cyanocitta cristata", outing_id=new_outing.id, captured_date="2026-07-21"))
    session.add(Photo(file_path="c.jpg", filename="c.jpg", scientific_name="Passer domesticus", outing_id=new_outing.id, captured_date="2026-07-21"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.guide_page(request=object(), q="")
    context = templates.calls[0]["context"]
    families = {f["family_cn"]: f["species"] for f in context["families"]}
    # 家麻雀在旧外拍已有，不是新增
    sparrow = next(s for s in families["雀科"] if s["scientific_name"] == "Passer domesticus")
    assert sparrow["is_new"] is False
    # 冠蓝鸦只在最新外拍出现，应标记为新增
    jay = next(s for s in families["鸦科"] if s["scientific_name"] == "Cyanocitta cristata")
    assert jay["is_new"] is True


def test_guide_species_history_api(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    outing = Outing(name="测试外拍", start_date="20260722")
    session.add(outing)
    session.commit()
    session.add(Species(scientific_name="Passer domesticus", chinese_name="家麻雀", family_cn="雀科", family_sci="Passeridae", photo_count=2))
    session.add(Photo(
        file_path="a.jpg", filename="a.jpg", scientific_name="Passer domesticus",
        outing_id=outing.id, captured_date="2026-07-22", location_tag="北京_玉渊潭",
        location_level1="北京", location_level2="海淀区", location_level3="玉渊潭公园",
        latitude=39.91, longitude=116.30, quality_score=85,
    ))
    session.commit()
    session.close()

    result = web_app.guide_species_history(scientific_name="Passer domesticus")
    assert result["status"] == "success"
    assert result["species"]["chinese_name"] == "家麻雀"
    assert len(result["timeline"]) == 1
    assert result["timeline"][0]["outing_name"] == "测试外拍"
    assert result["timeline"][0]["photo_count"] == 1
    assert len(result["locations"]) == 1
    assert result["locations"][0]["latitude"] == 39.91
    assert result["locations"][0]["longitude"] == 116.30
    assert result["locations"][0]["location_level1"] == "北京"


def test_guide_species_history_api_not_found(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))

    with pytest.raises(HTTPException) as exc:
        web_app.guide_species_history(scientific_name="Unknown sp.")
    assert exc.value.status_code == 404


def test_guide_http_route_renders_content(tmp_path, monkeypatch):
    """回归测试：确保 /guide 路由没有被空的同名函数覆盖，能够正常渲染页面。"""
    db_path = _create_temp_db(tmp_path)
    session, engine = _create_session(db_path)
    session.add(Species(
        scientific_name="Passer domesticus",
        chinese_name="家麻雀",
        family_cn="雀科",
        family_sci="Passeridae",
        photo_count=1,
    ))
    session.add(Photo(
        file_path="a.jpg",
        filename="a.jpg",
        scientific_name="Passer domesticus",
        quality_score=80,
        captured_date="2026-07-20",
    ))
    session.commit()
    session.close()

    SessionLocal = sessionmaker(bind=engine)

    def _get_session():
        return SessionLocal()

    monkeypatch.setattr(web_app, "get_sqlalchemy_session", _get_session)

    with TestClient(web_app.app) as client:
        response = client.get("/guide")

    assert response.status_code == 200
    body = response.text
    assert "家麻雀" in body
    assert "雀科" in body


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


def test_gallery_page_filters_cascade_locations(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    session.add(Photo(file_path="a.jpg", filename="a.jpg", location_level1="福建", location_level2="福州", location_level3="森林公园"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", location_level1="福建", location_level2="厦门", location_level3="鼓浪屿"))
    session.add(Photo(file_path="c.jpg", filename="c.jpg", location_level1="北京", location_level2="海淀区", location_level3="玉渊潭公园"))
    session.commit()
    session.close()

    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="",
        date="",
        date_from="",
        date_to="",
        species=[""],
        families=[""],
        locations=[""],
        location_level1=["福建"],
        location_level2=[""],
        location_level3=[""],
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[0]["context"]
    assert len(context["photos"]) == 2

    web_app.gallery_page(
        request=object(),
        q="",
        view="",
        filter="",
        date="",
        date_from="",
        date_to="",
        species=[""],
        families=[""],
        locations=[""],
        location_level1=["福建"],
        location_level2=["福州"],
        location_level3=[""],
        outing_id=0,
        limit=50,
        offset=0,
    )
    context = templates.calls[-1]["context"]
    assert len(context["photos"]) == 1
    assert context["photos"][0]["location_level3"] == "森林公园"


def test_select_progress_endpoint_empty_db(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))

    result = web_app.select_progress(outing_id=0, date="")

    assert result == {"status": "success", "total": 0, "processed": 0, "unprocessed": 0, "percent": 0}


def test_select_progress_counts_processed_states(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    # 选中 + 已确认 → 已处理
    session.add(Photo(file_path="a.jpg", filename="a.jpg", is_selected=True, primary_bird_cn="麻雀", scientific_name="Passer montanus"))
    # 选中 + 待确认 → 未处理
    session.add(Photo(file_path="b.jpg", filename="b.jpg", is_selected=True, primary_bird_cn="待确认鸟种"))
    # 选中 + Uncertain 学名 → 未处理
    session.add(Photo(file_path="c.jpg", filename="c.jpg", is_selected=True, primary_bird_cn="麻雀", scientific_name="Uncertain"))
    # 淘汰 → 已处理
    session.add(Photo(file_path="d.jpg", filename="d.jpg", rating=-1, primary_bird_cn="待确认鸟种"))
    # 未动 → 未处理
    session.add(Photo(file_path="e.jpg", filename="e.jpg", primary_bird_cn="麻雀", scientific_name="Passer montanus"))
    # 选中 + 无鸟（NULL）→ 已处理
    session.add(Photo(file_path="f.jpg", filename="f.jpg", is_selected=True))
    session.commit()
    session.close()

    result = web_app.select_progress(outing_id=0, date="")

    assert result["total"] == 6
    assert result["processed"] == 3
    assert result["unprocessed"] == 3
    assert result["percent"] == 50


def test_select_progress_filters_outing_and_date(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(web_app, "db_path", Path(db_path))
    session, _ = _create_session(db_path)
    o1 = Outing(name="外拍1", start_date="20260720")
    o2 = Outing(name="外拍2", start_date="20260721")
    session.add_all([o1, o2])
    session.flush()
    session.add(Photo(file_path="a.jpg", filename="a.jpg", outing_id=o1.id, captured_date="2026-07-20", is_selected=True, primary_bird_cn="麻雀"))
    session.add(Photo(file_path="b.jpg", filename="b.jpg", outing_id=o1.id, captured_date="2026-07-21", rating=-1))
    session.add(Photo(file_path="c.jpg", filename="c.jpg", outing_id=o2.id, captured_date="2026-07-21", rating=-1))
    session.commit()
    o1_id, o2_id = o1.id, o2.id
    session.close()

    # outing_id 过滤
    result = web_app.select_progress(outing_id=o1_id, date="")
    assert result["total"] == 2 and result["processed"] == 2
    # outing_id + date 过滤
    result = web_app.select_progress(outing_id=o1_id, date="2026-07-21")
    assert result["total"] == 1 and result["processed"] == 1
    # 指定外拍优先于"最近一次外拍"回退
    result = web_app.select_progress(outing_id=o2_id, date="")
    assert result["total"] == 1
