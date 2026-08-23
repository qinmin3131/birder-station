import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.trash_service import TrashService
from src.db.models import Base, Photo, PhotoGroup, Species


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


@pytest.fixture
def sent():
    return []


@pytest.fixture
def service(session, tmp_path, sent):
    def _send(path):
        sent.append(str(path))
    processed = tmp_path / "processed"
    processed.mkdir()
    return TrashService(session, [tmp_path], processed_dir=processed, send_func=_send)


def _make_photo(tmp_path, name="a.jpg", rating=-1, **kwargs):
    src = tmp_path / name
    src.write_bytes(b"fake image data")
    return Photo(file_path=str(src), original_path=str(src), filename=name, rating=rating, **kwargs)


def test_empty_moves_original_and_sidecar_and_deletes_record(service, session, tmp_path, sent):
    photo = _make_photo(tmp_path)
    session.add(photo)
    session.commit()
    sidecar = tmp_path / "a.jpg.xmp"
    sidecar.write_text("<xmp/>", encoding="utf-8")

    result = service.empty()

    assert result["moved"] == 1
    assert result["deleted"] == 1
    assert result["errors"] == []
    assert sent == [str(tmp_path / "a.jpg"), str(sidecar)]
    assert session.query(Photo).count() == 0


def test_empty_filters_by_outing(service, session, tmp_path):
    p1 = _make_photo(tmp_path, "a.jpg", outing_id=1)
    p2 = _make_photo(tmp_path, "b.jpg", outing_id=2)
    session.add_all([p1, p2])
    session.commit()

    result = service.empty(outing_id=1)

    assert result["deleted"] == 1
    remaining = session.query(Photo).all()
    assert len(remaining) == 1
    assert remaining[0].outing_id == 2


def test_empty_ignores_non_rejected(service, session, tmp_path):
    session.add(_make_photo(tmp_path, "keep.jpg", rating=3))
    session.add(_make_photo(tmp_path, "bad.jpg", rating=-1))
    session.commit()

    result = service.empty()

    assert result["deleted"] == 1
    assert session.query(Photo).one().filename == "keep.jpg"


def test_missing_original_counts_skipped_but_deletes_record(service, session):
    session.add(Photo(file_path="D:/gone/a.jpg", original_path="D:/gone/a.jpg", filename="a.jpg", rating=-1))
    session.commit()

    result = service.empty()

    assert result["skipped"] == 1
    assert result["moved"] == 0
    assert result["deleted"] == 1
    assert session.query(Photo).count() == 0


def test_send_error_keeps_record(session, tmp_path):
    def boom(path):
        raise OSError("file in use")
    service = TrashService(session, [tmp_path], processed_dir=tmp_path / "processed", send_func=boom)
    session.add(_make_photo(tmp_path))
    session.commit()

    result = service.empty()

    assert result["errors"][0]["error"] == "file in use"
    assert result["deleted"] == 0
    assert session.query(Photo).count() == 1


def test_reselects_best_photo_in_group(service, session, tmp_path, sent):
    group = PhotoGroup(best_photo_id=0)
    session.add(group)
    session.flush()
    bad = _make_photo(tmp_path, "bad.jpg", group_id=group.id, quality_score=30)
    good = _make_photo(tmp_path, "good.jpg", rating=None, group_id=group.id, quality_score=90)
    session.add_all([bad, good])
    session.flush()
    group.best_photo_id = bad.id
    session.commit()

    service.empty()

    session.expire_all()
    assert group.best_photo_id == good.id
    assert session.query(PhotoGroup).count() == 1


def test_deletes_empty_group(service, session, tmp_path):
    group = PhotoGroup(best_photo_id=0)
    session.add(group)
    session.flush()
    bad = _make_photo(tmp_path, "bad.jpg", group_id=group.id)
    session.add(bad)
    session.flush()
    group.best_photo_id = bad.id
    session.commit()

    service.empty()

    assert session.query(PhotoGroup).count() == 0


def test_refreshes_species_stats(service, session, tmp_path):
    session.add(Species(scientific_name="Passer montanus", chinese_name="麻雀", photo_count=1))
    session.add(_make_photo(tmp_path, scientific_name="Passer montanus"))
    session.commit()

    service.empty()

    assert session.query(Species).filter(Species.scientific_name == "Passer montanus").first() is None


def test_removes_processed_crop_only_inside_processed_dir(service, session, tmp_path):
    processed = tmp_path / "processed"
    photo = _make_photo(tmp_path, "a.jpg")
    crop = processed / "a_crop.jpg"
    crop.write_bytes(b"crop")
    photo.file_path = str(crop)
    session.add(photo)
    outside = _make_photo(tmp_path, "b.jpg")
    session.add(outside)
    session.commit()

    service.empty()

    assert not crop.exists()
    assert (tmp_path / "b.jpg").exists()


def test_list_rejected_counts_and_samples(service, session, tmp_path):
    for name in ["a.jpg", "b.jpg", "c.jpg"]:
        session.add(_make_photo(tmp_path, name))
    session.commit()

    info = service.list_rejected()

    assert info["count"] == 3
    assert info["total_bytes"] == 3 * len(b"fake image data")
    assert info["sample_filenames"] == ["a.jpg", "b.jpg", "c.jpg"]
