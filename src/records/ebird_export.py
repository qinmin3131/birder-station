import csv
import hashlib
import io
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.db.models import EBirdDraftStatus, EBirdExportBatch, EBirdSyncDraft


EBIRD_RECORD_COLUMNS = (
    "Common Name", "Genus", "Species", "Number", "Species Comments",
    "Location Name", "Latitude", "Longitude", "Date", "Start Time",
    "State/Province", "Country", "Protocol", "Number of Observers",
    "Duration", "All Obs Reported", "Distance Traveled", "Area Covered",
)


class EBirdExportError(Exception):
    pass


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    code: str
    message: str = "必填字段缺失"


@dataclass(frozen=True)
class ExportResult:
    batch_id: int
    path: Path
    content_hash: str
    duplicate_of_batch_id: int | None = None


def validate_draft(draft) -> list[ValidationIssue]:
    issues = []
    required = ("location_name", "latitude", "longitude", "protocol", "start_time", "duration_minutes", "observer_count", "is_complete_checklist")
    for field in required:
        if getattr(draft, field, None) is None or getattr(draft, field, None) == "":
            issues.append(ValidationIssue(field, "required"))
    for item in draft.items:
        if item.included and item.mapping_status != "mapped":
            issues.append(ValidationIssue(f"items.{item.id}.mapping", "unresolved", "鸟种映射尚未确认"))
        if item.included and not (item.ebird_name or item.scientific_name):
            issues.append(ValidationIssue(f"items.{item.id}.name", "required", "缺少 eBird 鸟种名称"))
    if not any(item.included for item in draft.items):
        issues.append(ValidationIssue("items", "empty", "至少需要一个纳入导出的鸟种"))
    return issues


def build_ebird_record_csv(draft) -> bytes:
    issues = validate_draft(draft)
    if issues:
        raise EBirdExportError("同步草稿尚未通过校验")
    observed = datetime.strptime(draft.report.observed_on, "%Y%m%d").strftime("%m/%d/%Y")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for item in sorted((value for value in draft.items if value.included), key=lambda value: (value.taxonomy_code or "", value.scientific_name or "")):
        scientific_parts = (item.scientific_name or "").split(" ", 1)
        writer.writerow([
            item.ebird_name or item.birdreport_name or item.local_name or "",
            scientific_parts[0] if scientific_parts else "",
            scientific_parts[1] if len(scientific_parts) > 1 else "",
            item.count_value,
            "",
            draft.location_name,
            draft.latitude,
            draft.longitude,
            observed,
            draft.start_time,
            "",
            "CN",
            draft.protocol,
            draft.observer_count,
            draft.duration_minutes,
            "Y" if draft.is_complete_checklist else "N",
            draft.distance_km if draft.distance_km is not None else "",
            "",
        ])
    return buffer.getvalue().encode("utf-8")


def export_draft(session, draft_id: int, export_dir: Path) -> ExportResult:
    draft = session.get(EBirdSyncDraft, draft_id)
    if draft is None:
        raise EBirdExportError("找不到同步草稿")
    content = build_ebird_record_csv(draft)
    digest = hashlib.sha256(content).hexdigest()
    duplicate = next((batch for batch in draft.export_batches if batch.content_hash == digest), None)
    if duplicate:
        return ExportResult(duplicate.id, Path(duplicate.file_path), digest, duplicate.id)
    version = len(draft.export_batches) + 1
    filename = f"ebird-{draft.report.remote_id}-v{version}.csv"
    directory = Path(export_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        final_path = directory / filename
        temp_path = directory / f".{filename}.tmp"
        temp_path.write_bytes(content)
        os.replace(temp_path, final_path)
    except OSError as exc:
        session.rollback()
        raise EBirdExportError("无法写入 eBird 导出文件") from exc
    batch = EBirdExportBatch(draft=draft, version=version, filename=filename, file_path=str(final_path), content_hash=digest)
    draft.status = EBirdDraftStatus.EXPORTED.value
    session.add(batch)
    session.commit()
    return ExportResult(batch.id, final_path, digest)
