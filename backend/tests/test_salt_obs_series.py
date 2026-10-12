"""Backend tests for Salt Spray — History Pengamatan (observation series).

Flow (preserves user's real data):
  1. Snapshot header + list of real cards
  2. Archive real series -> verify response, archived cards guard (PUT=409),
     header reset (conditions kept, operator cleared), active list empty.
  3. Create a temp card (clone plates from real card) with partial grid_boxes
     covering only some samples -> try force=false (409), then force=true.
  4. Delete the temp TEST series.
  5. complete with no active cards -> 400.
  6. Reopen the REAL series -> cards back, header back exactly.
"""
import os
import copy
import pytest
import requests


def _url() -> str:
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        with open("/app/frontend/.env") as f:
            for ln in f:
                if ln.startswith("REACT_APP_BACKEND_URL="):
                    v = ln.split("=", 1)[1].strip()
                    break
    assert v, "REACT_APP_BACKEND_URL not set"
    return v.rstrip("/")


BASE = _url()


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


def test_full_series_lifecycle(client):
    # ---------- 1) snapshot ----------
    hdr0 = client.get(f"{BASE}/api/salt-spray/observation-header").json()
    cards0 = client.get(f"{BASE}/api/salt-spray/observations").json()
    assert len(cards0) >= 1, "No active cards to test with"
    orig_ids = [c["id"] for c in cards0]
    print(f"snapshot: {len(cards0)} active cards; operator={hdr0.get('operator')!r}")

    # pre-flight: active-summary
    summ = client.get(f"{BASE}/api/salt-spray/observation-series/active-summary").json()
    assert summ["card_count"] == len(cards0)
    assert isinstance(summ["samples"], list) and summ["samples"]

    real_series_id = None
    temp_card_id = None
    temp_series_id = None
    try:
        # ---------- 2) complete real series (all 100%) ----------
        r = client.post(f"{BASE}/api/salt-spray/observation-series/complete",
                        json={"force": False, "note": "TEST archive real"})
        assert r.status_code == 200, r.text
        series = r.json()
        real_series_id = series["id"]
        assert series["card_count"] == len(cards0)
        assert series["all_reached"] is True
        assert series["stopped_early"] is False
        assert series["duration_hours"] is not None
        assert isinstance(series["number"], int) and series["number"] >= 1
        assert series["cover_photo_path"], "cover photo should be set"
        assert len(series["samples"]) == len(summ["samples"])
        # header snapshot preserved on series
        assert series["header"]["operator"] == hdr0.get("operator")

        # 2a) PUT on archived card -> 409
        archived_card_id = orig_ids[0]
        g = client.get(f"{BASE}/api/salt-spray/observations/{archived_card_id}")
        assert g.status_code == 200  # still fetchable (not deleted, just archived)
        card_doc = g.json()
        put = client.put(f"{BASE}/api/salt-spray/observations/{archived_card_id}", json={
            "seq": card_doc["seq"], "duration_label": card_doc["duration_label"],
            "photo_path": card_doc["photo_path"], "detection": card_doc.get("detection", ""),
            "plates": card_doc["plates"],
        })
        assert put.status_code == 409, f"expected 409, got {put.status_code}: {put.text}"

        # 2b) active list now empty
        acts = client.get(f"{BASE}/api/salt-spray/observations").json()
        assert acts == [], f"expected active list empty, got {len(acts)}"
        s2 = client.get(f"{BASE}/api/salt-spray/observation-series/active-summary").json()
        assert s2["card_count"] == 0

        # 2c) header reset: operator cleared, condition fields kept
        hdr1 = client.get(f"{BASE}/api/salt-spray/observation-header").json()
        for k in ("specimen_position", "pressure", "water", "chamber_temp_min",
                  "chamber_temp_max", "saturated_air_temp", "ph"):
            assert hdr1.get(k) == hdr0.get(k), f"condition field {k} must be preserved"
        for k in ("operator", "start_time", "start_date", "plate_grinding", "plate_grinding_note"):
            assert not hdr1.get(k), f"field {k} should be cleared, got {hdr1.get(k)!r}"

        # ---------- 3) temp card: partial grid_boxes to simulate 'not all 100%' ----------
        detail = client.get(f"{BASE}/api/salt-spray/observation-series/{real_series_id}").json()
        tpl = detail["cards"][0]
        temp_plates = []
        for i, p in enumerate(tpl["plates"]):
            np_ = copy.deepcopy(p)
            np_["code"] = f"TEST_SMP_{i+1}"
            # First plate reaches 100%, others only ~30%
            if i == 0:
                np_["grid_boxes"] = [True] * 100
            else:
                boxes = [False] * 100
                for j in range(30):
                    boxes[j] = True
                np_["grid_boxes"] = boxes
            temp_plates.append(np_)
        temp_payload = {
            "seq": 1, "duration_label": "0 Jam",
            "photo_path": tpl["photo_path"], "detection": tpl.get("detection", ""),
            "plates": temp_plates,
        }
        c = client.post(f"{BASE}/api/salt-spray/observations", json=temp_payload)
        assert c.status_code == 200, c.text
        temp_card_id = c.json()["id"]

        # 3a) force=false -> 409
        r409 = client.post(f"{BASE}/api/salt-spray/observation-series/complete",
                           json={"force": False, "note": ""})
        assert r409.status_code == 409
        assert "TEST_SMP_2" in r409.text  # pending samples listed

        # 3b) force=true -> ok, stopped_early=True
        r2 = client.post(f"{BASE}/api/salt-spray/observation-series/complete",
                        json={"force": True, "note": "TEST stop early"})
        assert r2.status_code == 200, r2.text
        s2 = r2.json()
        temp_series_id = s2["id"]
        assert s2["stopped_early"] is True
        assert s2["all_reached"] is False
        assert s2["duration_hours"] is None
        assert s2["card_count"] == 1
        # number should NOT increment past real (temp series are archived; reopened=False here).
        # Just assert it is an int > 0.
        assert isinstance(s2["number"], int) and s2["number"] >= 1

        # list endpoint shows both
        lst = client.get(f"{BASE}/api/salt-spray/observation-series").json()
        ids = {s["id"] for s in lst}
        assert real_series_id in ids and temp_series_id in ids

        # ---------- 4) delete temp series ----------
        d = client.delete(f"{BASE}/api/salt-spray/observation-series/{temp_series_id}")
        assert d.status_code == 200
        g_del = client.get(f"{BASE}/api/salt-spray/observation-series/{temp_series_id}")
        assert g_del.status_code == 404
        # soft-deleted cards gone from active list too (they were already archived)
        temp_series_id = None  # mark cleaned

        # ---------- 5) complete with no active cards -> 400 ----------
        acts_now = client.get(f"{BASE}/api/salt-spray/observations").json()
        assert acts_now == []
        r400 = client.post(f"{BASE}/api/salt-spray/observation-series/complete",
                           json={"force": True, "note": ""})
        assert r400.status_code == 400

        # ---------- 6) reopen real series ----------
        ro = client.post(f"{BASE}/api/salt-spray/observation-series/{real_series_id}/reopen")
        assert ro.status_code == 200, ro.text
        real_series_id = None  # reopen soft-deletes the series

        # final state must match snapshot
        acts_final = client.get(f"{BASE}/api/salt-spray/observations").json()
        assert sorted([c["id"] for c in acts_final]) == sorted(orig_ids)
        hdr_final = client.get(f"{BASE}/api/salt-spray/observation-header").json()
        for k in ("operator", "start_time", "start_date", "pressure", "water",
                  "chamber_temp_min", "chamber_temp_max", "saturated_air_temp",
                  "ph", "specimen_position", "plate_grinding", "plate_grinding_note"):
            assert hdr_final.get(k) == hdr0.get(k), f"header field {k} mismatch after reopen"

        # 6a) reopen must 409 while active cards present
        # pick ANY previously completed series (there should be at least one old one in history)
        hist = client.get(f"{BASE}/api/salt-spray/observation-series").json()
        if hist:
            other = hist[0]["id"]
            r409b = client.post(f"{BASE}/api/salt-spray/observation-series/{other}/reopen")
            assert r409b.status_code == 409
    finally:
        # Safety net: ensure nothing is left in a bad state
        if temp_series_id:
            client.delete(f"{BASE}/api/salt-spray/observation-series/{temp_series_id}")
        if real_series_id:
            # best-effort reopen
            client.post(f"{BASE}/api/salt-spray/observation-series/{real_series_id}/reopen")
