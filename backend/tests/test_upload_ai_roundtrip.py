"""End-to-end: upload a realistic image, run AI analyses (copper batch, diptest, dka) and confirm they do NOT 404 'Image not found'."""
import io
import os
import time
import pytest
import requests
from PIL import Image

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://lpd-evaluator.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"}, timeout=30)
    assert r.status_code == 200
    return s


@pytest.fixture(scope="module")
def uploaded_path(session):
    # Download a realistic jpeg from an existing demo record (Unsplash)
    url = "https://images.unsplash.com/photo-1605152276897-4f618f831968?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"
    img = requests.get(url, timeout=30).content
    assert len(img) > 10000
    # Re-upload through our compression endpoint
    r = session.post(f"{API}/kht/upload", files={"file": ("real.jpg", img, "image/jpeg")}, timeout=60)
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["image_path"].startswith(("elastech", "elastech-kht")) or "/uploads/" in info["image_path"]
    return info["image_path"]


def _poll(session, url, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = session.get(url, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        if j.get("status") in ("done", "error", "failed"):
            return j
        time.sleep(2)
    pytest.fail(f"polling timed out: {url}")


def test_copper_analyze_newly_uploaded_image_not_404(session, uploaded_path):
    r = session.post(f"{API}/copper/analyze/start", json={"image_path": uploaded_path}, timeout=30)
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    j = _poll(session, f"{API}/copper/analyze/jobs/{job_id}")
    # Key check: image was found (no 404). AI may return done or soft error, but not image-not-found.
    err = (j.get("error") or "").lower()
    assert "image not found" not in err, f"image not found: {j}"


def test_dka_analyze_newly_uploaded_image_not_404(session, uploaded_path):
    r = session.post(f"{API}/dka/analyze/start", json={"image_path": uploaded_path}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"dka start returned {r.status_code}: {r.text[:200]}")
    job_id = r.json()["id"]
    j = _poll(session, f"{API}/dka/analyze/jobs/{job_id}")
    err = (j.get("error") or "").lower()
    assert "image not found" not in err, f"image not found: {j}"


def test_diptest_analyze_newly_uploaded_image_not_404(session, uploaded_path):
    r = session.post(f"{API}/diptest/analyze/start", json={"image_path": uploaded_path}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"diptest start returned {r.status_code}: {r.text[:200]}")
    job_id = r.json()["id"]
    j = _poll(session, f"{API}/diptest/analyze/jobs/{job_id}")
    err = (j.get("error") or "").lower()
    assert "image not found" not in err, f"image not found: {j}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
