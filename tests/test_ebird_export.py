import csv
import io
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, BirdReportReport, EBirdExportBatch, EBirdSyncDraft, EBirdSyncItem
from src.records.ebird_export import EBirdExportError, build_ebird_record_csv, export_draft, validate_draft


@pytest.fixture
def draft_and_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    report = BirdReportReport(remote_id="R1", observed_on="20261007", location_name="奥森", content_hash="source")
    draft = EBirdSyncDraft(report=report, status="ready", location_name="奥森北园", latitude=40.01, longitude=116.39, protocol="Traveling", start_time="08:17", duration_minutes=149, distance_km=2.5, observer_count=1, is_complete_checklist=True)
    draft.items.append(EBirdSyncItem(source="birdreport", birdreport_name="喜鹊", ebird_name="Eurasian Magpie", scientific_name="Pica pica", taxonomy_code="eurmag", count_value="2", included=True, mapping_status="mapped"))
    draft.items.append(EBirdSyncItem(source="local_supplement", birdreport_name="红胁蓝尾鸲", ebird_name="Red-flanked Bluetail", scientific_name="Tarsiger cyanurus", taxonomy_code="refblu", count_value="X", included=True, mapping_status="mapped"))
    session.add(draft)
    session.commit()
    return draft, session


def test_missing_required_effort_blocks_export(draft_and_session):
    draft, _ = draft_and_session
    draft.observer_count = None
    assert [(issue.field, issue.code) for issue in validate_draft(draft)] == [("observer_count", "required")]


def test_csv_is_headerless_utf8_and_keeps_x(draft_and_session):
    draft, _ = draft_and_session
    rows = list(csv.reader(io.StringIO(build_ebird_record_csv(draft).decode("utf-8"))))
    assert rows[0][0] == "Eurasian Magpie"
    assert rows[1][3] == "X"
    assert all("Common Name" not in row for row in rows)


def test_csv_quotes_location_punctuation(draft_and_session):
    draft, _ = draft_and_session
    draft.location_name = '奥森, 北园 "湿地"\n东侧'
    rows = list(csv.reader(io.StringIO(build_ebird_record_csv(draft).decode("utf-8"))))
    assert rows[0][5] == draft.location_name


def test_repeated_export_detects_duplicate_and_changed_content_versions(draft_and_session, tmp_path):
    draft, session = draft_and_session
    first = export_draft(session, draft.id, tmp_path)
    repeated = export_draft(session, draft.id, tmp_path)
    assert repeated.duplicate_of_batch_id == first.batch_id
    draft.location_name = "新地点"
    session.commit()
    changed = export_draft(session, draft.id, tmp_path)
    assert changed.batch_id != first.batch_id
    assert session.query(EBirdExportBatch).count() == 2


def test_write_failure_does_not_create_batch(draft_and_session, tmp_path):
    draft, session = draft_and_session
    target = tmp_path / "not-directory"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(EBirdExportError):
        export_draft(session, draft.id, target)
    assert session.query(EBirdExportBatch).count() == 0
