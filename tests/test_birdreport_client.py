import json

import pytest
import requests

from src.records.birdreport_client import (
    BirdReportAuthError,
    BirdReportClient,
    BirdReportError,
)


class FakeResponse:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is ValueError:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def test_fetch_reports_normalizes_response_and_auth_header():
    session = FakeSession(FakeResponse(200, {"data": [{"id": "R1", "date": "2026-10-07", "place": "奥森", "species": []}]}))

    reports = BirdReportClient("https://api.birdreport.cn", lambda: " secret ", session).fetch_reports("20261001", "20261008")

    assert reports[0].remote_id == "R1"
    assert reports[0].observed_on == "20261007"
    assert session.calls[0][1]["headers"] == {"X-Auth-Token": "secret"}


@pytest.mark.parametrize("status", [401, 403])
def test_expired_token_raises_without_leaking_token(status):
    session = FakeSession(FakeResponse(status, {"message": "secret rejected"}))
    with pytest.raises(BirdReportAuthError) as exc:
        BirdReportClient("https://api.birdreport.cn", lambda: "secret", session).test_connection()
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize(
    ("token", "response", "error", "category"),
    [
        ("", None, None, "auth"),
        ("secret", FakeResponse(200, ValueError, "<html>bad</html>"), None, "invalid_response"),
        ("secret", FakeResponse(200, None, ""), None, "invalid_response"),
        ("secret", None, requests.Timeout("slow"), "network"),
        ("secret", FakeResponse(429, {"message": "slow down"}), None, "rate_limit"),
        ("secret", FakeResponse(200, {"data": [{"date": "2026-10-07"}]}), None, "invalid_response"),
    ],
)
def test_client_rejects_unusable_input_with_safe_domain_error(token, response, error, category):
    client = BirdReportClient("https://api.birdreport.cn", lambda: token, FakeSession(response, error))
    with pytest.raises(BirdReportError) as exc:
        client.fetch_reports("20261001", "20261008")
    assert exc.value.category == category
    assert "X-Auth-Token" not in str(exc.value)


def test_connection_returns_identity_when_available():
    session = FakeSession(FakeResponse(200, {"data": {"username": "bird-user"}}))
    result = BirdReportClient("https://api.birdreport.cn", lambda: "secret", session).test_connection()
    assert result.connected is True
    assert result.username == "bird-user"
