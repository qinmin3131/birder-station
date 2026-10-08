from types import SimpleNamespace
from pathlib import Path

from src.web.record_sync_service import serialize_draft, serialize_export


def test_serialize_draft_exposes_status_without_internal_paths():
    draft = SimpleNamespace(id=7, status="ready", report=SimpleNamespace(remote_id="R1"), outing_id=3, location_name="奥森", duplicate_warning=False, items=[])
    assert serialize_draft(draft) == {"id": 7, "status": "ready", "remote_id": "R1", "outing_id": 3, "location_name": "奥森", "duplicate_warning": False, "items": []}


def test_serialize_export_returns_safe_urls():
    result = SimpleNamespace(batch_id=9, duplicate_of_batch_id=None)
    assert serialize_export(result) == {"batch_id": 9, "download_url": "/api/ebird/exports/9", "import_url": "https://ebird.org/import/upload.form", "duplicate_of_batch_id": None}


def test_log_template_uses_directory_not_cards():
    html = Path("src/web/templates/log.html").read_text(encoding="utf-8")
    assert 'id="recordDirectory"' in html
    assert 'id="recordDetail"' in html
    assert "record-card" not in html
    assert 'id="syncModal"' in html
