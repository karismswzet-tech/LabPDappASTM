"""Backend tests for review request:
- Rust D1748 analyze roundtrip (fix: _analyze_rust no longer shadowed by salt)
- Rust OCR label (new endpoints /api/rust/ocr/start, /api/rust/ocr/jobs/{id})
- Salt Spray still works after rename to _analyze_salt
- Validation: empty image_path -> 400 across modules
- Whole-app GET smoke (9 modules)
Cleans up any TEST_RUST_FIX records it creates.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
FIXTURE = "/app/tests/fixtures/rust_panel.jpg"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"}, timeout=15)
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def uploaded_image(session):
    with open(FIXTURE, "rb") as f:
        r = session.post(f"{API}/kht/upload", files={"file": ("rust_panel.jpg", f, "image/jpeg")}, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()["image_path"]


# --------------- Validation: empty image_path -> 400 ----------------
class TestEmptyImagePathValidation:
    @pytest.mark.parametrize("endpoint", [
        "/rust/analyze/start",
        "/rust/ocr/start",
    ])
    def test_empty_image_path_400(self, session, endpoint):
        payload = {"image_path": ""}
        if endpoint.endswith("/analyze/start"):
            payload.update({
                "sample_id": "TEST_RUST_FIX", "product": "x", "batch": "x", "operator": "x",
                "exposure_hours": 168, "temperature_c": 48.9, "humidity_pct": 95,
                "substrate": "CRS 1018", "remark": "", "method": "zone",
            })
        r = session.post(f"{API}{endpoint}", json=payload, timeout=15)
        assert r.status_code == 400, f"{endpoint} -> {r.status_code} {r.text}"


# --------------- Rust OCR label roundtrip ----------------
class TestRustOCR:
    def test_ocr_roundtrip(self, session, uploaded_image):
        r = session.post(f"{API}/rust/ocr/start", json={"image_path": uploaded_image}, timeout=15)
        assert r.status_code == 200, r.text
        job_id = r.json()["id"]
        result = None
        for _ in range(60):
            time.sleep(2)
            jr = session.get(f"{API}/rust/ocr/jobs/{job_id}", timeout=15).json()
            if jr["status"] == "done":
                result = jr["result"]
                break
            if jr["status"] == "error":
                pytest.fail(f"OCR job errored: {jr}")
        assert result is not None, "OCR did not finish in 120s"
        # shape
        for key in ["sample_id", "operator", "temperature_c", "duration_hours", "batch", "raw_text"]:
            assert key in result, f"missing OCR field: {key}"
        # fixture content: RP-0915 / Andi / 168 jam
        print(f"OCR result: {result}")
        assert "RP-0915" in (result.get("sample_id") or ""), f"expected sample_id RP-0915, got {result.get('sample_id')!r}"
        assert "andi" in (result.get("operator") or "").lower(), f"expected operator Andi, got {result.get('operator')!r}"
        assert str(result.get("duration_hours") or "").startswith("168"), f"expected duration 168, got {result.get('duration_hours')!r}"


# --------------- Rust analyze roundtrip (verifies _analyze_rust fix) ----------------
class TestRustAnalyzeRoundtrip:
    def test_analyze_zone_roundtrip_record_in_rust_not_salt(self, session, uploaded_image):
        payload = {
            "image_path": uploaded_image, "sample_id": "TEST_RUST_FIX", "product": "TEST product",
            "batch": "TEST_BATCH", "operator": "TEST_OP", "exposure_hours": 168, "temperature_c": 48.9,
            "humidity_pct": 95, "substrate": "CRS 1018", "remark": "pytest fix verification",
            "method": "zone",
        }
        r = session.post(f"{API}/rust/analyze/start", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        job_id = r.json()["id"]
        record_id = None
        for _ in range(60):
            time.sleep(2)
            jr = session.get(f"{API}/rust/analyze/jobs/{job_id}", timeout=15).json()
            if jr["status"] == "done":
                record_id = jr["record_id"]
                break
            if jr["status"] == "error":
                pytest.fail(f"analyze errored: {jr}")
        assert record_id, "analyze did not finish in 120s"

        try:
            # record must be in rust collection
            rec = session.get(f"{API}/rust/tests/{record_id}", timeout=15)
            assert rec.status_code == 200, f"GET /rust/tests/{record_id} -> {rec.status_code} (fix regression!)"
            data = rec.json()
            assert data["grade"] in "ABCDE"
            assert isinstance(data["rusted_box_count"], int)
            assert isinstance(data["grid_boxes"], list) and len(data["grid_boxes"]) == 100
            assert data["meta"]["sample_id"] == "TEST_RUST_FIX"

            # Should appear in /rust/tests list
            tests = session.get(f"{API}/rust/tests", timeout=15).json()
            assert any(t["id"] == record_id for t in tests)

            # Should NOT appear in /salt-spray/tests
            salt_tests = session.get(f"{API}/salt-spray/tests", timeout=15).json()
            assert not any(t["id"] == record_id for t in salt_tests), "Rust record leaked into salt collection!"
        finally:
            session.delete(f"{API}/rust/tests/{record_id}", timeout=15)


# --------------- Salt still works after rename ----------------
class TestSaltStillWorks:
    def test_salt_analyze_roundtrip(self, session, uploaded_image):
        payload = {
            "image_path": uploaded_image, "sample_id": "TEST_SALT_FIX", "product": "TEST",
            "batch": "TEST", "operator": "TEST", "exposure_hours": 24, "temperature_c": 35.0,
        }
        r = session.post(f"{API}/salt-spray/analyze/start", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        job_id = r.json()["id"]
        record_id = None
        for _ in range(60):
            time.sleep(2)
            jr = session.get(f"{API}/salt-spray/analyze/jobs/{job_id}", timeout=15).json()
            if jr["status"] == "done":
                record_id = jr["record_id"]
                break
            if jr["status"] == "error":
                pytest.fail(f"salt analyze errored: {jr}")
        assert record_id
        try:
            rec = session.get(f"{API}/salt-spray/tests/{record_id}", timeout=15)
            assert rec.status_code == 200
            assert rec.json()["meta"]["sample_id"] == "TEST_SALT_FIX"
        finally:
            session.delete(f"{API}/salt-spray/tests/{record_id}", timeout=15)


# --------------- Whole-app GET smoke across 9 modules ----------------
class TestWholeAppSmoke:
    @pytest.mark.parametrize("ep", [
        "/kht/dashboard", "/kht/tests", "/kht/trend", "/kht/reference-scale",
        "/copper/dashboard", "/copper/tests", "/copper/trend", "/copper/reference-scale",
        "/dka/dashboard", "/dka/tests", "/dka/trend", "/dka/reference-scale",
        "/rust/dashboard", "/rust/tests", "/rust/trend", "/rust/reference-scale",
        "/humidity/dashboard", "/humidity/tests", "/humidity/trend", "/humidity/reference-scale",
        "/diptest/dashboard", "/diptest/tests", "/diptest/trend", "/diptest/reference-scale",
        "/salt-spray/dashboard", "/salt-spray/tests", "/salt-spray/trend", "/salt-spray/reference-scale",
        "/htcbt/methods", "/htcbt/runs",
        "/dkacec/runs",
    ])
    def test_endpoint_200(self, session, ep):
        r = session.get(f"{API}{ep}", timeout=20)
        assert r.status_code == 200, f"{ep} -> {r.status_code} {r.text[:200]}"
