import hashlib
import logging
from pathlib import Path
from typing import List, Set, Optional

import numpy as np
from PIL import Image

from src.db.models import Photo
from src.db.repository import PhotoRepository

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

    def index_folder(self, folder: Path, recursive: bool = True) -> List[Photo]:
        photos = []
        glob_pattern = "**/*" if recursive else "*"
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
                )
                photos.append(self.repo.add(photo))
            except Exception as e:
                logger.error(f"Failed to index {path}: {e}")
        return photos

    def index_folder_with_stats(self, folder: Path, recursive: bool = True, overwrite: bool = False) -> dict:
        indexed = 0
        skipped = 0
        errors = 0
        overwritten = 0
        photo_ids = []
        glob_pattern = "**/*" if recursive else "*"
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
                    logger.info(f"Skipping duplicate photo: {path} (hash {file_hash[:8]}...)")
                    skipped += 1
                    continue

                photo = Photo(
                    file_path=file_path,
                    filename=filename,
                    original_path=file_path,
                    file_hash=file_hash,
                )
                photo = self.repo.add(photo)
                photo_ids.append(photo.id)
                indexed += 1
            except Exception as e:
                logger.error(f"Failed to index {path}: {e}")
                errors += 1
        return {"indexed": indexed, "skipped": skipped, "errors": errors, "overwritten": overwritten, "photo_ids": photo_ids}


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
