"""Backend tests for Salt Spray observation header + hours field in cards.

Covers:
- GET /api/salt-spray/observation-header returns defaults (never 404).
- PUT /api/salt-spray/observation-header persists all fields and GET returns them.
- POST/PUT /api/salt-spray/observations accept 'hours' numeric -> duration_label = "<hours> Jam".
- When 'hours' omitted, it's parsed from duration_label ("24 Jam" -> 24).
- List is sorted by hours then seq.

Restores the original header at teardown and deletes any test cards it created.
"""
import os
import pytest
import requests


def _base() -> str:
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL="):
                return ln.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _base()
HEADER_URL = f"{BASE_URL}/api/salt-spray/observation-header"
OBS_URL = f"{BASE_URL}/api/salt-spray/observations"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def original_header(client):
    r = client.get(HEADER_URL)
    assert r.status_code == 200, r.text
    original = r.json()
    yield original
    # restore
    client.put(HEADER_URL, json={k: v for k, v in original.items() if k != "updated_at"})


class TestHeader:
    def test_get_returns_defaults_shape(self, client, original_header):
        r = client.get(HEADER_URL)
        assert r.status_code == 200
        data = r.json()
        for k in ("operator", "specimen_position", "pressure", "water",
                  "chamber_temp_min", "chamber_temp_max", "saturated_air_temp",
                  "ph", "plate_grinding", "plate_grinding_note"):
            assert k in data, f"missing {k} in header response"
        assert isinstance(data["plate_grinding"], bool)

    def test_put_persists_all_fields(self, client, original_header):
        payload = {
            "operator": "TEST_Operator",
            "specimen_position": "20°",
            "pressure": "14 psi",
            "water": "TEST_water_content",
            "chamber_temp_min": "35.5",
            "chamber_temp_max": "36.2",
            "saturated_air_temp": "47°C",
            "ph": "6.8 di suhu 35°C",
            "plate_grinding": True,
            "plate_grinding_note": "TEST grit 240",
        }
        r = client.put(HEADER_URL, json=payload)
        assert r.status_code == 200, r.text
        resp = r.json()
        for k, v in payload.items():
            assert resp[k] == v, f"PUT response field {k}={resp.get(k)} expected {v}"
        assert resp.get("updated_at")

        # GET verifies persistence
        g = client.get(HEADER_URL).json()
        for k, v in payload.items():
            assert g[k] == v, f"GET persisted field {k}={g.get(k)} expected {v}"


# ---------- Hours field in cards ----------

def _copy_card_as_template(client):
    """Find an existing new-format card to copy plates/photo_path from (do not modify it)."""
    cards = client.get(OBS_URL).json()
    for c in cards:
        if c.get("photo_path") and len(c.get("plates") or []) == 4:
            return c
    pytest.skip("No existing new-format salt obs card available to clone plates from")


def _make_card(client, template, codes, *, hours=None, duration_label=None, seq=99, all_rust=True):
    plates = []
    for i, p in enumerate(template["plates"]):
        boxes = [bool(all_rust)] * 100
        plates.append({
            "bbox": p["bbox"],
            "crop_path": p.get("crop_path"),
            "label": p.get("label", f"P{i+1}"),
            "code": codes[i],
            "grid_boxes": boxes,
            "ai_grid_boxes": list(boxes),
            "confidence": p.get("confidence") or 90,
            "rust_spread": p.get("rust_spread", ""),
            "summary": "TEST",
        })
    payload = {
        "seq": seq,
        "photo_path": template["photo_path"],
        "detection": template.get("detection", "ai"),
        "plates": plates,
    }
    if hours is not None:
        payload["hours"] = hours
    if duration_label is not None:
        payload["duration_label"] = duration_label
    r = client.post(OBS_URL, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestObsHours:
    created_ids = []

    @classmethod
    def teardown_class(cls):
        # cleanup is per-test via try/finally too, but ensure here
        pass

    def test_hours_numeric_sets_duration_label(self, client):
        template = _copy_card_as_template(client)
        card = _make_card(client, template, [f"TEST_H_{i}" for i in range(4)], hours=6)
        TestObsHours.created_ids.append(card["id"])
        try:
            assert card["hours"] == 6
            assert card["duration_label"] == "6 Jam"
            # verify persisted via GET
            g = client.get(f"{OBS_URL}/{card['id']}").json()
            assert g["hours"] == 6 and g["duration_label"] == "6 Jam"
        finally:
            client.delete(f"{OBS_URL}/{card['id']}")

    def test_hours_parsed_from_duration_label(self, client):
        template = _copy_card_as_template(client)
        card = _make_card(client, template, [f"TEST_P_{i}" for i in range(4)], duration_label="24 Jam")
        try:
            assert card["hours"] == 24
            assert card["duration_label"] == "24 Jam"
        finally:
            client.delete(f"{OBS_URL}/{card['id']}")

    def test_put_updates_hours(self, client):
        template = _copy_card_as_template(client)
        card = _make_card(client, template, [f"TEST_U_{i}" for i in range(4)], hours=6)
        try:
            # PUT with new hours=72
            plates = card["plates"]
            payload = {
                "seq": 99, "hours": 72, "photo_path": card["photo_path"],
                "detection": card.get("detection", "ai"), "plates": plates,
            }
            r = client.put(f"{OBS_URL}/{card['id']}", json=payload)
            assert r.status_code == 200, r.text
            upd = r.json()
            assert upd["hours"] == 72
            assert upd["duration_label"] == "72 Jam"
        finally:
            client.delete(f"{OBS_URL}/{card['id']}")

    def test_list_sorted_by_hours_then_seq(self, client):
        template = _copy_card_as_template(client)
        c1 = _make_card(client, template, [f"TEST_S1_{i}" for i in range(4)], hours=240, seq=2)
        c2 = _make_card(client, template, [f"TEST_S2_{i}" for i in range(4)], hours=10, seq=5)
        c3 = _make_card(client, template, [f"TEST_S3_{i}" for i in range(4)], hours=10, seq=1)
        try:
            cards = client.get(OBS_URL).json()
            ids_in_order = [c["id"] for c in cards if c["id"] in {c1["id"], c2["id"], c3["id"]}]
            # expect order: c3 (10,1), c2 (10,5), c1 (240,2)
            assert ids_in_order == [c3["id"], c2["id"], c1["id"]], ids_in_order
        finally:
            for cid in (c1["id"], c2["id"], c3["id"]):
                client.delete(f"{OBS_URL}/{cid}")
