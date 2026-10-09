"""VideoRepository 单元测试：视频查询筛选与标记 CRUD。"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import init_database, Video, VideoMarker, Outing
from src.db.repository import VideoRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    init_database(engine)
    db_session = sessionmaker(bind=engine)()
    yield db_session
    db_session.close()


@pytest.fixture
def repo(session):
    return VideoRepository(session)


def _make_outing(session, name="20261001_北京_奥森", date_str="20261001"):
    outing = Outing(name=name, start_date=date_str)
    session.add(outing)
    session.commit()
    session.refresh(outing)
    return outing


def _add_video(
    repo,
    outing,
    filename="a.mov",
    hash_="h1",
    captured_date="20261001",
    captured_at=None,
    note=None,
    tags=None,
    location=None,
):
    video = Video(
        file_path=f"/data/{filename}",
        filename=filename,
        original_path=f"/data/{filename}",
        file_hash=hash_,
        captured_date=captured_date,
        captured_at=captured_at,
        note=note,
        tags=tags,
        outing_id=outing.id,
        **(location or {}),
    )
    return repo.add(video)


def test_add_and_lookups(repo, session):
    outing = _make_outing(session)
    video = _add_video(repo, outing, filename="clip.mov", hash_="abc")

    assert repo.get_by_id(video.id).id == video.id
    assert repo.get_by_hash("abc").filename == "clip.mov"
    assert repo.get_by_path_and_name("/data/clip.mov", "clip.mov") is not None


def test_delete_cascades_markers(repo, session):
    outing = _make_outing(session)
    video = _add_video(repo, outing, hash_="h1")
    repo.add_marker(
        VideoMarker(video_id=video.id, kind="point", time=1.0, value="x")
    )

    repo.delete(video)

    assert repo.get_by_id(video.id) is None
    assert session.query(VideoMarker).count() == 0


def test_list_by_outing(repo, session):
    outing1 = _make_outing(session, "20261001_北京_奥森")
    outing2 = _make_outing(session, "20261002_北京_颐和园", "20261002")
    _add_video(repo, outing1, "a.mov", "h1")
    _add_video(repo, outing1, "b.mov", "h2")
    _add_video(repo, outing2, "c.mov", "h3")

    results = repo.list_videos(outing_id=outing1.id)
    assert {v.filename for v in results} == {"a.mov", "b.mov"}


def test_list_by_date_range(repo, session):
    outing = _make_outing(session)
    _add_video(repo, outing, "a.mov", "h1", captured_date="20261001")
    _add_video(repo, outing, "b.mov", "h2", captured_date="20261005")
    _add_video(repo, outing, "c.mov", "h3", captured_date="20261010")

    results = repo.list_videos(date_from="20261002", date_to="20261008")
    assert {v.filename for v in results} == {"b.mov"}


def test_list_by_location(repo, session):
    outing = _make_outing(session)
    _add_video(
        repo, outing, "a.mov", "h1",
        location={"location_level1": "北京", "location_level2": "北京市",
                  "location_level3": "奥森"},
    )
    _add_video(
        repo, outing, "b.mov", "h2",
        location={"location_level1": "上海", "location_level2": "上海市",
                  "location_level3": "世纪公园"},
    )

    assert {v.filename for v in repo.list_videos(location_level1="北京")} == {"a.mov"}
    assert {v.filename for v in repo.list_videos(location_level3="世纪公园")} == {"b.mov"}


def test_list_by_tag(repo, session):
    outing = _make_outing(session)
    _add_video(repo, outing, "a.mov", "h1", tags=["vlog", "采访"])
    _add_video(repo, outing, "b.mov", "h2", tags=["空镜"])

    assert {v.filename for v in repo.list_videos(tag="采访")} == {"a.mov"}


def test_list_by_keyword_filename_note_marker(repo, session):
    outing = _make_outing(session)
    _add_video(repo, outing, "interview.mov", "h1")
    _add_video(repo, outing, "b.mov", "h2", note="这段记录了鸟群起飞")
    video3 = _add_video(repo, outing, "c.mov", "h3")
    repo.add_marker(
        VideoMarker(video_id=video3.id, kind="point", time=5.0,
                    value="翠鸟入水瞬间")
    )

    assert {v.filename for v in repo.list_videos(q="interview")} == {"interview.mov"}
    assert {v.filename for v in repo.list_videos(q="鸟群起飞")} == {"b.mov"}
    assert {v.filename for v in repo.list_videos(q="翠鸟")} == {"c.mov"}


def test_list_orders_by_captured_at_desc(repo, session):
    outing = _make_outing(session)
    _add_video(
        repo, outing, "old.mov", "h1",
        captured_at=datetime(2026, 10, 1, 8, 0, 0),
    )
    _add_video(
        repo, outing, "new.mov", "h2",
        captured_at=datetime(2026, 10, 1, 10, 0, 0),
    )

    results = repo.list_videos(outing_id=outing.id)
    assert [v.filename for v in results] == ["new.mov", "old.mov"]


def test_marker_crud(repo, session):
    outing = _make_outing(session)
    video = _add_video(repo, outing, hash_="h1")

    marker = repo.add_marker(
        VideoMarker(
            video_id=video.id, kind="segment",
            in_time=10.0, out_time=20.0,
            value="可用片段", category="可用",
        )
    )
    point = repo.add_marker(
        VideoMarker(video_id=video.id, kind="point", time=5.0, value="打点")
    )

    assert len(repo.list_markers(video.id)) == 2
    assert len(repo.list_markers(video.id, kind="segment")) == 1

    updated = repo.update_marker(marker.id, {"value": "更新后", "category": "采访"})
    assert updated.value == "更新后" and updated.category == "采访"

    repo.delete_marker(point)
    assert {m.id for m in repo.list_markers(video.id)} == {marker.id}


def test_update_missing_marker_returns_none(repo):
    assert repo.update_marker(999, {"value": "x"}) is None
