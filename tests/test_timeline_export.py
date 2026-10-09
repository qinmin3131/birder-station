"""时间线导出测试：FCPXML / Premiere XML / EDL 三种格式 × 两种模式。"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from src.core.video.timeline_export import (
    Clip,
    build_clips_from_video,
    default_export_path,
    export_edl,
    export_fcpxml,
    export_premiere_xml,
    export_timeline,
)


# --- Mock data ---------------------------------------------------------------

class MockMarker:
    def __init__(self, kind, time=None, in_time=None, out_time=None,
                 value=None, category=None):
        self.kind = kind
        self.time = time
        self.in_time = in_time
        self.out_time = out_time
        self.value = value
        self.category = category


class MockVideo:
    def __init__(self, file_path="D:/videos/clip.mov", filename="clip.mov",
                 duration=10.0, fps=25.0, note="整体备注"):
        self.file_path = file_path
        self.filename = filename
        self.duration = duration
        self.fps = fps
        self.note = note


FULL_CLIPS = [
    Clip(
        file_path="D:/vid/a.mov",
        filename="a.mov",
        duration=10.0,
        markers=[
            {"kind": "point", "time": 3.0, "value": "高光"},
            {"kind": "segment", "in_time": 5.0, "out_time": 8.0,
             "value": "可用片段", "category": "可用"},
        ],
    ),
    Clip(
        file_path="D:/vid/b.mp4",
        filename="b.mp4",
        duration=15.0,
        markers=[
            {"kind": "point", "time": 7.5, "value": "起飞"},
        ],
    ),
]

SEGMENT_CLIPS = [
    Clip(
        file_path="D:/vid/a.mov", filename="a.mov", duration=10.0, markers=[],
        in_time=5.0, out_time=8.0, note="可用片段",
    ),
    Clip(
        file_path="D:/vid/b.mp4", filename="b.mp4", duration=15.0, markers=[],
        in_time=0.0, out_time=4.0, note="开头",
    ),
]


# --- FCPXML ------------------------------------------------------------------

def test_fcpxml_full_parses_and_has_assets():
    xml = export_fcpxml(FULL_CLIPS, "full")
    root = ET.fromstring(xml)
    assert root.tag == "fcpxml"
    assert root.get("version") == "1.9"
    assets = root.findall(".//asset")
    assert len(assets) == 2
    assert assets[0].get("name") == "a.mov"
    media_reps = root.findall(".//media-rep")
    assert media_reps[0].get("src") == "file://D:/vid/a.mov"

    asset_clips = root.findall(".//asset-clip")
    assert len(asset_clips) == 2
    # 第一段 offset=0, start=0, duration=10
    assert asset_clips[0].get("offset") == "0.000s"
    assert asset_clips[0].get("duration") == "10.000s"
    # 第二段 offset=10
    assert asset_clips[1].get("offset") == "10.000s"

    markers = root.findall(".//marker")
    assert len(markers) == 2
    assert markers[0].get("value") == "高光"


def test_fcpxml_segments_mode():
    xml = export_fcpxml(SEGMENT_CLIPS, "segments")
    root = ET.fromstring(xml)
    asset_clips = root.findall(".//asset-clip")
    assert len(asset_clips) == 2
    # 第一片段：start=5, duration=3
    assert asset_clips[0].get("start") == "5.000s"
    assert asset_clips[0].get("duration") == "3.000s"
    # 第二片段：start=0, duration=4
    assert asset_clips[1].get("start") == "0.000s"
    assert asset_clips[1].get("duration") == "4.000s"


def test_fcpxml_empty_segments_raises():
    with pytest.raises(ValueError, match="没有任何标记片段"):
        export_timeline([], "fcpxml", "segments")


# --- Premiere XML ------------------------------------------------------------

def test_premiere_xml_full_parses():
    xml = export_premiere_xml(FULL_CLIPS, "full")
    root = ET.fromstring(xml)
    assert root.tag == "xmeml"
    assert root.get("version") == "5"
    clipitems = root.findall(".//clipitem")
    assert len(clipitems) == 2
    assert clipitems[0].find("name").text == "a.mov"
    files = root.findall(".//file")
    assert files[0].find("pathurl").text == "file://D:/vid/a.mov"
    # 素材 0-10s, timeline 0-10
    assert clipitems[0].find("in").text == "0"
    assert clipitems[0].find("out").text == "10"
    markers = root.findall(".//marker")
    assert len(markers) == 2


def test_premiere_xml_segments_mode():
    xml = export_premiere_xml(SEGMENT_CLIPS, "segments")
    root = ET.fromstring(xml)
    clipitems = root.findall(".//clipitem")
    assert clipitems[0].find("in").text == "5"
    assert clipitems[0].find("out").text == "8"
    assert clipitems[1].find("in").text == "0"
    assert clipitems[1].find("out").text == "4"


# --- EDL ---------------------------------------------------------------------

def test_edl_full_structure():
    edl = export_edl(FULL_CLIPS, "full")
    lines = edl.strip().split("\n")
    assert lines[0] == "TITLE: 飞羽志导出"
    assert lines[1] == "FCM: NON-DROP FRAME"
    # 2 clips → 2 edit events with FROM CLIP NAME and SOURCE FILE
    assert "FROM CLIP NAME: a.mov" in edl
    assert "FROM CLIP NAME: b.mp4" in edl
    assert "SOURCE FILE: D:/vid/a.mov" in edl
    # Point markers → COMMENT lines
    assert "COMMENT:" in edl
    assert "高光" in edl


def test_edl_segments_mode():
    edl = export_edl(SEGMENT_CLIPS, "segments")
    lines = edl.strip().split("\n")
    assert lines[0] == "TITLE: 飞羽志导出"
    assert "FROM CLIP NAME: a.mov" in edl
    assert "FROM CLIP NAME: b.mp4" in edl
    # 精选片段不应有 COMMENT（markers 为空）
    assert "COMMENT:" not in edl


def test_edl_timecode_format():
    edl = export_edl(FULL_CLIPS[:1], "full", fps=25)
    # 第一条：source 0-10s, record 0-10s → 00:00:00:00 ~ 00:00:10:00
    assert "00:00:00:00" in edl
    assert "00:00:10:00" in edl


# --- build_clips_from_video --------------------------------------------------

def test_build_clips_full_mode():
    video = MockVideo(duration=10.0)
    markers = [
        MockMarker("point", time=3.0, value="p1"),
        MockMarker("segment", in_time=5.0, out_time=8.0, category="可用"),
    ]
    clips = build_clips_from_video(video, markers, "full")
    assert len(clips) == 1
    assert clips[0].duration == 10.0
    assert len(clips[0].markers) == 2


def test_build_clips_segments_mode():
    video = MockVideo(duration=10.0)
    markers = [
        MockMarker("point", time=3.0, value="p1"),
        MockMarker("segment", in_time=5.0, out_time=8.0, value="可用片段"),
        MockMarker("segment", in_time=1.0, out_time=2.0, value="开头"),
    ]
    clips = build_clips_from_video(video, markers, "segments")
    assert len(clips) == 2
    assert clips[0].in_time == 5.0
    assert clips[0].out_time == 8.0
    assert clips[1].in_time == 1.0


def test_build_clips_segments_no_segments():
    video = MockVideo()
    markers = [MockMarker("point", time=1.0, value="only point")]
    clips = build_clips_from_video(video, markers, "segments")
    assert clips == []


# --- default_export_path -----------------------------------------------------

def test_default_export_path(tmp_path):
    p = default_export_path("clip", "fcpxml", str(tmp_path))
    assert p.suffix == ".fcpxml"
    assert p.stem == "clip"


def test_default_export_path_existing_adds_timestamp(tmp_path):
    existing = tmp_path / "clip.fcpxml"
    existing.write_text("old")
    p = default_export_path("clip", "fcpxml", str(tmp_path))
    assert p.exists() is False
    assert p.stem.startswith("clip_")
    assert p.suffix == ".fcpxml"


def test_default_export_path_extensions(tmp_path):
    assert default_export_path("x", "fcpxml", str(tmp_path)).suffix == ".fcpxml"
    assert default_export_path("x", "premiere", str(tmp_path)).suffix == ".xml"
    assert default_export_path("x", "edl", str(tmp_path)).suffix == ".edl"


# --- export_timeline dispatch ------------------------------------------------

def test_export_timeline_invalid_format():
    with pytest.raises(ValueError, match="不支持的导出格式"):
        export_timeline(FULL_CLIPS, "invalid", "full")


# --- API 端点测试 ------------------------------------------------------------

@pytest.fixture
def setup(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.db.models import Video, VideoMarker, init_database, create_engine
    from src.db.repository import VideoRepository
    from src.web.routes.videos import init_video_routes, router

    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    init_database(engine)

    from sqlalchemy.orm import sessionmaker

    def factory():
        return sessionmaker(bind=engine)()

    session = factory()
    repo = VideoRepository(session)
    video = repo.add(Video(
        file_path=str(tmp_path / "clip.mov"),
        filename="clip.mov",
        file_hash="x" * 64,
        duration=10.0,
        fps=25.0,
    ))
    repo.add_marker(VideoMarker(
        video_id=video.id, kind="point", time=3.0, value="高光",
    ))
    repo.add_marker(VideoMarker(
        video_id=video.id, kind="segment", in_time=5.0, out_time=8.0,
        category="可用", value="可用片段",
    ))
    vid = video.id
    session.close()

    app = FastAPI()
    app.include_router(router)
    init_video_routes(factory)
    yield {"client": TestClient(app), "vid": vid, "factory": factory}
    init_video_routes(None)
    engine.dispose()


def test_api_export_video_fcpxml_full(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['vid']}/export",
        json={"fmt": "fcpxml", "mode": "full", "download": False},
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    root = ET.fromstring(content)
    assert root.tag == "fcpxml"
    assert root.findall(".//asset")
    assert root.findall(".//marker")


def test_api_export_video_fcpxml_segments(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['vid']}/export",
        json={"fmt": "fcpxml", "mode": "segments", "download": False},
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    root = ET.fromstring(content)
    assert len(root.findall(".//asset-clip")) == 1
    assert root.findall(".//asset-clip")[0].get("start") == "5.000s"


def test_api_export_video_premiere(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['vid']}/export",
        json={"fmt": "premiere", "mode": "full", "download": False},
    )
    assert resp.status_code == 200
    root = ET.fromstring(resp.json()["content"])
    assert root.tag == "xmeml"


def test_api_export_video_edl(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['vid']}/export",
        json={"fmt": "edl", "mode": "full", "download": False},
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    assert "TITLE:" in content
    assert "FROM CLIP NAME:" in content


def test_api_export_video_download(setup):
    resp = setup["client"].post(
        f"/api/videos/{setup['vid']}/export",
        json={"fmt": "fcpxml", "mode": "full", "download": True},
    )
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "clip.fcpxml" in resp.headers.get("content-disposition", "")
    # 内容是合法 XML
    ET.fromstring(resp.content)


def test_api_export_segments_empty_400(setup, tmp_path):
    """无片段标记时，精选模式应返回 400。"""
    from src.db.models import Video
    from src.db.repository import VideoRepository

    session = setup["factory"]()
    repo = VideoRepository(session)
    v = repo.add(Video(
        file_path=str(tmp_path / "no_markers.mov"),
        filename="no_markers.mov",
        file_hash="z" * 64,
        duration=5.0,
    ))
    session.close()

    resp = setup["client"].post(
        f"/api/videos/{v.id}/export",
        json={"fmt": "fcpxml", "mode": "segments", "download": False},
    )
    assert resp.status_code == 400
    assert "片段" in resp.json()["detail"]


def test_api_export_video_404(setup):
    resp = setup["client"].post(
        "/api/videos/999/export",
        json={"fmt": "fcpxml", "mode": "full"},
    )
    assert resp.status_code == 404
