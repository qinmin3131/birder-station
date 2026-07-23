from datetime import datetime
from pathlib import Path
from unittest.mock import ANY, patch

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Photo, PhotoGroup
from src.web import app as web_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_review.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr(web_app, "db_path", db_path)
    monkeypatch.setattr(web_app, "config", {"paths": {"source_dir": str(tmp_path)}})

    def _get_session():
        return SessionLocal()

    monkeypatch.setattr(web_app, "get_sqlalchemy_session", _get_session)

    with TestClient(web_app.app) as c:
        yield c


@pytest.fixture
def sample_jpg(tmp_path):
    img_path = tmp_path / "bird.jpg"
    Image.new("RGB", (800, 600), color="green").save(img_path)
    return img_path


@pytest.fixture
def sample_raw(tmp_path):
    raw_path = tmp_path / "bird.orf"
    raw_path.write_bytes(b"fake raw bytes")
    return raw_path


def _create_photo(session, **kwargs):
    defaults = {
        "file_path": "bird.jpg",
        "filename": "bird.jpg",
        "original_path": None,
        "width": 800,
        "height": 600,
        "captured_at": None,
        "captured_date": "2026-07-20",
        "primary_bird_cn": "麻雀",
        "scientific_name": "Passer montanus",
        "confidence_score": 0.95,
        "quality_score": 85,
        "is_selected": False,
        "rating": 0,
    }
    defaults.update(kwargs)
    photo = Photo(**defaults)
    session.add(photo)
    session.commit()
    session.refresh(photo)
    return photo


def test_review_returns_photo_metadata_and_exif_summary(client, sample_jpg, monkeypatch):
    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(
        session,
        original_path=str(sample_jpg),
        candidates_json=[{"sci": "Passer montanus", "cn": "麻雀", "score": 0.95}],
        quality_details={"clarity": 80, "exposure": 90},
        bird_bbox=[100, 100, 300, 300],
    )
    session.close()

    fake_exif = {
        "camera_make": "OLYMPUS",
        "camera_model": "OM-1",
        "lens_model": "M.Zuiko 300mm",
        "aperture": "F5.6",
        "shutter_speed": "1/1000",
        "iso": 800,
        "focal_length": "300.0 mm",
        "date_time_original": "2026:07:20 10:00:00",
        "gps_latitude": "39.9",
        "gps_longitude": "116.3",
        "image_size": "800x600",
        "file_size": sample_jpg.stat().st_size,
        "raw": {},
    }
    with patch.object(web_app, "read_exif_summary", return_value=fake_exif):
        response = client.get(f"/api/photo/{photo.id}/review")
    assert response.status_code == 200

    data = response.json()
    assert data["photo"]["id"] == photo.id
    assert data["photo"]["filename"] == "bird.jpg"
    assert data["photo"]["primary_bird_cn"] == "麻雀"
    assert data["photo"]["bird_bbox"] == [100, 100, 300, 300]
    assert data["candidates"][0]["cn"] == "麻雀"
    assert data["quality_details"]["exposure"] == 90
    assert data["exif"]["camera_make"] == "OLYMPUS"
    assert data["exif"]["iso"] == 800
    assert data["exif"]["file_size"] == sample_jpg.stat().st_size


def test_review_returns_neighbor_ids_within_group(client, sample_jpg, monkeypatch):
    session = web_app.get_sqlalchemy_session()
    g1 = PhotoGroup(
        outing_id=1,
        best_photo_id=0,
        created_at=datetime(2026, 7, 20, 8, 0, 0),
    )
    session.add(g1)
    session.commit()
    session.refresh(g1)

    p1 = _create_photo(
        session,
        original_path=str(sample_jpg),
        filename="a.jpg",
        captured_at=datetime(2026, 7, 20, 8, 0, 1),
        group_id=g1.id,
    )
    p2 = _create_photo(
        session,
        original_path=str(sample_jpg),
        filename="b.jpg",
        captured_at=datetime(2026, 7, 20, 8, 0, 2),
        group_id=g1.id,
    )
    p3 = _create_photo(
        session,
        original_path=str(sample_jpg),
        filename="c.jpg",
        captured_at=datetime(2026, 7, 20, 8, 0, 3),
        group_id=g1.id,
    )
    p1_id = p1.id
    p2_id = p2.id
    p3_id = p3.id
    session.close()

    data = client.get(f"/api/photo/{p2_id}/review").json()
    assert data["prev_photo_id"] == p1_id
    assert data["next_photo_id"] == p3_id

    data_first = client.get(f"/api/photo/{p1_id}/review").json()
    assert data_first["prev_photo_id"] is None
    assert data_first["next_photo_id"] == p2_id

    data_last = client.get(f"/api/photo/{p3_id}/review").json()
    assert data_last["prev_photo_id"] == p2_id
    assert data_last["next_photo_id"] is None


    response = client.get("/api/photo/9999/review")
    assert response.status_code == 404
    assert "Photo not found" in response.json()["detail"]


def test_review_returns_404_when_original_file_missing(client):
    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(session, original_path="/nonexistent/bird.jpg")
    photo_id = photo.id
    session.close()

    response = client.get(f"/api/photo/{photo_id}/review")
    assert response.status_code == 404
    assert "Original file not found" in response.json()["detail"]


def test_preview_returns_jpeg_for_existing_jpg(client, sample_jpg):
    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(session, original_path=str(sample_jpg))
    photo_id = photo.id
    session.close()

    response = client.get(f"/api/photo/{photo_id}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_preview_decodes_raw_to_temp_jpg(client, sample_raw, monkeypatch):
    decoded_jpg = sample_raw.parent / "decoded.jpg"
    Image.new("RGB", (800, 600), color="blue").save(decoded_jpg)

    monkeypatch.setattr(
        web_app.ImageProcessor, "is_raw", staticmethod(lambda path: True)
    )
    monkeypatch.setattr(
        web_app.ImageProcessor,
        "decode_raw_to_temp_jpg",
        staticmethod(lambda path: str(decoded_jpg)),
    )

    session = web_app.get_sqlalchemy_session()
    photo = _create_photo(session, original_path=str(sample_raw))
    photo_id = photo.id
    session.close()

    response = client.get(f"/api/photo/{photo_id}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_preview_returns_404_when_photo_missing(client):
    response = client.get("/api/photo/9999/preview")
    assert response.status_code == 404
