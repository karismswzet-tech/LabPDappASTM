"""Tests for POST /api/copper/tests/{id}/rerate (AI re-rating after manual crop)."""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://rating-lab.preview.emergentagent.com").rstrip("/")

# Reuse pre-existing batch to keep AI cost low (iteration_15 note)
EXISTING_BATCH_ID = "CU-BATCH-20261008-356"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin123"}, timeout=20)
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def batch(client):
    r = client.get(f"{BASE_URL}/api/copper/batches/{EXISTING_BATCH_ID}", timeout=15)
    assert r.status_code == 200, r.text
    recs = r.json()
    assert len(recs) >= 3, "need batch with >=3 samples with bbox"
    for rec in recs:
        assert rec.get("bbox"), f"record {rec['id']} missing bbox"
    recs.sort(key=lambda x: x.get("sample_index") or 0)
    return recs


def test_rerate_unknown_id_returns_404(client):
    r = client.post(f"{BASE_URL}/api/copper/tests/does-not-exist-xyz/rerate", timeout=15)
    assert r.status_code == 404, r.text


def test_rerate_meaningful_dark_strip_becomes_darker_class(client, batch):
    """
    Meaningful AI check: take sample 1 (bright copper -> 1a) in CU-BATCH-20261008-356,
    manually re-crop it to sample 3's bbox (dark 4a strip region of the same photo),
    then rerate. Expected: classification severity goes UP (darker class) and all AI
    fields are refreshed/persisted. Restore state afterwards.
    """
    s1 = batch[0]  # sample_index=1, 1a
    s3 = batch[2]  # sample_index=3, 4a (dark strip)
    orig_bbox = list(s1["bbox"])
    orig_cls = s1["classification"]
    orig_severity = float(s1["severity"])

    try:
        # 1) force manual class to 1a to make the roundtrip measurable
        pr = client.put(
            f"{BASE_URL}/api/copper/tests/{s1['id']}",
            json={"classification": "1a"},
            timeout=20,
        )
        assert pr.status_code == 200, pr.text
        assert pr.json()["classification"] == "1a"

        # 2) move crop to sample 3's area (dark strip)
        cr = client.put(
            f"{BASE_URL}/api/copper/tests/{s1['id']}/crop",
            json={"bbox": list(s3["bbox"])},
            timeout=30,
        )
        assert cr.status_code == 200, cr.text
        before = cr.json()
        assert before["classification"] == "1a", "crop endpoint must not re-rate"

        # 3) rerate via AI
        rr = client.post(f"{BASE_URL}/api/copper/tests/{s1['id']}/rerate", timeout=120)
        assert rr.status_code == 200, rr.text
        after = rr.json()

        # structural assertions
        for f in [
            "classification", "class_label", "group", "color", "description",
            "severity", "status", "confidence", "ai_summary", "recommendation",
        ]:
            assert f in after, f"missing field in response: {f}"
        assert isinstance(after["confidence"], (int, float))
        assert 0 <= after["confidence"] <= 100
        assert after["ai_summary"], "ai_summary should be non-empty"

        # persistence
        g = client.get(f"{BASE_URL}/api/copper/tests/{s1['id']}", timeout=15).json()
        for k in ("classification", "class_label", "severity", "status", "confidence", "ai_summary"):
            assert g[k] == after[k], f"persistence mismatch on {k}"

        # meaningful: cropped onto dark 4a strip -> severity must be strictly higher than 1a (sev=1)
        assert float(after["severity"]) > orig_severity, (
            f"AI rerate did not darken sample after cropping on dark strip: "
            f"orig_sev={orig_severity}, new_cls={after['classification']}, new_sev={after['severity']}"
        )
    finally:
        # best-effort restore to original bbox + classification
        try:
            client.put(
                f"{BASE_URL}/api/copper/tests/{s1['id']}/crop",
                json={"bbox": orig_bbox},
                timeout=30,
            )
            client.put(
                f"{BASE_URL}/api/copper/tests/{s1['id']}",
                json={"classification": orig_cls},
                timeout=15,
            )
        except Exception:
            pass
