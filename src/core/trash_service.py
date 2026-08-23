import logging
import os
from pathlib import Path
from typing import Callable, Optional, Sequence

import send2trash
from sqlalchemy.orm import Session

from src.db.models import Photo, PhotoGroup
from src.db.stats import refresh_species_for_photo
from src.web.path_helpers import resolve_original_path

logger = logging.getLogger(__name__)


class TrashService:
    """Move rejected (rating == -1) photos to the OS recycle bin and delete
    their database records.

    ``send_func`` and ``manager_factory`` are injectable for tests; production
    code uses the defaults (``send2trash.send2trash`` and no legacy-stats
    manager, which the web layer supplies explicitly).
    """

    def __init__(
        self,
        session: Session,
        source_dirs: Sequence[Path],
        processed_dir: Optional[Path] = None,
        send_func: Callable = send2trash.send2trash,
        manager_factory: Optional[Callable] = None,
    ):
        self.session = session
        self.source_dirs = list(source_dirs)
        self.processed_dir = processed_dir
        self._send = send_func
        self._manager_factory = manager_factory

    def _rejected_query(self, outing_id: int):
        query = self.session.query(Photo).filter(Photo.rating == -1)
        if outing_id:
            query = query.filter(Photo.outing_id == outing_id)
        return query

    def list_rejected(self, outing_id: int = 0) -> dict:
        photos = self._rejected_query(outing_id).all()
        total_bytes = 0
        for p in photos:
            original = resolve_original_path(p.original_path or p.file_path, self.source_dirs)
            if original:
                try:
                    total_bytes += os.path.getsize(original)
                except OSError:
                    pass
        return {
            "count": len(photos),
            "total_bytes": total_bytes,
            "sample_filenames": [p.filename for p in photos[:5]],
        }

    def empty(self, outing_id: int = 0) -> dict:
        photos = self._rejected_query(outing_id).all()
        moved = 0
        deleted = 0
        skipped = 0
        errors: list[dict] = []
        affected_species: set[str] = set()

        for photo in photos:
            try:
                was_moved = self._trash_files(photo)
            except Exception as e:
                logger.error(f"Failed to trash files for photo {photo.id}: {e}")
                errors.append({"photo_id": photo.id, "error": str(e)})
                continue
            if was_moved:
                moved += 1
            else:
                skipped += 1
            if photo.scientific_name:
                affected_species.add(photo.scientific_name)
            self._delete_record(photo)
            deleted += 1

        for name in affected_species:
            try:
                refresh_species_for_photo(self.session, name, self._manager_factory)
            except Exception as e:
                logger.error(f"Failed to refresh species stats for {name}: {e}")

        return {"moved": moved, "deleted": deleted, "skipped": skipped, "errors": errors}

    def _trash_files(self, photo: Photo) -> bool:
        """Send original + .xmp sidecar to the recycle bin.

        Returns True if the original file existed (and was sent).
        """
        original = resolve_original_path(photo.original_path or photo.file_path, self.source_dirs)
        if not original or not Path(original).exists():
            return False
        self._send(original)
        sidecar = Path(original).with_suffix(Path(original).suffix + ".xmp")
        if sidecar.exists():
            self._send(str(sidecar))
        return True

    def _delete_record(self, photo: Photo) -> None:
        """Remove the processed crop cache, then delete the DB record and fix
        up the owning PhotoGroup."""
        self._remove_processed_crop(photo)
        group = None
        if photo.group_id:
            group = self.session.query(PhotoGroup).filter(PhotoGroup.id == photo.group_id).first()
        self.session.delete(photo)
        self.session.flush()
        if group is not None:
            remaining = self.session.query(Photo).filter(Photo.group_id == group.id).all()
            if not remaining:
                self.session.delete(group)
            elif group.best_photo_id == photo.id:
                best = max(remaining, key=lambda x: (x.quality_score or 0, x.id))
                group.best_photo_id = best.id
        self.session.commit()

    def _remove_processed_crop(self, photo: Photo) -> None:
        """Delete the generated crop only when it lives inside processed_dir.

        The crop is a system-generated cache, so it is removed directly (not
        via the recycle bin). The processed_dir guard makes it impossible to
        delete the user's original file through this path.
        """
        if not photo.file_path or not self.processed_dir:
            return
        path = Path(photo.file_path)
        if not path.is_absolute():
            path = Path(self.processed_dir) / path
        try:
            resolved = path.resolve()
            if resolved.is_file() and Path(self.processed_dir).resolve() in resolved.parents:
                os.remove(resolved)
        except OSError as e:
            logger.warning(f"Failed to remove processed crop {path}: {e}")
