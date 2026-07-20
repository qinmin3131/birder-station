import hashlib
import logging
from pathlib import Path
from typing import List, Set, Optional
from src.db.models import Photo
from src.db.repository import PhotoRepository

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".nef", ".orf", ".cr2", ".cr3", ".arw", ".dng", ".rw2"}

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
