import hashlib
import json
from dataclasses import asdict
from datetime import datetime

from src.db.models import (
    BirdReportReport,
    EBirdDraftStatus,
    EBirdItemSource,
    EBirdSyncDraft,
    EBirdSyncItem,
    Photo,
)
from src.records.matching import derive_effort_from_photos


class RecordSyncError(Exception):
    pass


class RecordSyncService:
    ACTIVE_STATUSES = {
        EBirdDraftStatus.PENDING_MATCH.value,
        EBirdDraftStatus.PENDING_CONFIRMATION.value,
        EBirdDraftStatus.READY.value,
        EBirdDraftStatus.EXPORTED.value,
        EBirdDraftStatus.NEEDS_REVISION.value,
    }

    def __init__(self, session):
        self.session = session

    @staticmethod
    def _content(report):
        data = asdict(report)
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return data, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def upsert_reports(self, reports):
        stored = []
        for report in reports:
            data, content_hash = self._content(report)
            row = self.session.query(BirdReportReport).filter_by(remote_id=report.remote_id).one_or_none()
            if row is None:
                row = BirdReportReport(remote_id=report.remote_id, first_fetched_at=datetime.utcnow())
                self.session.add(row)
            elif row.content_hash and row.content_hash != content_hash:
                for draft in row.drafts:
                    if draft.status in self.ACTIVE_STATUSES:
                        draft.status = EBirdDraftStatus.NEEDS_REVISION.value
            row.observed_on = report.observed_on
            row.location_name = report.location_name
            row.latitude = report.latitude
            row.longitude = report.longitude
            row.species_json = [asdict(item) for item in report.species]
            row.raw_json = report.raw or {}
            row.summary_json = {"species_count": len(report.species)}
            row.content_hash = content_hash
            row.last_fetched_at = datetime.utcnow()
            stored.append(row)
        self.session.commit()
        return stored

    def bind_report(self, outing_id, remote_id):
        report = self.session.query(BirdReportReport).filter_by(remote_id=remote_id).one_or_none()
        if report is None:
            raise RecordSyncError("找不到观鸟中心报告")
        active = next((draft for draft in report.drafts if draft.status in self.ACTIVE_STATUSES), None)
        if active:
            return active
        uploaded_exists = any(draft.status == EBirdDraftStatus.UPLOADED.value for draft in report.drafts)
        draft = EBirdSyncDraft(
            report=report,
            outing_id=outing_id,
            status=EBirdDraftStatus.PENDING_CONFIRMATION.value,
            location_name=report.location_name,
            latitude=report.latitude,
            longitude=report.longitude,
            source_content_hash=report.content_hash,
            duplicate_warning=uploaded_exists,
        )
        for species in report.species_json or []:
            draft.items.append(EBirdSyncItem(
                source=EBirdItemSource.BIRDREPORT.value,
                birdreport_name=species.get("name"),
                scientific_name=species.get("scientific_name"),
                count_value=str(species.get("count") or "X"),
                included=True,
                mapping_status="mapped" if species.get("scientific_name") else "needs_confirmation",
            ))
        if outing_id is not None:
            photos = self.session.query(Photo).filter(Photo.outing_id == outing_id).all()
            remote_keys = {
                value for item in draft.items for value in (item.scientific_name, item.birdreport_name) if value
            }
            local_seen = set()
            for photo in photos:
                key = photo.scientific_name or photo.primary_bird_cn
                if not key or key in remote_keys or key in local_seen:
                    continue
                local_seen.add(key)
                draft.items.append(EBirdSyncItem(
                    source=EBirdItemSource.LOCAL_SUPPLEMENT.value,
                    local_name=photo.primary_bird_cn,
                    scientific_name=photo.scientific_name,
                    count_value="X",
                    included=False,
                    mapping_status="needs_confirmation",
                    evidence_json={"photo_id": photo.id},
                ))
            effort = derive_effort_from_photos(photos)
            draft.start_time = effort.start_time.strftime("%H:%M") if effort.start_time else None
            draft.duration_minutes = effort.duration_minutes
            draft.suggestion_json = {
                "photo_count": effort.source_photo_count,
                "warnings": list(effort.warnings),
                "errors": list(effort.errors),
                "split_recommended": effort.split_recommended,
            }
        self.session.add(draft)
        self.session.commit()
        return draft

    def get_draft(self, draft_id):
        draft = self.session.get(EBirdSyncDraft, draft_id)
        if draft is None:
            raise RecordSyncError("找不到同步草稿")
        return draft

    def update_draft(self, draft_id, patch):
        draft = self.get_draft(draft_id)
        allowed = {"location_name", "latitude", "longitude", "protocol", "start_time", "duration_minutes", "distance_km", "observer_count", "is_complete_checklist", "suggestion_json", "status"}
        for key, value in patch.items():
            if key not in allowed:
                raise RecordSyncError(f"不允许更新字段: {key}")
            setattr(draft, key, value)
        self.session.commit()
        return draft

    def mark_uploaded(self, draft_id, checklist_id=None):
        draft = self.get_draft(draft_id)
        draft.status = EBirdDraftStatus.UPLOADED.value
        draft.ebird_checklist_id = checklist_id
        self.session.commit()
        return draft
