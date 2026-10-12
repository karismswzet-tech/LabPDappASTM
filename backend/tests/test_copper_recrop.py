"""Tests for PUT /api/copper/tests/{id}/crop (manual re-crop feature)."""
import os
import io
import time
import base64

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lpd-evaluator.preview.emergentagent.com").rstrip("/")
FIXTURE = "/app/tests/fixtures/copper_batch_4.jpg"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin123"}, timeout=20)
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def batch(client):
    # Upload fixture
    with open(FIXTURE, "rb") as f:
        up = client.post(f"{BASE_URL}/api/kht/upload", files={"file": ("copper.jpg", f, "image/jpeg")}, timeout=60)
    assert up.status_code == 200, up.text
    image_path = up.json()["image_path"]

    # Start batch analyze
    payload = {
        "image_path": image_path,
        "batch_id": f"TEST_RECROP_{int(time.time())}",
        "samples": [{"sample_id": f"CU-0{i}"} for i in range(1, 5)],
        "notes": "pytest recrop",
    }
    r = client.post(f"{BASE_URL}/api/copper/batch/analyze/start", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    batch_id = None
    for _ in range(90):
        time.sleep(3)
        st = client.get(f"{BASE_URL}/api/copper/batch/analyze/jobs/{job_id}", timeout=15).json()
        if st.get("status") == "done":
            batch_id = st["batch_id"]
            break
        if st.get("status") == "error":
            pytest.fail(f"AI batch error: {st.get('error')}")
    assert batch_id, "batch analyze timed out"
    records = client.get(f"{BASE_URL}/api/copper/batches/{batch_id}", timeout=15).json()
    assert len(records) >= 1, records
    yield {"batch_id": batch_id, "records": records}
    # cleanup
    client.delete(f"{BASE_URL}/api/copper/batches/{batch_id}", timeout=15)


def test_bbox_present_on_new_batch(batch):
    """New batches must persist bbox so manual crop editor opens on the AI box."""
    for rec in batch["records"]:
        assert "bbox" in rec, rec
        assert isinstance(rec["bbox"], list)
        assert len(rec["bbox"]) == 4


def test_recrop_persists_and_updates_crop_path(client, batch):
    rec = batch["records"][0]
    old_crop = rec.get("crop_path", "")
    new_bbox = [0.1, 0.1, 0.4, 0.6]
    r = client.put(f"{BASE_URL}/api/copper/tests/{rec['id']}/crop", json={"bbox": new_bbox}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bbox"] == new_bbox
    assert body["crop_path"] != old_crop
    assert body.get("edited") is True
    # GET verifies persistence
    g = client.get(f"{BASE_URL}/api/copper/tests/{rec['id']}", timeout=15).json()
    assert g["bbox"] == new_bbox
    assert g["crop_path"] == body["crop_path"]
    assert g.get("edited") is True


def test_recrop_crop_file_downloadable(client, batch):
    rec = batch["records"][1]
    r = client.put(f"{BASE_URL}/api/copper/tests/{rec['id']}/crop", json={"bbox": [0.2, 0.05, 0.3, 0.7]}, timeout=30)
    assert r.status_code == 200
    new_path = r.json()["crop_path"]
    # fetch file via /api/files
    f = client.get(f"{BASE_URL}/api/kht/files/{new_path}", timeout=20)
    assert f.status_code == 200
    assert len(f.content) > 500  # non-empty JPEG


def test_recrop_rejects_wrong_bbox_length(client, batch):
    rec = batch["records"][0]
    r = client.put(f"{BASE_URL}/api/copper/tests/{rec['id']}/crop", json={"bbox": [0.1, 0.1, 0.4]}, timeout=15)
    # pydantic may 422 for parse, or 400 from our explicit check (len != 4 only triggers if parse passed)
    assert r.status_code in (400, 422), r.text


def test_recrop_rejects_too_small_area(client, batch):
    rec = batch["records"][0]
    r = client.put(f"{BASE_URL}/api/copper/tests/{rec['id']}/crop", json={"bbox": [0.5, 0.5, 0.001, 0.001]}, timeout=15)
    assert r.status_code == 400, r.text


def test_recrop_unknown_id_returns_404(client):
    r = client.put(f"{BASE_URL}/api/copper/tests/does-not-exist-xyz/crop", json={"bbox": [0.1, 0.1, 0.4, 0.4]}, timeout=15)
    assert r.status_code == 404, r.text


def test_sample_id_edit_regression(client, batch):
    """Iteration 14 regression — PUT /copper/tests/{id} with sample_id maps to meta.sample_id."""
    rec = batch["records"][2]
    r = client.put(f"{BASE_URL}/api/copper/tests/{rec['id']}", json={"sample_id": "TEST_SID_REGR"}, timeout=15)
    assert r.status_code == 200, r.text
    g = client.get(f"{BASE_URL}/api/copper/tests/{rec['id']}", timeout=15).json()
    assert g["meta"]["sample_id"] == "TEST_SID_REGR"
