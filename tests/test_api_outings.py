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


def test_taxonomy_tree_with_outing_filter():
    client = TestClient(app)
    response = client.get("/api/taxonomy/tree?outing_id=1")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_taxonomy_tree_with_outing_zero():
    client = TestClient(app)
    response = client.get("/api/taxonomy/tree?outing_id=0")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_taxonomy_tree_without_outing():
    client = TestClient(app)
    response = client.get("/api/taxonomy/tree")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)