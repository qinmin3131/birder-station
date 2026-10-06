import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

import send2trash
from sqlalchemy.orm import Session

from src.db.models import Photo, PhotoGroup
from src.db.stats import refresh_species_for_photo
from src.web.path_helpers import resolve_original_path

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"


def _looks_like_access_denied(errors: list[dict]) -> bool:
    """Return True when any error message smells like WinError 5."""
    for err in errors:
        msg = str(err.get("error", ""))
        if "拒绝访问" in msg or "WinError 5" in msg or "Access is denied" in msg:
            return True
    return False


_TRASH_WORKER_SCRIPT = r"""
import sys
import send2trash
paths = [line.strip() for line in sys.stdin if line.strip()]
for p in paths:
    try:
        send2trash.send2trash(p)
    except Exception as exc:
        sys.stdout.write("FAIL::" + p + "::" + str(exc) + "\n")
sys.stdout.flush()
"""


def _batch_send_to_trash(
    paths: list[str],
    send_func: Callable[[str], None] = send2trash.send2trash,
) -> dict[str, Optional[str]]:
    """Send multiple paths to the recycle bin in one go.

    Returns a mapping ``{path: error_message}`` for every path that failed;
    successfully moved paths are absent from the result.

    On Windows the in-process ``send2trash`` (which calls ``SHFileOperationW``)
    is unreliable inside the uvicorn server process: the worker threads may be
    initialised as MTA, and the shell operation can fail with
    ``ERROR_ACCESS_DENIED`` or ``COPYENGINE_E_USER_CANCELLED``.  We therefore
    delegate to a fresh Python subprocess that imports ``send2trash`` and
    processes the batch; a new process always has a clean COM apartment and
    full shell access.  Paths are piped via stdin to stay well under the
    Windows command-line length limit.

    When a custom ``send_func`` is injected (e.g. in tests) it is invoked per
    file in-process instead.  On non-Windows platforms ``send_func`` is always
    called per file.
    """
    failures: dict[str, Optional[str]] = {}
    if not paths:
        return failures

    use_subprocess = _IS_WINDOWS and send_func is send2trash.send2trash
    if not use_subprocess:
        for p in paths:
            try:
                send_func(p)
            except Exception as exc:  # noqa: BLE001
                failures[p] = str(exc)
        return failures

    chunk_size = 200
    for start in range(0, len(paths), chunk_size):
        chunk = paths[start : start + chunk_size]
        failures.update(_subprocess_send_to_trash(chunk))
    return failures


def _subprocess_send_to_trash(paths: list[str]) -> dict[str, Optional[str]]:
    """Send a chunk of paths to the recycle bin via a fresh Python process."""
    failures: dict[str, Optional[str]] = {}
    input_data = "\n".join(paths) + "\n"
    result = subprocess.run(
        [sys.executable, "-c", _TRASH_WORKER_SCRIPT],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=600,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("FAIL::"):
            parts = line.split("::", 2)
            if len(parts) >= 3:
                failures[parts[1]] = parts[2]
            elif len(parts) == 2:
                failures[parts[1]] = "unknown error"
    if result.returncode != 0 and not failures:
        msg = (result.stderr or result.stdout).strip()
        for p in paths:
            failures[p] = msg or f"worker exited {result.returncode}"
    return failures


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

        # Phase 1: resolve every original + sidecar path and batch-send them
        # to the recycle bin.  Doing it in one subprocess call keeps the
        # operation fast even with hundreds of files.
        photo_paths: list[tuple[Photo, Optional[str], Optional[str]]] = []
        all_paths: list[str] = []
        for photo in photos:
            original, sidecar = self._resolve_paths(photo)
            photo_paths.append((photo, original, sidecar))
            if original:
                all_paths.append(original)
            if sidecar:
                all_paths.append(sidecar)

        failures = _batch_send_to_trash(all_paths, self._send)

        # Phase 2: delete DB records for photos whose files were moved (or
        # were already missing on disk).
        for photo, original, sidecar in photo_paths:
            if original is None:
                # Original was already gone (e.g. deleted outside the app);
                # still clean up the DB record.
                skipped += 1
                if photo.scientific_name:
                    affected_species.add(photo.scientific_name)
                self._delete_record(photo)
                deleted += 1
                continue
            orig_error = failures.get(original)
            if orig_error is not None:
                logger.error(f"Failed to trash {original}: {orig_error}")
                errors.append({"photo_id": photo.id, "error": orig_error})
                continue
            moved += 1
            if photo.scientific_name:
                affected_species.add(photo.scientific_name)
            self._delete_record(photo)
            deleted += 1

        for name in affected_species:
            try:
                refresh_species_for_photo(self.session, name, self._manager_factory)
            except Exception as e:
                logger.error(f"Failed to refresh species stats for {name}: {e}")

        result = {"moved": moved, "deleted": deleted, "skipped": skipped, "errors": errors}
        if errors and _looks_like_access_denied(errors):
            hint = (
                "回收站操作被拒绝（WinError 5）。如果服务器运行在 IDE/沙箱终端中，"
                "Windows shell API 可能受限。请改用普通命令行窗口（cmd/PowerShell）"
                "通过 start_server.bat 启动服务后重试。"
            )
            logger.warning(hint)
            result["hint"] = hint
        return result

    def _resolve_paths(self, photo: Photo) -> tuple[Optional[str], Optional[str]]:
        """Return ``(original_path, sidecar_path)`` for a photo.

        Each path is returned only when the file exists on disk; otherwise
        ``None``.  A ``None`` original means the photo has no locatable
        original (e.g. the file was already removed) and should be skipped.
        """
        original = resolve_original_path(photo.original_path or photo.file_path, self.source_dirs)
        if not original or not Path(original).exists():
            return None, None
        sidecar = Path(original).with_suffix(Path(original).suffix + ".xmp")
        sidecar_str = str(sidecar) if sidecar.exists() else None
        return original, sidecar_str

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
