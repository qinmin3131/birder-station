"""视频流式播放（Range）与缩略图访问测试。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.models import Video, init_database, create_engine
from src.db.repository import VideoRepository
from src.web.path_helpers import get_video_mime
from src.web.routes.videos import init_video_routes, router


# ---------------------------------------------------------------------------
# MIME 工具
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "filename, expected",
    [
        ("a.mov", "video/quicktime"),
        ("a.MP4", "video/mp4"),
        ("a.mkv", "video/x-matroska"),
        ("a.mts", "video/mp2t"),
        ("a.wmv", "video/x-ms-wmv"),
        ("a.3gp", "video/3gpp"),
    ],
)
def test_get_video_mime(filename, expected):
    assert get_video_mime(filename) == expected


def test_get_video_mime_fallback(tmp_path):
    weird = tmp_path / "x.xyz"
    mime = get_video_mime(str(weird))
    assert mime == "application/octet-stream"


# ---------------------------------------------------------------------------
# 路由级测试
# ---------------------------------------------------------------------------

@pytest.fixture
def setup(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    init_database(engine)

    from sqlalchemy.orm import sessionmaker

    def factory():
        return sessionmaker(bind=engine)()

    # 一个"视频"文件（内容为占位字节，但路由层只做文件传输）
    video_file = tmp_path / "clip.mov"
    payload = bytes(range(256)) * 40  # 10240 字节
    video_file.write_bytes(payload)

    session = factory()
    video = VideoRepository(session).add(
        Video(
            file_path=str(video_file),
            filename="clip.mov",
            file_hash="a" * 64,
        )
    )
    video_id = video.id
    session.commit()
    session.close()

    app = FastAPI()
    app.include_router(router)
    init_video_routes(factory)

    client = TestClient(app)
    yield {
        "client": client,
        "video_id": video_id,
        "video_file": video_file,
        "factory": factory,
        "payload": payload,
    }

    init_video_routes(None)
    engine.dispose()


def test_stream_full_file(setup):
    resp = setup["client"].get(f"/api/videos/{setup['video_id']}/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/quicktime"
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.content == setup["payload"]


def test_stream_range_prefix(setup):
    resp = setup["client"].get(
        f"/api/videos/{setup['video_id']}/stream",
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == f"bytes 0-99/{len(setup['payload'])}"
    assert len(resp.content) == 100
    assert resp.content == setup["payload"][:100]


def test_stream_range_open_ended(setup):
    resp = setup["client"].get(
        f"/api/videos/{setup['video_id']}/stream",
        headers={"Range": "bytes=10000-"},
    )
    total = len(setup["payload"])
    assert resp.status_code == 206
    assert resp.headers["content-range"] == f"bytes 10000-{total - 1}/{total}"
    assert len(resp.content) == total - 10000


def test_stream_middle_range(setup):
    resp = setup["client"].get(
        f"/api/videos/{setup['video_id']}/stream",
        headers={"Range": "bytes=256-511"},
    )
    assert resp.status_code == 206
    assert len(resp.content) == 256
    assert resp.content == setup["payload"][256:512]


def test_stream_unknown_video_404(setup):
    resp = setup["client"].get("/api/videos/9999/stream")
    assert resp.status_code == 404


def test_stream_missing_file_404(setup):
    setup["video_file"].unlink()
    resp = setup["client"].get(f"/api/videos/{setup['video_id']}/stream")
    assert resp.status_code == 404


def test_thumbnail_placeholder_when_absent(setup):
    resp = setup["client"].get(f"/api/videos/{setup['video_id']}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"
    assert "暂无缩略图" in resp.text


def test_thumbnail_served_when_present(setup, tmp_path):
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")

    session = setup["factory"]()
    video = VideoRepository(session).get_by_id(setup["video_id"])
    video.thumbnail_path = str(thumb)
    session.commit()
    session.close()

    resp = setup["client"].get(f"/api/videos/{setup['video_id']}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_thumbnail_missing_file_falls_back_to_placeholder(setup, tmp_path):
    # DB 中记录了缩略图，但文件已丢失
    session = setup["factory"]()
    video = VideoRepository(session).get_by_id(setup["video_id"])
    video.thumbnail_path = str(tmp_path / "gone.jpg")
    session.commit()
    session.close()

    resp = setup["client"].get(f"/api/videos/{setup['video_id']}/thumbnail")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"


def test_thumbnail_unknown_video_404(setup):
    resp = setup["client"].get("/api/videos/9999/thumbnail")
    assert resp.status_code == 404
