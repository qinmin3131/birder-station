"""FFmpeg/ffprobe 工具封装：视频元数据探测与海报帧抽取。

ffmpeg 可执行文件优先来自 imageio-ffmpeg（随 pip 依赖分发，无需用户
手动安装）；ffprobe 不随 imageio-ffmpeg 分发，若系统 PATH 中存在则
优先用于结构化 JSON 探测，否则回退解析 ``ffmpeg -i`` 的 stderr 输出。

所有 subprocess 调用均使用列表参数 + 超时，Windows 下中文路径安全。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 30
POSTER_TIMEOUT = 60
POSTER_WIDTH = 480


class FFmpegNotFoundError(RuntimeError):
    """ffmpeg 可执行文件不可用。"""


def get_ffmpeg_path() -> str:
    """返回 ffmpeg 可执行文件路径，优先 imageio-ffmpeg 捆绑二进制。"""
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path:
            return path
    except Exception as exc:  # pragma: no cover - 取决于运行环境
        logger.debug("imageio-ffmpeg unavailable: %s", exc)
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    raise FFmpegNotFoundError(
        "未找到 ffmpeg：请确认已安装 imageio-ffmpeg 或将 ffmpeg 加入 PATH"
    )


def get_ffprobe_path() -> Optional[str]:
    """返回系统 PATH 中的 ffprobe 路径；不存在时为 None。"""
    return shutil.which("ffprobe")


def probe_video(path: str | Path) -> dict:
    """探测视频元数据。

    Returns:
        dict: duration（秒）、width、height、fps、video_codec、
        audio_codec、size_bytes。
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"视频文件不存在: {file_path}")

    ffprobe = get_ffprobe_path()
    if ffprobe:
        try:
            return _probe_with_ffprobe(ffprobe, file_path)
        except Exception as exc:
            logger.warning("ffprobe 探测失败，回退 ffmpeg -i 解析: %s", exc)
    return _probe_with_ffmpeg(file_path)


def extract_poster(
    path: str | Path,
    out_path: str | Path,
    at_ratio: float = 0.1,
) -> Path:
    """抽取海报帧为 JPEG。

    先尝试 ``duration * at_ratio`` 处的帧，失败时回退首帧；均失败则
    抛出 RuntimeError。
    """
    file_path = Path(path)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = get_ffmpeg_path()

    duration: Optional[float] = None
    try:
        duration = probe_video(file_path).get("duration")
    except Exception as exc:
        logger.warning("抽帧前探测时长失败，按首帧处理: %s", exc)

    seek_time = 0.0
    if duration and duration > 0:
        seek_time = max(0.0, duration * at_ratio)

    if _run_poster(ffmpeg, file_path, target, seek_time):
        return target
    if seek_time > 0:
        logger.info("海报帧抽取失败(%.2fs)，回退首帧: %s", seek_time, file_path)
        if _run_poster(ffmpeg, file_path, target, 0.0):
            return target
    raise RuntimeError(f"海报帧抽取失败: {file_path}")


# --------------------------------------------------------------------------- #
# 内部实现
# --------------------------------------------------------------------------- #

def _empty_info(path: Path) -> dict:
    return {
        "duration": None,
        "width": None,
        "height": None,
        "fps": None,
        "video_codec": None,
        "audio_codec": None,
        "size_bytes": path.stat().st_size if path.exists() else None,
    }


def _probe_with_ffprobe(ffprobe: str, path: Path) -> dict:
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return _parse_ffprobe_json(json.loads(result.stdout), path)


def _parse_ffprobe_json(data: dict, path: Path) -> dict:
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    info = _empty_info(path)
    if video:
        info["width"] = _to_int(video.get("width"))
        info["height"] = _to_int(video.get("height"))
        info["video_codec"] = video.get("codec_name")
        frame_rate = video.get("avg_frame_rate")
        if frame_rate in (None, "0/0"):
            frame_rate = video.get("r_frame_rate")
        info["fps"] = _parse_rational(frame_rate)
    if audio:
        info["audio_codec"] = audio.get("codec_name")

    duration = fmt.get("duration")
    if not duration and video:
        duration = video.get("duration")
    info["duration"] = _to_float(duration)
    return info


def _probe_with_ffmpeg(path: Path) -> dict:
    ffmpeg = get_ffmpeg_path()
    # ffmpeg -i 不给出输出文件时以非零码退出，信息写在 stderr。
    cmd = [ffmpeg, "-hide_banner", "-i", str(path)]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT,
        encoding="utf-8",
        errors="replace",
    )
    return _parse_ffmpeg_stderr(result.stderr or "", path)


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(
    r"Video:\s*([a-zA-Z0-9_]+).*?,\s*(\d{2,5})x(\d{2,5})"
    r"(?:.*?([\d.]+)\s*(?:fps|tbr))?"
)
_AUDIO_RE = re.compile(r"Audio:\s*([a-zA-Z0-9_]+)")


def _parse_ffmpeg_stderr(stderr: str, path: Path) -> dict:
    info = _empty_info(path)

    duration_match = _DURATION_RE.search(stderr)
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        info["duration"] = (
            int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        )

    video_match = _VIDEO_RE.search(stderr)
    if video_match:
        codec, width, height, fps = video_match.groups()
        info["video_codec"] = codec
        info["width"] = _to_int(width)
        info["height"] = _to_int(height)
        info["fps"] = _to_float(fps)

    audio_match = _AUDIO_RE.search(stderr)
    if audio_match:
        info["audio_codec"] = audio_match.group(1)

    return info


def _run_poster(
    ffmpeg: str,
    path: Path,
    target: Path,
    seek_time: float,
) -> bool:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-ss", f"{seek_time:.3f}",
        "-i", str(path),
        "-frames:v", "1",
        "-vf", f"scale={POSTER_WIDTH}:-2",
        "-q:v", "3",
        "-y", str(target),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=POSTER_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("海报帧抽取超时: %s", path)
        return False
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace")[:300]
        logger.warning("海报帧抽取失败: %s %s", path, detail)
        return False
    return target.is_file() and target.stat().st_size > 0


def _to_int(value) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_rational(value) -> Optional[float]:
    if not value or "/" not in value:
        return _to_float(value)
    numerator, denominator = value.split("/", 1)
    denominator_f = _to_float(denominator)
    numerator_f = _to_float(numerator)
    if not denominator_f or numerator_f is None:
        return None
    return numerator_f / denominator_f
