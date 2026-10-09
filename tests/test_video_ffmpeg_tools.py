"""ffmpeg_tools 单元测试：路径解析、探测回退、海报帧回退。"""
import json

import pytest

from src.core.video import ffmpeg_tools


FFPROBE_JSON = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "25/1",
            "r_frame_rate": "25/1",
        },
        {"codec_type": "audio", "codec_name": "aac"},
    ],
    "format": {"duration": "10.5"},
}

FFMPEG_STDERR_H264 = """
Input #0, mov,mp4,m4a, from 'a.mov':
  Duration: 00:01:23.45, start: 0.000000, bitrate: 5000 kb/s
  Stream #0:0(und): Video: h264 (High), yuv420p, 1920x1080, 25 fps, 25 tbr
  Stream #0:1(und): Audio: aac (LC), 48000 Hz, stereo
"""

FFMPEG_STDERR_HEVC_TBR = """
Input #0, mov, from 'b.mov':
  Duration: 00:00:10.00, start: 0.000000
  Stream #0:0(und): Video: hevc (Main 10) (hvc1), yuv420p10le, 3840x2160, 30 tbr
"""


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_get_ffmpeg_path_imageio(monkeypatch):
    import imageio_ffmpeg

    monkeypatch.setattr(
        imageio_ffmpeg, "get_ffmpeg_exe", lambda: "C:/tools/ffmpeg.exe"
    )
    assert ffmpeg_tools.get_ffmpeg_path() == "C:/tools/ffmpeg.exe"


def test_get_ffmpeg_path_system_fallback(monkeypatch):
    import imageio_ffmpeg

    def _raise():
        raise RuntimeError("no bundled binary")

    monkeypatch.setattr(imageio_ffmpeg, "get_ffmpeg_exe", _raise)
    monkeypatch.setattr(
        ffmpeg_tools.shutil,
        "which",
        lambda name: "C:/system/ffmpeg.exe" if name == "ffmpeg" else None,
    )
    assert ffmpeg_tools.get_ffmpeg_path().endswith("ffmpeg.exe")


def test_get_ffmpeg_path_missing(monkeypatch):
    import imageio_ffmpeg

    monkeypatch.setattr(
        imageio_ffmpeg,
        "get_ffmpeg_exe",
        lambda: (_ for _ in ()).throw(RuntimeError("x")),
    )
    monkeypatch.setattr(ffmpeg_tools.shutil, "which", lambda name: None)
    with pytest.raises(ffmpeg_tools.FFmpegNotFoundError):
        ffmpeg_tools.get_ffmpeg_path()


def test_probe_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        ffmpeg_tools.probe_video(tmp_path / "nope.mov")


def test_probe_with_ffprobe(tmp_path, monkeypatch):
    video = tmp_path / "a.mov"
    video.write_bytes(b"fake")
    monkeypatch.setattr(ffmpeg_tools, "get_ffprobe_path", lambda: "ffprobe")

    def fake_run(cmd, **kwargs):
        return FakeCompleted(0, stdout=json.dumps(FFPROBE_JSON))

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)

    info = ffmpeg_tools.probe_video(video)
    assert info["video_codec"] == "hevc"
    assert info["audio_codec"] == "aac"
    assert (info["width"], info["height"]) == (1920, 1080)
    assert info["fps"] == 25.0
    assert info["duration"] == 10.5
    assert info["size_bytes"] == 4


def test_probe_ffprobe_failure_falls_back_to_ffmpeg(tmp_path, monkeypatch):
    video = tmp_path / "a.mov"
    video.write_bytes(b"fake")
    monkeypatch.setattr(ffmpeg_tools, "get_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(ffmpeg_tools, "get_ffmpeg_path", lambda: "ffmpeg")

    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeCompleted(1, stderr="boom")
        return FakeCompleted(1, stderr=FFMPEG_STDERR_H264)

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)

    info = ffmpeg_tools.probe_video(video)
    assert info["video_codec"] == "h264"
    assert info["duration"] == pytest.approx(83.45, abs=0.01)
    assert calls["n"] == 2


def test_probe_with_ffmpeg_stderr_hevc(tmp_path, monkeypatch):
    video = tmp_path / "b.mov"
    video.write_bytes(b"fake")
    monkeypatch.setattr(ffmpeg_tools, "get_ffprobe_path", lambda: None)
    monkeypatch.setattr(ffmpeg_tools, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        ffmpeg_tools.subprocess,
        "run",
        lambda cmd, **kw: FakeCompleted(1, stderr=FFMPEG_STDERR_HEVC_TBR),
    )

    info = ffmpeg_tools.probe_video(video)
    assert info["video_codec"] == "hevc"
    assert info["width"] == 3840 and info["height"] == 2160
    assert info["fps"] == 30.0
    assert info["duration"] == 10.0


def test_parse_rational_invalid():
    assert ffmpeg_tools._parse_rational("0/0") is None
    assert ffmpeg_tools._parse_rational("60/2") == 30.0
    assert ffmpeg_tools._parse_rational("23.976") == pytest.approx(23.976)


def test_extract_poster_fallback_first_frame(tmp_path, monkeypatch):
    video = tmp_path / "a.mov"
    video.write_bytes(b"fake")
    out = tmp_path / "thumb.jpg"

    monkeypatch.setattr(ffmpeg_tools, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        ffmpeg_tools, "probe_video", lambda p: {"duration": 100.0}
    )

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        seek = float(cmd[cmd.index("-ss") + 1])
        if seek > 1:
            return FakeCompleted(1, stderr=b"fail")
        out.write_bytes(b"jpeg-bytes")
        return FakeCompleted(0)

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)

    result = ffmpeg_tools.extract_poster(video, out)
    assert result.is_file()
    # 10s(100*0.1) 抽帧失败 -> 回退 0s 成功
    assert len(calls) == 2


def test_extract_poster_all_failures_raises(tmp_path, monkeypatch):
    video = tmp_path / "a.mov"
    video.write_bytes(b"fake")
    out = tmp_path / "thumb.jpg"

    monkeypatch.setattr(ffmpeg_tools, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        ffmpeg_tools, "probe_video", lambda p: {"duration": 100.0}
    )
    monkeypatch.setattr(
        ffmpeg_tools.subprocess,
        "run",
        lambda cmd, **kw: FakeCompleted(1, stderr=b"bad"),
    )

    with pytest.raises(RuntimeError):
        ffmpeg_tools.extract_poster(video, out)
