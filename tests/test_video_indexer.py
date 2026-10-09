"""视频索引与后台导入流程测试。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.video.indexer import VideoIndexer, SUPPORTED_VIDEO_FORMATS
from src.db.models import init_database, create_engine
from src.db.repository import VideoRepository


@pytest.fixture
def repo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_database(engine)
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    yield VideoRepository(session)
    session.close()
    engine.dispose()


def _make_videos(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "clip1.mov").write_bytes(b"fake-mov-data-1")
    (folder / "clip2.mp4").write_bytes(b"fake-mp4-data-2")
    (folder / "clip3.MOV").write_bytes(b"fake-mov-data-3")  # 大写扩展名
    (folder / "photo.jpg").write_bytes(b"not-a-video")
    (folder / "notes.txt").write_text("ignore me")


def test_index_folder_basic(repo, tmp_path):
    folder = tmp_path / "20261001_北京_奥森"
    _make_videos(folder)

    indexer = VideoIndexer(repo)
    result = indexer.index_folder_with_stats(folder, outing_id=7)

    assert result["indexed"] == 3
    assert result["skipped"] == 0
    assert result["errors"] == 0
    assert len(result["video_ids"]) == 3

    videos = repo.list_videos()
    assert len(videos) == 3
    for video in videos:
        assert video.outing_id == 7
        assert video.captured_date == "20261001"
        assert video.captured_at is not None
        assert video.file_hash
        assert Path(video.file_path).exists()


def test_index_skips_non_video_files(repo, tmp_path):
    folder = tmp_path / "outing"
    _make_videos(folder)

    videos = VideoIndexer(repo).index_folder_with_stats(folder)["indexed"]
    assert videos == 3  # jpg/txt 不被当作视频


def test_index_dedup_by_hash_on_repeat(repo, tmp_path):
    folder = tmp_path / "20261001_北京_奥森"
    _make_videos(folder)
    indexer = VideoIndexer(repo)

    first = indexer.index_folder_with_stats(folder)
    assert first["indexed"] == 3

    # 未探测记录重复导入：跳过新增，但仍进入待探测队列
    second = indexer.index_folder_with_stats(folder)
    assert second["indexed"] == 0
    assert second["skipped"] == 3
    assert len(second["video_ids"]) == 3


def test_probed_videos_not_requed(repo, tmp_path):
    folder = tmp_path / "outing"
    _make_videos(folder)
    indexer = VideoIndexer(repo)
    result = indexer.index_folder_with_stats(folder)

    # 模拟探测完成
    for video_id in result["video_ids"]:
        video = repo.get_by_id(video_id)
        video.duration = 10.0
        video.probe_failed = False
    repo.session.commit()

    again = indexer.index_folder_with_stats(folder)
    assert again["video_ids"] == []


def test_existing_record_gets_outing_assigned(repo, tmp_path):
    folder = tmp_path / "outing"
    _make_videos(folder)
    indexer = VideoIndexer(repo)
    indexer.index_folder_with_stats(folder)  # 无 outing

    result = indexer.index_folder_with_stats(folder, outing_id=42)
    videos = repo.list_videos()
    assert all(v.outing_id == 42 for v in videos)
    assert result["skipped"] == 3


def test_non_recursive_mode(repo, tmp_path):
    folder = tmp_path / "outing"
    _make_videos(folder)
    sub = folder / "sub"
    sub.mkdir()
    (sub / "deep.mov").write_bytes(b"deep-video")

    result = VideoIndexer(repo).index_folder_with_stats(
        folder, recursive=False
    )
    assert result["indexed"] == 3  # 子目录中的 deep.mov 不被索引


def test_location_info_applied(repo, tmp_path):
    folder = tmp_path / "outing"
    _make_videos(folder)
    location_info = {
        "location_tag": "奥森",
        "location_level1": "北京",
        "location_level2": "朝阳",
        "location_level3": None,
    }
    VideoIndexer(repo).index_folder_with_stats(
        folder, location_info=location_info
    )
    for video in repo.list_videos():
        assert video.location_tag == "奥森"
        assert video.location_level1 == "北京"
        assert video.location_level2 == "朝阳"


def test_index_does_not_probe_or_recognize(repo, tmp_path):
    """索引阶段不得调用 ffmpeg 探测或抽帧，更不触发识别。"""
    folder = tmp_path / "outing"
    _make_videos(folder)

    with patch("src.core.video.ffmpeg_tools.probe_video") as mock_probe, \
         patch("src.core.video.ffmpeg_tools.extract_poster") as mock_poster:
        VideoIndexer(repo).index_folder_with_stats(folder)
        mock_probe.assert_not_called()
        mock_poster.assert_not_called()


def test_custom_supported_formats(repo, tmp_path):
    folder = tmp_path / "outing"
    _make_videos(folder)
    indexer = VideoIndexer(repo, supported_formats={".mp4"})
    result = indexer.index_folder_with_stats(folder)
    assert result["indexed"] == 1


# ---------------------------------------------------------------------------
# 后台导入线程（同步直接调用线程函数）
# ---------------------------------------------------------------------------

PROBE_INFO = {
    "duration": 12.5,
    "width": 1920,
    "height": 1080,
    "fps": 29.97,
    "video_codec": "h264",
    "audio_codec": "aac",
}


def test_video_import_thread_probes_and_thumbnails(tmp_path, monkeypatch):
    import src.web.task_manager as tm_module

    # 将缩略图目录与 CWD 重定向到临时目录，避免污染仓库
    monkeypatch.setattr(tm_module, "BASE_DIR", tmp_path)

    folder = tmp_path / "20261001_北京_奥森"
    _make_videos(folder)
    db_path = tmp_path / "data" / "test.db"

    def fake_poster(path, output_path):
        Path(output_path).write_bytes(b"fake-jpeg")

    tm = tm_module.TaskManager()
    with patch(
        "src.core.video.ffmpeg_tools.probe_video", return_value=PROBE_INFO
    ) as mock_probe, patch(
        "src.core.video.ffmpeg_tools.extract_poster",
        side_effect=fake_poster,
    ) as mock_poster:
        tm._run_video_import_thread(
            str(folder), True, False,
            {"paths": {"db_path": str(db_path)}}, None, None,
        )

    assert mock_probe.call_count == 3
    assert mock_poster.call_count == 3
    assert not tm.is_running

    engine = create_engine(f"sqlite:///{db_path}")
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    videos = VideoRepository(session).list_videos()
    try:
        assert len(videos) == 3
        for video in videos:
            assert video.duration == 12.5
            assert video.width == 1920
            assert video.height == 1080
            assert video.video_codec == "h264"
            assert video.audio_codec == "aac"
            assert video.probe_failed is False
            assert video.thumbnail_path
            assert Path(video.thumbnail_path).exists()
    finally:
        session.close()
        engine.dispose()


def test_video_import_thread_probe_failure_does_not_abort(
    tmp_path, monkeypatch
):
    """单个视频损坏/探测失败时任务继续，失败记录打上 probe_failed。"""
    import src.web.task_manager as tm_module

    monkeypatch.setattr(tm_module, "BASE_DIR", tmp_path)

    folder = tmp_path / "outing"
    _make_videos(folder)
    db_path = tmp_path / "data" / "test.db"

    def probe_side_effect(path):
        if path.endswith("clip1.mov"):
            raise RuntimeError("moov atom not found")
        return PROBE_INFO

    def fake_poster(path, output_path):
        Path(output_path).write_bytes(b"fake-jpeg")

    tm = tm_module.TaskManager()
    with patch(
        "src.core.video.ffmpeg_tools.probe_video",
        side_effect=probe_side_effect,
    ) as mock_probe, patch(
        "src.core.video.ffmpeg_tools.extract_poster",
        side_effect=fake_poster,
    ):
        tm._run_video_import_thread(
            str(folder), True, False,
            {"paths": {"db_path": str(db_path)}}, None, None,
        )

    assert mock_probe.call_count == 3
    assert not tm.is_running

    engine = create_engine(f"sqlite:///{db_path}")
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    repo = VideoRepository(session)
    try:
        failed = repo.get_by_path_and_name(
            str(folder / "clip1.mov"), "clip1.mov"
        )
        assert failed.probe_failed is True
        assert failed.duration is None
        ok = repo.list_videos()
        assert sum(1 for v in ok if v.probe_failed is False) == 2
    finally:
        session.close()
        engine.dispose()


def test_video_import_thread_idempotent_rerun(tmp_path, monkeypatch):
    """重复导入：已成功探测的视频不重复探测，失败的视频重新尝试。"""
    import src.web.task_manager as tm_module

    monkeypatch.setattr(tm_module, "BASE_DIR", tmp_path)

    folder = tmp_path / "outing"
    _make_videos(folder)
    db_path = tmp_path / "data" / "test.db"
    config = {"paths": {"db_path": str(db_path)}}

    call_count = {"n": 0}

    def flaky_probe(path):
        if path.endswith("clip1.mov"):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first run fails")
        return PROBE_INFO

    def fake_poster(path, output_path):
        Path(output_path).write_bytes(b"fake-jpeg")

    tm = tm_module.TaskManager()
    with patch(
        "src.core.video.ffmpeg_tools.probe_video", side_effect=flaky_probe
    ) as mock_probe, patch(
        "src.core.video.ffmpeg_tools.extract_poster",
        side_effect=fake_poster,
    ):
        tm._run_video_import_thread(
            str(folder), True, False, config, None, None
        )
        # 第二次运行：2 个成功的不再探测，只重试 clip1
        tm._run_video_import_thread(
            str(folder), True, False, config, None, None
        )

    # 第一次 3 次，第二次仅重试失败的 1 次
    assert mock_probe.call_count == 4

    engine = create_engine(f"sqlite:///{db_path}")
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    repo = VideoRepository(session)
    try:
        videos = repo.list_videos()
        assert all(v.probe_failed is False for v in videos)
        assert len(videos) == 3
    finally:
        session.close()
        engine.dispose()
