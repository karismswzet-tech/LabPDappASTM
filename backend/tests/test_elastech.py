"""Backend API tests for Elastech Production."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://webapp-astm2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MODULES = ["khtt", "copper-strip", "rating-dka"]


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def test_root(session):
    r = session.get(f"{API}/")
    assert r.status_code == 200
    assert "message" in r.json()


def test_get_modules(session):
    r = session.get(f"{API}/modules")
    assert r.status_code == 200
    data = r.json()
    for m in MODULES:
        assert m in data
        assert "parameters" in data[m]


@pytest.mark.parametrize("module", MODULES)
def test_get_module(session, module):
    r = session.get(f"{API}/modules/{module}")
    assert r.status_code == 200
    assert "parameters" in r.json()


def test_unknown_module(session):
    r = session.get(f"{API}/modules/nonexistent")
    assert r.status_code == 404


@pytest.mark.parametrize("module", MODULES)
def test_crud_flow(session, module):
    # Create
    payload = {
        "sample_code": f"TEST-{module}-001",
        "sample_name": "Test Sample",
        "product_type": "Diesel",
        "operator": "Tester",
        "test_date": "2026-01-15",
        "rating": "",
        "notes": "auto",
        "parameters": {"foo": "bar"},
    }
    r = session.post(f"{API}/{module}/samples", json=payload)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["sample_code"] == payload["sample_code"]
    assert created["module"] == module
    assert "id" in created
    sid = created["id"]

    # List
    r = session.get(f"{API}/{module}/samples")
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json())

    # Get one
    r = session.get(f"{API}/{module}/samples/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid

    # Delete
    r = session.delete(f"{API}/{module}/samples/{sid}")
    assert r.status_code == 200
    # Verify gone
    r = session.get(f"{API}/{module}/samples/{sid}")
    assert r.status_code == 404


def test_delete_missing(session):
    r = session.delete(f"{API}/khtt/samples/nonexistent-id")
    assert r.status_code == 404


def test_ai_analyze(session):
    # Create a sample
    payload = {
        "sample_code": "TEST-AI-001",
        "sample_name": "AI Test Sample",
        "product_type": "Diesel",
        "operator": "Tester",
        "test_date": "2026-01-15",
        "rating": "Good",
        "notes": "test",
        "parameters": {"appearance": "Clear", "flash_point": "65"},
    }
    r = session.post(f"{API}/khtt/samples", json=payload)
    assert r.status_code == 200
    sid = r.json()["id"]
    try:
        r = session.post(f"{API}/khtt/samples/{sid}/analyze", timeout=90)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ai_analysis")
        assert len(data["ai_analysis"]) > 20
    finally:
        session.delete(f"{API}/khtt/samples/{sid}")
