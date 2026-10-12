"""Backend tests for Salt Spray Kartu Pengamatan (observation cards).

Covers:
- POST /api/kht/upload (prepare photo)
- POST /api/salt-spray/observations/detect/start + poll jobs (real Gemini, ~1-3 min)
- POST /api/salt-spray/observations with validation (missing photo, != 4 plates, empty code)
- GET list returns only new-format cards
- GET single, PUT (updates + edited flag), DELETE (soft)
"""
import base64
import os
import time

import pytest
import requests

def _load_backend_url() -> str:
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL="):
                return ln.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _load_backend_url()
FIXTURE = "/app/tests/fixtures/saltspray_four_plates.jpg"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def uploaded_photo(client):
    with open(FIXTURE, "rb") as f:
        r = client.post(f"{BASE_URL}/api/kht/upload", files={"file": ("four.jpg", f, "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()["image_path"]


# ---------- Validation ----------
class TestObsValidation:
    def test_missing_photo(self, client):
        r = client.post(f"{BASE_URL}/api/salt-spray/observations", json={
            "seq": 99, "duration_label": "24 Jam", "plates": [{"code": f"T{i}"} for i in range(4)],
        })
        assert r.status_code == 400

    def test_wrong_plate_count(self, client, uploaded_photo):
        r = client.post(f"{BASE_URL}/api/salt-spray/observations", json={
            "seq": 99, "duration_label": "24 Jam", "photo_path": uploaded_photo,
            "plates": [{"code": "A"}, {"code": "B"}],
        })
        assert r.status_code == 400

    def test_empty_code(self, client, uploaded_photo):
        r = client.post(f"{BASE_URL}/api/salt-spray/observations", json={
            "seq": 99, "duration_label": "24 Jam", "photo_path": uploaded_photo,
            "plates": [{"code": "A"}, {"code": "B"}, {"code": "C"}, {"code": "   "}],
        })
        assert r.status_code == 400


# ---------- List returns only new-format cards ----------
class TestObsList:
    def test_list_new_format_only(self, client):
        r = client.get(f"{BASE_URL}/api/salt-spray/observations")
        assert r.status_code == 200
        cards = r.json()
        for c in cards:
            assert "plates" in c and len(c["plates"]) == 4
            for p in c["plates"]:
                assert len(p["grid_boxes"]) == 100
                assert p["grade"] in {"A", "B", "C", "D", "E"}


# ---------- Full detect job (real Gemini) ----------
class TestObsDetectJob:
    def test_detect_and_create_roundtrip(self, client, uploaded_photo):
        start = client.post(f"{BASE_URL}/api/salt-spray/observations/detect/start",
                            json={"photo_path": uploaded_photo})
        assert start.status_code == 200, start.text
        job = start.json()
        job_id = job["id"]

        # poll up to 4 minutes
        deadline = time.time() + 240
        last = None
        while time.time() < deadline:
            r = client.get(f"{BASE_URL}/api/salt-spray/observations/detect/jobs/{job_id}")
            assert r.status_code == 200
            last = r.json()
            if last["status"] in {"done", "error"}:
                break
            time.sleep(5)
        assert last and last["status"] == "done", f"job final: {last}"
        assert last["detection"] in {"ai", "fallback"}
        plates = last["plates"]
        assert len(plates) == 4
        for p in plates:
            assert "bbox" in p and len(p["bbox"]) == 4
            assert len(p["grid_boxes"]) == 100
            assert len(p["ai_grid_boxes"]) == 100
            assert 0 <= p["rusted_box_count"] <= 100
            assert p["grade"] in {"A", "B", "C", "D", "E"}
            # grade consistency with count
            n = p["rusted_box_count"]
            if n == 0: assert p["grade"] == "A"
            elif n <= 10: assert p["grade"] == "B"
            elif n <= 25: assert p["grade"] == "C"
            elif n <= 50: assert p["grade"] == "D"
            else: assert p["grade"] == "E"

        # Now create the card from job
        for i, p in enumerate(plates):
            p["code"] = f"TEST_SMP_{i+1}"
        payload = {
            "seq": 99, "duration_label": "48 Jam",
            "photo_path": uploaded_photo, "detection": last["detection"], "plates": plates,
        }
        c = client.post(f"{BASE_URL}/api/salt-spray/observations", json=payload)
        assert c.status_code == 200, c.text
        card = c.json()
        card_id = card["id"]
        try:
            # grid_boxes == ai_grid_boxes initially -> edited False
            assert all(p["edited"] is False for p in card["plates"])

            # GET verifies persistence
            g = client.get(f"{BASE_URL}/api/salt-spray/observations/{card_id}")
            assert g.status_code == 200
            assert g.json()["seq"] == 99
            assert [p["code"] for p in g.json()["plates"]] == [f"TEST_SMP_{i+1}" for i in range(4)]

            # PUT: toggle one box on plate 1 -> edited True and count+1 if was false
            plates2 = [dict(p) for p in card["plates"]]
            boxes = list(plates2[0]["grid_boxes"])
            idx = next((i for i, v in enumerate(boxes) if not v), 0)
            orig_count = plates2[0]["rusted_box_count"]
            boxes[idx] = True
            plates2[0]["grid_boxes"] = boxes
            u = client.put(f"{BASE_URL}/api/salt-spray/observations/{card_id}", json={
                "seq": 99, "duration_label": "48 Jam", "photo_path": uploaded_photo,
                "detection": card["detection"], "plates": plates2,
            })
            assert u.status_code == 200, u.text
            upd = u.json()
            assert upd["plates"][0]["rusted_box_count"] == orig_count + 1
            assert upd["plates"][0]["edited"] is True

            # DELETE soft
            d = client.delete(f"{BASE_URL}/api/salt-spray/observations/{card_id}")
            assert d.status_code == 200
            g2 = client.get(f"{BASE_URL}/api/salt-spray/observations/{card_id}")
            assert g2.status_code == 404
            # not visible in list
            all_cards = client.get(f"{BASE_URL}/api/salt-spray/observations").json()
            assert all(c["id"] != card_id for c in all_cards)
        finally:
            # best-effort cleanup
            try:
                client.delete(f"{BASE_URL}/api/salt-spray/observations/{card_id}")
            except Exception:
                pass
