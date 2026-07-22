import logging
from pathlib import Path
from typing import List, Set, Optional
from collections import Counter

from src.core.indexer import PhotoIndexer, SUPPORTED_FORMATS, RAW_FORMATS
from src.core.io.path_parser import PathParser
from src.db.repository import PhotoRepository


logger = logging.getLogger(__name__)


class ImportService:
    """Guided photo import workflow: scan, index, and run recognition pipeline."""

    def __init__(self, task_manager, config: dict):
        self.task_manager = task_manager
        self.config = config

    def _supported_formats(self) -> Set[str]:
        formats = self.config.get("paths", {}).get("supported_formats")
        if formats:
            return set(f.lower() for f in formats)
        return SUPPORTED_FORMATS

    def scan_folder(self, folder: str, recursive: bool = True) -> dict:
        """Scan a folder for importable photos and return summary statistics."""
        folder_path = Path(folder)
        if not folder_path.exists() or not folder_path.is_dir():
            raise ValueError("Folder does not exist or is not a directory")

        supported = self._supported_formats()
        raw_formats = {f for f in supported if f in RAW_FORMATS}
        jpeg_formats = {f for f in supported if f in {".jpg", ".jpeg"}}

        glob_pattern = "**/*" if recursive else "*"
        files = []
        for path in folder_path.glob(glob_pattern):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in supported:
                continue
            files.append(path)

        total_size = sum(p.stat().st_size for p in files)
        counts = Counter(p.suffix.lower() for p in files)

        # Attempt to parse location from the immediate folder name
        parser = PathParser(str(folder_path))
        sample_file = str(files[0]) if files else str(folder_path / "sample.jpg")
        parsed = parser.parse(sample_file)
        location = {
            "tag": parsed.get("location_tag"),
            "level1": parsed.get("location_level1"),
            "level2": parsed.get("location_level2"),
            "level3": parsed.get("location_level3"),
        }

        return {
            "folder": str(folder_path.resolve()),
            "recursive": recursive,
            "total_files": len(files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "raw_files": sum(counts[ext] for ext in raw_formats),
            "jpeg_files": sum(counts[ext] for ext in jpeg_formats),
            "extensions": dict(counts),
            "sample_files": [str(p) for p in files[:10]],
            "location": location,
        }

    def parse_location(self, folder: str) -> dict:
        """Parse location info from a folder path without scanning files."""
        folder_path = Path(folder)
        parser = PathParser(str(folder_path.parent))
        sample_file = str(folder_path / "sample.jpg")
        parsed = parser.parse(sample_file)
        return {
            "tag": parsed.get("location_tag"),
            "level1": parsed.get("location_level1"),
            "level2": parsed.get("location_level2"),
            "level3": parsed.get("location_level3"),
        }

    def start_import(self, folder: str, recursive: bool = True, run_recognition: bool = True, overwrite: bool = False, location_info: dict = None) -> dict:
        """Start the background import task."""
        if self.task_manager.is_running:
            return {"status": "error", "message": "Another task is already running"}

        folder_path = Path(folder)
        if not folder_path.exists() or not folder_path.is_dir():
            return {"status": "error", "message": "Folder does not exist or is not a directory"}

        self.task_manager.start_import(
            str(folder_path.resolve()),
            recursive=recursive,
            run_recognition=run_recognition,
            overwrite=overwrite,
            config=self.config,
            location_info=location_info,
        )
        return {"status": "success", "message": "Import started"}

    def get_status(self) -> dict:
        """Return current import/pipeline status."""
        return {
            "is_running": self.task_manager.is_running,
            "logs": self.task_manager.logs[-100:],
        }
