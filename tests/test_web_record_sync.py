from types import SimpleNamespace
from pathlib import Path

from src.web.record_sync_service import serialize_draft, serialize_export


def test_serialize_draft_exposes_status_without_internal_paths():
    draft = SimpleNamespace(id=7, status="ready", report=SimpleNamespace(remote_id="R1"), outing_id=3, location_name="奥森", duplicate_warning=False, items=[])
    payload = serialize_draft(draft)
    assert payload["id"] == 7
    assert payload["remote_id"] == "R1"
    assert payload["items"] == []


def test_serialize_draft_includes_confirmation_fields():
    draft = SimpleNamespace(id=7, status="ready", report=SimpleNamespace(remote_id="R1"), outing_id=3, location_name="奥森", latitude=40.0, longitude=116.0, protocol="Traveling", start_time="08:17", duration_minutes=149, distance_km=2.5, observer_count=1, is_complete_checklist=True, suggestion_json={}, duplicate_warning=False, items=[])
    payload = serialize_draft(draft)
    assert payload["start_time"] == "08:17"
    assert payload["duration_minutes"] == 149
    assert payload["latitude"] == 40.0


def test_serialize_export_returns_safe_urls():
    result = SimpleNamespace(batch_id=9, duplicate_of_batch_id=None)
    assert serialize_export(result) == {"batch_id": 9, "download_url": "/api/ebird/exports/9", "import_url": "https://ebird.org/import/upload.form", "duplicate_of_batch_id": None}


def test_log_template_uses_directory_not_cards():
    html = Path("src/web/templates/log.html").read_text(encoding="utf-8")
    assert 'id="recordDirectory"' in html
    assert 'id="recordDetail"' in html
    assert "record-card" not in html
    assert 'id="syncModal"' in html
