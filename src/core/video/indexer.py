"""视频素材索引：扫描、hash 去重、外拍归属。

仅做索引与归属，不读取视频内容、不调用识别服务；元数据探测与海报帧
抽取由后台导入流程在索引完成后执行。
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

from src.core.io.path_parser import PathParser
from src.db.models import Video
from src.db.repository import VideoRepository

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_FORMATS = {
    ".mov",
    ".mp4",
    ".m4v",
    ".avi",
    ".mkv",
    ".mts",
    ".m2ts",
    ".wmv",
    ".3gp",
}


class VideoIndexer:
    def __init__(
        self,
        repo: VideoRepository,
        supported_formats: Optional[Set[str]] = None,
    ):
        self.repo = repo
        self.supported_formats = supported_formats or SUPPORTED_VIDEO_FORMATS

    def _file_hash(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def index_folder_with_stats(
        self,
        folder: Path,
        recursive: bool = True,
        overwrite: bool = False,
        location_info: Optional[dict] = None,
        outing_id: Optional[int] = None,
    ) -> dict:
        indexed = 0
        skipped = 0
        errors = 0
        overwritten = 0
        video_ids: List[int] = []
        glob_pattern = "**/*" if recursive else "*"
        location_kwargs = self._build_location_kwargs(location_info)
        # 文件夹名日期优先（如 20261001_北京_奥森 -> 20261001）
        folder_date, _, _ = PathParser.parse_folder_name(folder.name)

        for path in folder.glob(glob_pattern):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.supported_formats:
                continue
            try:
                file_hash = self._file_hash(path)
                file_path = str(path)
                filename = path.name

                if overwrite:
                    existing_path = self.repo.get_by_path_and_name(
                        file_path, filename
                    )
                    if existing_path:
                        logger.info("Overwriting video record: %s", path)
                        self.repo.delete(existing_path)
                        overwritten += 1

                existing = self.repo.get_by_hash(file_hash)
                if existing is not None:
                    skipped += 1
                    changed = False
                    if outing_id and existing.outing_id != outing_id:
                        existing.outing_id = outing_id
                        changed = True
                    if folder_date and not existing.captured_date:
                        existing.captured_date = folder_date
                        changed = True
                    if changed:
                        self.repo.session.commit()
                    # 未成功探测过的视频加入后续探测队列；已探测的不重复处理
                    if existing.id not in video_ids and (
                        existing.probe_failed or not existing.duration
                    ):
                        video_ids.append(existing.id)
                    continue

                # 相机视频文件的修改时间通常即拍摄时间，用作精确时间排序
                captured_at = datetime.fromtimestamp(path.stat().st_mtime)
                video = Video(
                    file_path=file_path,
                    filename=filename,
                    original_path=file_path,
                    file_hash=file_hash,
                    outing_id=outing_id,
                    captured_date=folder_date,
                    captured_at=captured_at,
                    **location_kwargs,
                )
                video = self.repo.add(video)
                video_ids.append(video.id)
                indexed += 1
            except Exception as exc:
                logger.error("Failed to index video %s: %s", path, exc)
                errors += 1

        return {
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
            "overwritten": overwritten,
            "video_ids": video_ids,
            "outing_id": outing_id,
        }

    @staticmethod
    def _build_location_kwargs(location_info: Optional[dict]) -> dict:
        if not location_info:
            return {}
        return {
            "location_tag": location_info.get("location_tag"),
            "location_level1": location_info.get("location_level1"),
            "location_level2": location_info.get("location_level2"),
            "location_level3": location_info.get("location_level3"),
        }
