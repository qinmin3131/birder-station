from types import SimpleNamespace

from src.records.secrets import load_birdreport_token
from src.web.birdreport_settings_service import BirdReportSettingsService


class Client:
    def test_connection(self):
        return SimpleNamespace(connected=True, username="bird-user")


def test_status_never_returns_token(tmp_path):
    service = BirdReportSettingsService(tmp_path, lambda: Client())
    service.save("secret", test=False)
    payload = service.status()
    assert payload == {"configured": True, "connected": None, "username": None}
    assert "secret" not in str(payload)


def test_save_and_test_strips_token(tmp_path):
    service = BirdReportSettingsService(tmp_path, lambda: Client())
    payload = service.save(" secret ", test=True)
    assert load_birdreport_token(tmp_path) == "secret"
    assert payload["connected"] is True
    assert payload["username"] == "bird-user"


def test_clear_removes_token(tmp_path):
    service = BirdReportSettingsService(tmp_path, lambda: Client())
    service.save("secret", test=False)
    assert service.clear() == {"configured": False, "connected": None, "username": None}
