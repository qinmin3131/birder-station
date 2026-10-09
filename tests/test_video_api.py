"""视频浏览/详情/更新与时间线标记 CRUD API 测试。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.models import Video, init_database, create_engine
from src.db.repository import VideoRepository
from src.web.routes.videos import init_video_routes, router


@pytest.fixture
def setup(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    init_database(engine)

    from sqlalchemy.orm import sessionmaker

    def factory():
        return sessionmaker(bind=engine)()

    base = datetime(2026, 10, 1, 10, 0, 0)
    session = factory()
    repo = VideoRepository(session)
    v1 = repo.add(
        Video(
            file_path=str(tmp_path / "a.mov"),
            filename="a.mov",
            file_hash="a" * 64,
            duration=10.0,
            captured_date="20261001",
            captured_at=base,
            outing_id=1,
        )
    )
    v2 = repo.add(
        Video(
            file_path=str(tmp_path / "b.mp4"),
            filename="b.mp4",
            file_hash="b" * 64,
            duration=20.0,
            captured_date="20261001",
            captured_at=base + timedelta(hours=2),
            outing_id=1,
        )
    )
    v3 = repo.add(
        Video(
            file_path=str(tmp_path / "c.mov"),
            filename="c.mov",
            file_hash="c" * 64,
            duration=5.0,
            captured_date="20260930",
            captured_at=base - timedelta(days=1),
            outing_id=2,
        )
    )
    ids = {"v1": v1.id, "v2": v2.id, "v3": v3.id}
    session.close()

    app = FastAPI()
    app.include_router(router)
    init_video_routes(factory)

    yield {"client": TestClient(app), "ids": ids, "factory": factory}

    init_video_routes(None)
    engine.dispose()


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------

def test_list_all(setup):
    resp = setup["client"].get("/api/videos")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["has_more"] is False
    # 倒序：v2(12:00) -> v1(10:00) -> v3(前一天)
    assert [v["id"] for v in data["items"]] == [
        setup["ids"]["v2"],
        setup["ids"]["v1"],
        setup["ids"]["v3"],
    ]
    # 序列化附带可直接使用的 URL
    item = data["items"][0]
    assert item["stream_url"].endswith("/stream")
    assert item["thumbnail_url"].endswith("/thumbnail")


def test_list_filter_by_outing(setup):
    resp = setup["client"].get("/api/videos", params={"outing_id": 2})
    items = resp.json()["items"]
    assert [v["id"] for v in items] == [setup["ids"]["v3"]]


def test_list_filter_by_date_range(setup):
    resp = setup["client"].get(
        "/api/videos",
        params={"date_from": "20261001", "date_to": "20261001"},
    )
    assert len(resp.json()["items"]) == 2


def test_list_pagination_has_more(setup):
    resp = setup["client"].get("/api/videos", params={"limit": 2})
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["has_more"] is True

    next_page = setup["client"].get(
        "/api/videos", params={"limit": 2, "offset": 2}
    ).json()
    assert len(next_page["items"]) == 1
    assert next_page["has_more"] is False


def test_list_search_by_filename(setup):
    resp = setup["client"].get("/api/videos", params={"q": "b.mp4"})
    items = resp.json()["items"]
    assert [v["id"] for v in items] == [setup["ids"]["v2"]]


def test_list_search_by_marker_value(setup):
    # 先给 v1 加一个标记，再用标记内容搜索
    client = setup["client"]
    client.post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": 3.0, "value": "苍鹭起飞瞬间"},
    )
    resp = client.get("/api/videos", params={"q": "苍鹭"})
    items = resp.json()["items"]
    assert [v["id"] for v in items] == [setup["ids"]["v1"]]


# ---------------------------------------------------------------------------
# 详情
# ---------------------------------------------------------------------------

def test_detail_includes_markers(setup):
    client = setup["client"]
    vid = setup["ids"]["v1"]
    client.post(
        f"/api/videos/{vid}/markers",
        json={"kind": "point", "time": 1.0, "value": "p1"},
    )
    client.post(
        f"/api/videos/{vid}/markers",
        json={
            "kind": "segment",
            "in_time": 2.0,
            "out_time": 8.0,
            "category": "可用",
        },
    )
    resp = client.get(f"/api/videos/{vid}")
    data = resp.json()
    assert len(data["markers"]) == 2
    # point 在前，segment 在后（按时间排序）
    assert data["markers"][0]["kind"] == "point"
    assert data["markers"][1]["category"] == "可用"


def test_detail_404(setup):
    assert setup["client"].get("/api/videos/999").status_code == 404


# ---------------------------------------------------------------------------
# 更新视频
# ---------------------------------------------------------------------------

def test_update_note_and_tags(setup):
    vid = setup["ids"]["v1"]
    resp = setup["client"].put(
        f"/api/videos/{vid}",
        json={"note": "整体备注", "tags": ["奥森", "苍鹭"]},
    )
    data = resp.json()
    assert data["note"] == "整体备注"
    assert data["tags"] == ["奥森", "苍鹭"]


def test_update_tags_must_be_array(setup):
    vid = setup["ids"]["v1"]
    resp = setup["client"].put(
        f"/api/videos/{vid}", json={"tags": "not-array"}
    )
    assert resp.status_code == 400


def test_update_404(setup):
    assert setup["client"].put("/api/videos/999", json={"note": "x"}).status_code == 404


# ---------------------------------------------------------------------------
# 标记创建
# ---------------------------------------------------------------------------

def test_create_point_marker(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": 5.5, "value": "高光时刻"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "point"
    assert data["time"] == 5.5
    assert data["completed"] is False


def test_create_segment_marker(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={
            "kind": "segment",
            "in_time": 1.0,
            "out_time": 4.0,
            "category": "B-roll",
            "value": "空镜",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["category"] == "B-roll"


def test_create_point_without_time_400(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point"},
    )
    assert resp.status_code == 400


def test_create_invalid_kind_400(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "weird", "time": 1},
    )
    assert resp.status_code == 400


def test_create_segment_bad_range_400(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "segment", "in_time": 8.0, "out_time": 3.0},
    )
    assert resp.status_code == 400


def test_create_marker_beyond_duration_400(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": 11.0},
    )
    assert resp.status_code == 400


def test_create_marker_negative_time_400(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": -1.0},
    )
    assert resp.status_code == 400


def test_create_invalid_category_400(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={
            "kind": "segment",
            "in_time": 1.0,
            "out_time": 2.0,
            "category": "随便",
        },
    )
    assert resp.status_code == 400


def test_create_marker_404_video(setup):
    resp = setup["client"].post(
        "/api/videos/999/markers",
        json={"kind": "point", "time": 1},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 标记更新 / 删除
# ---------------------------------------------------------------------------

def test_update_marker(setup):
    client = setup["client"]
    created = client.post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": 2.0, "value": "old"},
    ).json()

    resp = client.put(
        f"/api/videos/markers/{created['id']}",
        json={"value": "new", "completed": True},
    )
    data = resp.json()
    assert data["value"] == "new"
    assert data["completed"] is True


def test_update_marker_rollback_on_invalid(setup):
    """校验失败时，修改不得落库。"""
    client = setup["client"]
    created = client.post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": 2.0, "value": "keep"},
    ).json()

    resp = client.put(
        f"/api/videos/markers/{created['id']}",
        json={"time": 99.0},
    )
    assert resp.status_code == 400

    detail = client.get(f"/api/videos/{setup['ids']['v1']}").json()
    assert detail["markers"][0]["time"] == 2.0


def test_update_marker_unknown_field_400(setup):
    client = setup["client"]
    created = client.post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": 2.0},
    ).json()
    resp = client.put(
        f"/api/videos/markers/{created['id']}",
        json={"kind": "segment"},
    )
    assert resp.status_code == 400


def test_update_marker_404(setup):
    resp = setup["client"].put(
        "/api/videos/markers/999", json={"value": "x"}
    )
    assert resp.status_code == 404


def test_delete_marker(setup):
    client = setup["client"]
    created = client.post(
        f"/api/videos/{setup['ids']['v1']}/markers",
        json={"kind": "point", "time": 2.0},
    ).json()

    resp = client.delete(f"/api/videos/markers/{created['id']}")
    assert resp.status_code == 200

    detail = client.get(f"/api/videos/{setup['ids']['v1']}").json()
    assert detail["markers"] == []


def test_delete_marker_404(setup):
    assert setup["client"].delete("/api/videos/markers/999").status_code == 404
