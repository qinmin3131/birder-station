from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo, init_database
from src.metadata.exif_writer import build_exif_tags_from_photo
from src.web import app as web_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_tags.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr(web_app, "db_path", db_path)
    monkeypatch.setattr(web_app, "config", {"paths": {"source_dir": str(tmp_path)}})
    monkeypatch.setattr(web_app, "get_sqlalchemy_session", lambda: SessionLocal())

    with TestClient(web_app.app) as c:
        yield c


def _create_photo(session, **kwargs):
    defaults = {
        "file_path": "bird.jpg",
        "filename": "bird.jpg",
        "captured_date": "2026-07-20",
        "primary_bird_cn": None,
        "scientific_name": None,
        "is_selected": False,
        "rating": 0,
    }
    defaults.update(kwargs)
    photo = Photo(**defaults)
    session.add(photo)
    session.commit()
    session.refresh(photo)
    return photo


def test_photo_model_has_tags_and_note_columns(tmp_path):
    db_path = tmp_path / "m.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("photos")}
    assert "tags" in cols
    assert "note" in cols


def test_init_database_migrates_existing_photos_table(tmp_path):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE photos (id INTEGER PRIMARY KEY, file_path TEXT NOT NULL, filename TEXT NOT NULL)"
        ))
    init_database(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("photos")}
    assert "tags" in cols
    assert "note" in cols


def test_save_and_get_tags(client):
    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(session)
    photo_id = photo.id
    session.close()

    resp = client.post(f"/api/photo/{photo_id}/tags", json={"tags": ["风景", "昆虫"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["tags"] == ["风景", "昆虫"]

    session = web_app.get_sqlalchemy_session()
    saved = session.query(Photo).filter(Photo.id == photo_id).first()
    assert saved.tags == ["风景", "昆虫"]
    session.close()


def test_tags_endpoint_dedupes_and_strips(client):
    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(session)
    photo_id = photo.id
    session.close()

    resp = client.post(
        f"/api/photo/{photo_id}/tags",
        json={"tags": [" 风景 ", "风景", "", "昆虫"]},
    )
    assert resp.json()["tags"] == ["风景", "昆虫"]


def test_list_all_tags(client):
    session = web_app.get_sqlalchemy_session()
    _create_photo(session, filename="a.jpg", tags=["风景", "昆虫"])
    _create_photo(session, filename="b.jpg", tags=["风景", "兽类"])
    session.close()

    resp = client.get("/api/tags")
    assert resp.status_code == 200
    assert set(resp.json()["tags"]) == {"风景", "昆虫", "兽类"}


def test_save_and_get_note(client):
    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(session)
    photo_id = photo.id
    session.close()

    resp = client.post(f"/api/photo/{photo_id}/note", json={"note": "河边拍的日落"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    session = web_app.get_sqlalchemy_session()
    saved = session.query(Photo).filter(Photo.id == photo_id).first()
    assert saved.note == "河边拍的日落"
    session.close()


def test_review_returns_tags_and_note(client, tmp_path):
    from PIL import Image
    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (800, 600), color="green").save(img_path)

    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(
        session,
        original_path=str(img_path),
        quality_score=72,
        quality_details={"clarity": 0.6, "contrast": 0.5, "exposure": 0.7, "subject_size": 0.8, "iso": 0.85},
        tags=["风景"],
        note="备注内容",
    )
    photo_id = photo.id
    session.close()

    data = client.get(f"/api/photo/{photo_id}/review").json()
    assert data["photo"]["tags"] == ["风景"]
    assert data["photo"]["note"] == "备注内容"


def test_tagged_photo_counts_as_processed(client):
    session = web_app.get_sqlalchemy_session()
    _create_photo(session, filename="a.jpg", tags=["风景"])
    _create_photo(session, filename="b.jpg")
    session.close()

    data = client.get("/api/select/progress").json()
    assert data["total"] == 2
    assert data["processed"] == 1
    assert data["unprocessed"] == 1


def test_build_exif_tags_merges_user_tags_and_note():
    photo = Photo(
        file_path="a.jpg",
        filename="a.jpg",
        primary_bird_cn="麻雀",
        scientific_name="Passer montanus",
        location_tag="世纪公园",
        tags=["风景", "昆虫"],
        note="补充说明",
    )
    tags = build_exif_tags_from_photo(photo)
    for kw in ("麻雀", "Passer montanus", "世纪公园", "风景", "昆虫"):
        assert kw in tags["IPTC:Keywords"]
        assert kw in tags["XMP:Subject"]
    assert "补充说明" in tags["XMP:Description"]
    assert "补充说明" in tags["ImageDescription"]


def test_build_exif_tags_without_tags_and_note_unchanged():
    photo = Photo(
        file_path="a.jpg",
        filename="a.jpg",
        primary_bird_cn="麻雀",
        scientific_name="Passer montanus",
        location_tag="世纪公园",
    )
    tags = build_exif_tags_from_photo(photo)
    assert tags["IPTC:Keywords"] == ["麻雀", "Passer montanus", "世纪公园"]
    assert "备注" not in tags["XMP:Description"]
