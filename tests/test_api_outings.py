import pytest
from src.web.app import app
from fastapi.testclient import TestClient

def test_list_outings():
    client = TestClient(app)
    response = client.get("/api/outings")
    assert response.status_code == 200
    data = response.json()
    assert "outings" in data
    assert isinstance(data["outings"], list)