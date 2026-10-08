from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EBirdDraftStatus
from src.records.birdreport_client import NormalizedReport, NormalizedSpecies
from src.records.sync_service import RecordSyncService


def make_service():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return RecordSyncService(sessionmaker(bind=engine)())


def report(count="2"):
    return NormalizedReport("R1", "20261007", "奥森", species=(NormalizedSpecies("喜鹊", "Pica pica", count),), raw={"id": "R1"})


def test_changed_remote_report_marks_draft_needs_revision():
    service = make_service()
    service.upsert_reports([report("2")])
    draft = service.bind_report(None, "R1")
    service.upsert_reports([report("3")])
    assert service.get_draft(draft.id).status == EBirdDraftStatus.NEEDS_REVISION.value


def test_only_one_active_draft_per_report():
    service = make_service()
    service.upsert_reports([report()])
    first = service.bind_report(None, "R1")
    second = service.bind_report(None, "R1")
    assert second.id == first.id


def test_uploaded_draft_is_copied_for_revision():
    service = make_service()
    service.upsert_reports([report()])
    original = service.bind_report(None, "R1")
    service.mark_uploaded(original.id, "S123")
    revised = service.bind_report(None, "R1")
    assert revised.id != original.id
    assert revised.duplicate_warning is True


def test_binding_populates_remote_species_items():
    service = make_service()
    service.upsert_reports([report("8")])
    draft = service.bind_report(None, "R1")
    assert draft.items[0].scientific_name == "Pica pica"
    assert draft.items[0].count_value == "8"
    assert draft.items[0].included is True
