"""时间线导出：FCPXML 1.9 / Premiere xmeml v5 / CMX3600 EDL。

两种模式：
- full：完整素材按序上轨，保留时间点备注
- segments：仅精选片段（入/出点）按序上轨

默认落盘路径：与视频/外拍同名同目录，已存在时加时间戳后缀。
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


class Clip:
    """一条素材或片段的导出数据（已从 Video/VideoMarker 提取）。"""

    def __init__(
        self,
        file_path: str,
        filename: str,
        duration: float,
        markers: list,
        in_time: Optional[float] = None,
        out_time: Optional[float] = None,
        note: Optional[str] = None,
    ):
        self.file_path = file_path
        self.filename = filename
        self.duration = duration or 0.0
        self.markers = markers
        self.in_time = in_time
        self.out_time = out_time
        self.out_mode = out_time is not None
        self.note = note


def _fps_to_rateref(fps: float) -> str:
    """将帧率转为分数表示，如 29.97 -> 30000/1001s。"""
    if fps is None or fps <= 0:
        return "1/1s"
    common = {24: "24/1s", 25: "25/1s", 30: "30/1s", 50: "50/1s", 60: "60/1s"}
    if fps in common:
        return common[fps]
    if abs(fps - 23.976) < 0.01:
        return "24000/1001s"
    if abs(fps - 29.97) < 0.01:
        return "30000/1001s"
    if abs(fps - 59.94) < 0.01:
        return "60000/1001s"
    return f"{int(round(fps))}/1s"


def _tc(seconds: float, fps: float = 25.0) -> str:
    """秒 → HH:MM:SS:FF 时间码（NDF）。"""
    if seconds is None or seconds < 0:
        seconds = 0
    fps_int = max(1, int(round(fps)))
    total_frames = int(round(seconds * fps_int))
    hh = total_frames // (3600 * fps_int)
    mm = (total_frames % (3600 * fps_int)) // (60 * fps_int)
    ss = (total_frames % (60 * fps_int)) // fps_int
    ff = total_frames % fps_int
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _safe_id(prefix: str = "id") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# FCPXML 1.9
# ---------------------------------------------------------------------------

def export_fcpxml(clips: List[Clip], mode: str, fps: float = 25.0) -> str:
    """生成 FCPXML 1.9 单文件字符串。"""
    rateref = _fps_to_rateref(fps)
    root = ET.Element("fcpxml", {"version": "1.9"})
    resources = ET.SubElement(root, "resources")
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": "飞羽志导出"})

    timeline_duration = 0.0
    asset_clips = []

    for idx, clip in enumerate(clips):
        asset_id = f"asset-{idx + 1}"
        media_rep_src = f"file://{clip.file_path}"

        asset = ET.SubElement(
            resources, "asset",
            {"id": asset_id, "name": clip.filename, "hasVideo": "1"},
        )
        ET.SubElement(
            asset, "media-rep",
            {"kind": "original-media", "src": media_rep_src},
        )

        if mode == "segments":
            src_in = clip.in_time or 0
            src_out = clip.out_time or clip.duration
            clip_len = src_out - src_in
        else:
            src_in = 0
            src_out = clip.duration
            clip_len = clip.duration

        offset_ref = _fps_to_rateref(fps)
        ac = ET.SubElement(
            event, "asset-clip",
            {
                "name": clip.filename,
                "ref": asset_id,
                "offset": f"{timeline_duration:.3f}s",
                "start": f"{src_in:.3f}s",
                "duration": f"{clip_len:.3f}s",
                "tcFormat": "NDF",
            },
        )
        asset_clips.append(ac)

        # 时间点备注 → marker
        for marker in clip.markers:
            if marker.get("kind") != "point":
                continue
            m_time = marker.get("time", 0)
            if mode == "segments":
                adj = m_time - src_in
                if adj < 0 or adj > clip_len:
                    continue
                m_time = adj
            ET.SubElement(
                ac, "marker",
                {
                    "start": f"{m_time:.3f}s",
                    "duration": "0s",
                    "value": marker.get("value") or "",
                },
            )

        timeline_duration += clip_len

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )


# ---------------------------------------------------------------------------
# Premiere xmeml v5
# ---------------------------------------------------------------------------

def export_premiere_xml(clips: List[Clip], mode: str, fps: float = 25.0) -> str:
    """生成 Premiere xmeml v5 XML 字符串。"""
    fps_str = f"{fps:.2f}" if fps else "25.00"
    root = ET.Element("xmeml", {"version": "5"})
    sequence = ET.SubElement(root, "sequence")
    ET.SubElement(sequence, "name").text = "飞羽志导出"
    ET.SubElement(sequence, "duration").text = str(
        int(sum(c.duration for c in clips))
    )
    rate = ET.SubElement(sequence, "rate")
    ET.SubElement(rate, "timebase").text = str(int(round(fps)))

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")
    ET.SubElement(video, "format")
    track = ET.SubElement(video, "track")

    timeline_pos = 0.0
    for idx, clip in enumerate(clips):
        if mode == "segments":
            src_in = clip.in_time or 0
            src_out = clip.out_time or clip.duration
        else:
            src_in = 0
            src_out = clip.duration

        clipitem = ET.SubElement(track, "clipitem", {"id": f"clip-{idx + 1}"})
        ET.SubElement(clipitem, "name").text = clip.filename
        ET.SubElement(clipitem, "enabled").text = "true"
        ET.SubElement(clipitem, "duration").text = str(
            int(round(src_out - src_in))
        )
        ET.SubElement(clipitem, "start").text = str(int(round(timeline_pos)))
        ET.SubElement(
            clipitem, "end"
        ).text = str(int(round(timeline_pos + src_out - src_in)))
        ET.SubElement(clipitem, "in").text = str(int(round(src_in)))
        ET.SubElement(clipitem, "out").text = str(int(round(src_out)))

        file_elem = ET.SubElement(clipitem, "file", {"id": f"file-{idx + 1}"})
        ET.SubElement(file_elem, "name").text = clip.filename
        ET.SubElement(file_elem, "pathurl").text = f"file://{clip.file_path}"

        for marker in clip.markers:
            if marker.get("kind") != "point":
                continue
            m = ET.SubElement(clipitem, "marker")
            ET.SubElement(m, "name").text = marker.get("value") or ""
            ET.SubElement(m, "in").text = str(
                int(round(marker.get("time", 0)))
            )
            ET.SubElement(m, "out").text = str(
                int(round(marker.get("time", 0))) + 1
            )

        timeline_pos += src_out - src_in

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )


# ---------------------------------------------------------------------------
# CMX3600 EDL
# ---------------------------------------------------------------------------

def export_edl(clips: List[Clip], mode: str, fps: float = 25.0) -> str:
    """生成 CMX3600 EDL 字符串。"""
    lines = ["TITLE: 飞羽志导出", "FCM: NON-DROP FRAME"]
    edit_ordinal = 1
    timeline_pos = 0.0

    for clip in clips:
        if mode == "segments":
            src_in = clip.in_time or 0
            src_out = clip.out_time or clip.duration
        else:
            src_in = 0
            src_out = clip.duration

        clip_dur = src_out - src_in
        rec_in = timeline_pos
        rec_out = timeline_pos + clip_dur

        lines.append(
            f"{edit_ordinal:03d}  AX       V  C  "
            f"{_tc(src_in, fps)} { _tc(src_out, fps)} "
            f"{_tc(rec_in, fps)} { _tc(rec_out, fps)}"
        )
        lines.append(f"FROM CLIP NAME: {clip.filename}")
        lines.append(f"SOURCE FILE: {clip.file_path}")

        # 时间点备注 → COMMENT 行
        for marker in clip.markers:
            if marker.get("kind") != "point":
                continue
            val = marker.get("value") or ""
            m_time = marker.get("time", 0)
            if mode == "segments":
                adj = m_time - src_in
                if 0 <= adj <= clip_dur:
                    lines.append(f"COMMENT: {_tc(adj, fps)} {val}")
            else:
                lines.append(f"COMMENT: {_tc(m_time, fps)} {val}")

        edit_ordinal += 1
        timeline_pos = rec_out

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 落盘与 API 辅助
# ---------------------------------------------------------------------------

def default_export_path(
    target_name: str,
    fmt: str,
    directory: str,
) -> Path:
    """返回默认落盘路径，已存在时加时间戳后缀。"""
    ext = {"fcpxml": ".fcpxml", "premiere": ".xml", "edl": ".edl"}[fmt]
    base = Path(directory) / f"{target_name}{ext}"
    if base.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(directory) / f"{target_name}_{ts}{ext}"
    return base


def build_clips_from_video(video, markers: list, mode: str) -> List[Clip]:
    """从单个 Video 及其 markers 构建 Clip 列表。"""
    marker_data = [
        {"kind": m.kind, "time": m.time, "in_time": m.in_time,
         "out_time": m.out_time, "value": m.value, "category": m.category}
        for m in markers
    ]

    if mode == "segments":
        clips = []
        for m in markers:
            if m.kind != "segment":
                continue
            clips.append(Clip(
                file_path=video.file_path,
                filename=video.filename,
                duration=video.duration or 0,
                markers=[],
                in_time=m.in_time,
                out_time=m.out_time,
                note=m.value,
            ))
        return clips
    else:
        return [Clip(
            file_path=video.file_path,
            filename=video.filename,
            duration=video.duration or 0,
            markers=marker_data,
            note=video.note,
        )]


def build_clips_from_videos(videos_with_markers: list, mode: str) -> List[Clip]:
    """从多个 (video, markers) 元组构建 Clip 列表，按拍摄时间排序。"""
    clips = []
    for video, markers in videos_with_markers:
        clips.extend(build_clips_from_video(video, markers, mode))
    return clips


def export_timeline(
    clips: List[Clip],
    fmt: str,
    mode: str,
    fps: float = 25.0,
) -> str:
    """按格式与模式导出时间线，返回内容字符串。"""
    if mode == "segments" and not clips:
        raise ValueError("精选片段模式下没有任何标记片段，无法导出空时间线")
    if fmt == "fcpxml":
        return export_fcpxml(clips, mode, fps)
    elif fmt == "premiere":
        return export_premiere_xml(clips, mode, fps)
    elif fmt == "edl":
        return export_edl(clips, mode, fps)
    raise ValueError(f"不支持的导出格式: {fmt}")
