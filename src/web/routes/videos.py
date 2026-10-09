"""视频管理 API 路由。

T4: 流式播放（HTTP Range）与缩略图访问。
T5 将在此追加浏览/详情与时间线标记 CRUD 端点。
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.db.models import VideoMarker
from src.db.repository import VideoRepository
from src.web.path_helpers import (
    get_thumbnail_placeholder_response,
    get_video_file_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])

# 由 app 启动时注入的 SQLAlchemy session 工厂
_session_factory = None


def init_video_routes(session_factory) -> None:
    """Bind the session factory used by all video routes."""
    global _session_factory
    _session_factory = session_factory


def _require_factory():
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Video routes not initialized")
    return _session_factory


@router.get("/{video_id}/stream")
def stream_video(video_id: int):
    """以支持 Range 的方式返回视频文件，供浏览器播放器拖动进度。"""
    session = _require_factory()()
    try:
        video = VideoRepository(session).get_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        return get_video_file_response(video.file_path)
    finally:
        session.close()


@router.get("/{video_id}/thumbnail")
def video_thumbnail(video_id: int):
    """返回视频海报缩略图；缺失时返回内联占位图。"""
    session = _require_factory()()
    try:
        video = VideoRepository(session).get_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        thumb = video.thumbnail_path
        if thumb and Path(thumb).is_file():
            from fastapi.responses import FileResponse

            return FileResponse(thumb, media_type="image/jpeg")
        return get_thumbnail_placeholder_response()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# T5: 浏览 / 详情 / 更新 / 时间线标记 CRUD
# ---------------------------------------------------------------------------

MARKER_CATEGORIES = ("可用", "采访", "B-roll", "弃用")


def serialize_marker(marker: VideoMarker) -> dict:
    return {
        "id": marker.id,
        "video_id": marker.video_id,
        "kind": marker.kind,
        "time": marker.time,
        "in_time": marker.in_time,
        "out_time": marker.out_time,
        "value": marker.value,
        "category": marker.category,
        "completed": bool(marker.completed),
    }


def serialize_video(video, markers: Optional[list] = None) -> dict:
    data = {
        "id": video.id,
        "filename": video.filename,
        "file_path": video.file_path,
        "duration": video.duration,
        "width": video.width,
        "height": video.height,
        "fps": video.fps,
        "video_codec": video.video_codec,
        "audio_codec": video.audio_codec,
        "captured_at": (
            video.captured_at.isoformat() if video.captured_at else None
        ),
        "captured_date": video.captured_date,
        "location_tag": video.location_tag,
        "location_level1": video.location_level1,
        "location_level2": video.location_level2,
        "location_level3": video.location_level3,
        "note": video.note,
        "tags": video.tags or [],
        "probe_failed": bool(video.probe_failed),
        "outing_id": video.outing_id,
        "thumbnail_url": f"/api/videos/{video.id}/thumbnail",
        "stream_url": f"/api/videos/{video.id}/stream",
    }
    if markers is not None:
        data["markers"] = [serialize_marker(m) for m in markers]
    return data


def _validate_marker_fields(
    kind: str,
    time: Optional[float],
    in_time: Optional[float],
    out_time: Optional[float],
    duration: Optional[float],
    category: Optional[str],
) -> None:
    """Raise HTTP 400 if marker fields are inconsistent."""
    if kind not in ("point", "segment"):
        raise HTTPException(status_code=400, detail="kind 必须为 point 或 segment")
    if category and category not in MARKER_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"category 必须为 { '/'.join(MARKER_CATEGORIES) }",
        )

    def _within(value):
        if value is None:
            return
        if value < 0:
            raise HTTPException(status_code=400, detail="时间不能为负")
        if duration is not None and value > duration:
            raise HTTPException(
                status_code=400, detail="时间超出视频时长"
            )

    if kind == "point":
        if time is None:
            raise HTTPException(status_code=400, detail="point 标记必须提供 time")
        _within(time)
    else:
        if in_time is None or out_time is None:
            raise HTTPException(
                status_code=400, detail="segment 标记必须提供 in_time 和 out_time"
            )
        _within(in_time)
        _within(out_time)
        if in_time >= out_time:
            raise HTTPException(
                status_code=400, detail="入点必须早于出点"
            )


@router.get("")
def list_videos(
    outing_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location_level1: Optional[str] = None,
    location_level2: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """多条件查询视频列表，按拍摄时间倒序。"""
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        filter_kwargs = dict(
            outing_id=outing_id,
            date_from=date_from,
            date_to=date_to,
            location_level1=location_level1,
            location_level2=location_level2,
            tag=tag,
            q=q,
        )
        items = repo.list_videos(limit=limit + 1, offset=offset, **filter_kwargs)
        has_more = len(items) > limit
        total = repo.count_videos(**filter_kwargs)
        return {
            "items": [serialize_video(v) for v in items[:limit]],
            "has_more": has_more,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        session.close()


@router.get("/{video_id}")
def video_detail(video_id: int):
    """视频详情，含全部时间线标记。"""
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        video = repo.get_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        markers = repo.list_markers(video_id)
        return serialize_video(video, markers=markers)
    finally:
        session.close()


@router.put("/{video_id}")
def update_video(video_id: int, body: dict):
    """更新视频整体备注 note 与标签 tags。"""
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        video = repo.get_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")

        if "note" in body:
            note = body["note"]
            video.note = note if note is None or isinstance(note, str) else str(note)
        if "tags" in body:
            tags = body["tags"]
            if not isinstance(tags, list):
                raise HTTPException(status_code=400, detail="tags 必须为数组")
            video.tags = [str(tag) for tag in tags]

        session.commit()
        session.refresh(video)
        return serialize_video(video)
    finally:
        session.close()


@router.post("/{video_id}/markers")
def create_marker(video_id: int, body: dict):
    """新增时间点/片段标记。"""
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        video = repo.get_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")

        kind = body.get("kind")
        time = body.get("time")
        in_time = body.get("in_time")
        out_time = body.get("out_time")
        category = body.get("category")
        _validate_marker_fields(
            kind, time, in_time, out_time, video.duration, category
        )

        marker = VideoMarker(
            video_id=video_id,
            kind=kind,
            time=time,
            in_time=in_time,
            out_time=out_time,
            value=body.get("value"),
            category=category,
            completed=bool(body.get("completed", False)),
        )
        marker = repo.add_marker(marker)
        return serialize_marker(marker)
    finally:
        session.close()


@router.put("/markers/{marker_id}")
def update_marker(marker_id: int, body: dict):
    """更新标记字段（白名单），更新后重新校验一致性。"""
    allowed = {
        "time",
        "in_time",
        "out_time",
        "value",
        "category",
        "completed",
    }
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        marker = repo.get_marker(marker_id)
        if not marker:
            raise HTTPException(status_code=404, detail="标记不存在")

        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"不允许更新的字段: {sorted(unknown)}"
            )

        # 先在内存中修改并校验，通过后再一次性提交，避免非法状态落库
        for key, value in body.items():
            setattr(marker, key, value)

        video = repo.get_by_id(marker.video_id)
        _validate_marker_fields(
            marker.kind,
            marker.time,
            marker.in_time,
            marker.out_time,
            video.duration if video else None,
            marker.category,
        )
        session.commit()
        session.refresh(marker)
        return serialize_marker(marker)
    finally:
        session.close()


@router.delete("/markers/{marker_id}")
def delete_marker(marker_id: int):
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        marker = repo.get_marker(marker_id)
        if not marker:
            raise HTTPException(status_code=404, detail="标记不存在")
        repo.delete_marker(marker)
        return {"status": "deleted", "id": marker_id}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# T7: 时间线导出
# ---------------------------------------------------------------------------

def _do_export(clips, fmt: str, mode: str, fps: float):
    from src.core.video.timeline_export import export_timeline
    try:
        content = export_timeline(clips, fmt, mode, fps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Timeline export failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"导出失败: {exc}")
    return content


@router.post("/{video_id}/export")
def export_video_timeline(video_id: int, body: dict):
    """单视频级导出：mode(full|segments) × fmt(fcpxml|premiere|edl)。"""
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        video = repo.get_by_id(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="视频不存在")
        fmt = body.get("fmt", "fcpxml")
        mode = body.get("mode", "full")
        download = body.get("download", True)
        markers = repo.list_markers(video_id)
        fps = video.fps or 25.0

        from src.core.video.timeline_export import build_clips_from_video
        clips = build_clips_from_video(video, markers, mode)
        content = _do_export(clips, fmt, mode, fps)

        if download:
            from fastapi.responses import Response
            mime = {
                "fcpxml": "application/xml",
                "premiere": "application/xml",
                "edl": "text/plain",
            }[fmt]
            ext = {"fcpxml": ".fcpxml", "premiere": ".xml", "edl": ".edl"}[fmt]
            base = Path(video.filename).stem
            filename = f"{base}{ext}"
            return Response(
                content=content.encode("utf-8"),
                media_type=mime,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                },
            )
        return {"content": content}
    finally:
        session.close()


@router.post("/outing/{outing_id}/export")
def export_outing_timeline(outing_id: int, body: dict):
    """外拍级导出：含外拍内全部视频，按拍摄时间排序。"""
    session = _require_factory()()
    try:
        repo = VideoRepository(session)
        videos = repo.list_videos(outing_id=outing_id, limit=500)
        if not videos:
            raise HTTPException(status_code=404, detail="该外拍没有视频")
        fmt = body.get("fmt", "fcpxml")
        mode = body.get("mode", "full")
        download = body.get("download", True)

        fps = max(v.fps or 25.0 for v in videos) if videos else 25.0
        pairs = [(v, repo.list_markers(v.id)) for v in videos]
        from src.core.video.timeline_export import build_clips_from_videos
        clips = build_clips_from_videos(pairs, mode)
        content = _do_export(clips, fmt, mode, fps)

        if download:
            from fastapi.responses import Response
            mime = {
                "fcpxml": "application/xml",
                "premiere": "application/xml",
                "edl": "text/plain",
            }[fmt]
            ext = {"fcpxml": ".fcpxml", "premiere": ".xml", "edl": ".edl"}[fmt]
            filename = f"outing_{outing_id}{ext}"
            return Response(
                content=content.encode("utf-8"),
                media_type=mime,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"'
                },
            )
        return {"content": content}
    finally:
        session.close()
