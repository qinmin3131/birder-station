import hashlib
import logging
from pathlib import Path
from typing import List, Set, Optional

import numpy as np
from PIL import Image

from src.db.models import Photo
from src.db.repository import PhotoRepository
from src.core.io.path_parser import PathParser

try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    rawpy = None
    RAWPY_AVAILABLE = False
    logging.warning("rawpy not installed; RAW decoding disabled")

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"}
RAW_FORMATS = {".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"}

logger = logging.getLogger(__name__)


class PhotoIndexer:
    def __init__(self, repo: PhotoRepository, supported_formats: Optional[Set[str]] = None):
        self.repo = repo
        self.supported_formats = supported_formats or SUPPORTED_FORMATS

    def _file_hash(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def index_folder(self, folder: Path, recursive: bool = True, location_info: Optional[dict] = None) -> List[Photo]:
        photos = []
        glob_pattern = "**/*" if recursive else "*"
        location_kwargs = self._build_location_kwargs(location_info)
        for path in folder.glob(glob_pattern):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self.supported_formats:
                continue
            try:
                file_hash = self._file_hash(path)
                existing = self.repo.get_by_hash(file_hash)
                if existing is not None:
                    logger.info(f"Skipping duplicate photo: {path} (hash {file_hash[:8]}...)")
                    continue
                photo = Photo(
                    file_path=str(path),
                    filename=path.name,
                    original_path=str(path),
                    file_hash=file_hash,
                    **location_kwargs,
                )
                photos.append(self.repo.add(photo))
            except Exception as e:
                logger.error(f"Failed to index {path}: {e}")
        return photos

    def index_folder_with_stats(self, folder: Path, recursive: bool = True, overwrite: bool = False, location_info: Optional[dict] = None, outing_id: Optional[int] = None) -> dict:
        indexed = 0
        skipped = 0
        errors = 0
        overwritten = 0
        reprocessed = 0
        photo_ids = []
        glob_pattern = "**/*" if recursive else "*"
        location_kwargs = self._build_location_kwargs(location_info)
        # 从文件夹名解析拍摄日期（如 20260101_北京_奥森 -> 20260101），
        # 保证观鸟记录按拍摄时间排序，而非导入时间
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

                # Overwrite mode: remove existing record with same path + filename
                if overwrite:
                    existing = self.repo.get_by_path_and_name(file_path, filename)
                    if existing:
                        logger.info(f"Overwriting existing photo record: {path}")
                        self.repo.delete(existing)
                        overwritten += 1

                existing = self.repo.get_by_hash(file_hash)
                if existing is not None:
                    skipped += 1
                    # 将已有照片归入当前外拍，保证观鸟记录与外拍记录一致
                    if outing_id and existing.outing_id != outing_id:
                        existing.outing_id = outing_id
                        self.repo.session.commit()
                    # 已有照片若无拍摄日期，用文件夹名日期补齐
                    if folder_date and not existing.captured_date:
                        existing.captured_date = folder_date
                        self.repo.session.commit()
                    # 未处理的照片（无 bird_bbox 且无鸟种信息）加入识别队列，
                    # 已处理的照片不覆盖；避免同一照片因多文件同 hash 重复加入
                    if not self._is_processed(existing) and existing.id not in photo_ids:
                        logger.info(f"Re-recognizing unprocessed photo: {path}")
                        photo_ids.append(existing.id)
                        reprocessed += 1
                    else:
                        logger.info(f"Skipping already-processed photo: {path}")
                    continue

                photo = Photo(
                    file_path=file_path,
                    filename=filename,
                    original_path=file_path,
                    file_hash=file_hash,
                    outing_id=outing_id,
                    captured_date=folder_date,
                    **location_kwargs,
                )
                photo = self.repo.add(photo)
                photo_ids.append(photo.id)
                indexed += 1
            except Exception as e:
                logger.error(f"Failed to index {path}: {e}")
                errors += 1
        return {"indexed": indexed, "skipped": skipped, "errors": errors, "overwritten": overwritten, "reprocessed": reprocessed, "photo_ids": photo_ids, "outing_id": outing_id}

    @staticmethod
    def _is_processed(photo: Photo) -> bool:
        """判断照片是否已处理：有鸟种信息或鸟框坐标即视为已处理，不再覆盖。"""
        return (
            photo.bird_bbox is not None
            or photo.primary_bird_cn is not None
            or photo.scientific_name is not None
        )

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


def decode_raw(path: Path) -> np.ndarray:
    if not RAWPY_AVAILABLE:
        raise RuntimeError("rawpy is not installed")
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess()
    return rgb


def load_image(path: Path) -> np.ndarray:
    ext = path.suffix.lower()
    if ext in RAW_FORMATS:
        return decode_raw(path)
    return np.array(Image.open(path))
