"""End-to-End-Tests der REST-API (FastAPI TestClient)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
AUTH = {"X-API-Key": "test-key"}


def test_health_no_auth():
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json()["status"] == "ready"


def test_auth_required():
    r = client.post("/v1/airlocks:generate", json={"count": 1})
    assert r.status_code == 401


def test_generate_auto_batch():
    r = client.post("/v1/airlocks:generate", json={"count": 3}, headers=AUTH)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["count"] == 3
    assert b["status"] == "completed"
    assert b["zip_url"]
    codes = [a["code"] for a in b["airlocks"]]
    assert len(set(codes)) == 3
    for a in b["airlocks"]:
        assert a["status"] == "generated"
        assert len(a["code"]) == 5
        assert a["stl_sha256"]

    # STL-Download
    code = codes[0]
    s = client.get(f"/v1/airlocks/{code}/stl", headers=AUTH)
    assert s.status_code == 200
    assert s.content[:200]  # nicht leer
    # Batch-ZIP
    z = client.get(b["zip_url"], headers=AUTH)
    assert z.status_code == 200
    assert z.headers["content-type"] == "application/zip"


def test_provided_codes_and_conflict():
    r1 = client.post("/v1/airlocks:generate",
                     json={"codes": ["55501", "55502"]}, headers=AUTH)
    assert r1.status_code == 201, r1.text
    assert {a["code"] for a in r1.json()["airlocks"]} == {"55501", "55502"}

    # 55501 existiert bereits -> partieller Erfolg
    r2 = client.post("/v1/airlocks:generate",
                     json={"codes": ["55501", "55503"]}, headers=AUTH)
    assert r2.status_code == 201, r2.text
    body = r2.json()
    assert body["status"] == "partial"
    assert "55501" in body["conflicts"]
    assert {a["code"] for a in body["airlocks"]} == {"55503"}


def test_idempotency():
    key = {"Idempotency-Key": "fixed-key-123", **AUTH}
    a = client.post("/v1/airlocks:generate", json={"count": 2}, headers=key).json()
    b = client.post("/v1/airlocks:generate", json={"count": 2}, headers=key).json()
    assert a["batch_id"] == b["batch_id"]


def test_status_update():
    r = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH)
    code = r.json()["airlocks"][0]["code"]
    p = client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH)
    assert p.status_code == 200
    assert p.json()["status"] == "printed"
    bad = client.patch(f"/v1/airlocks/{code}", json={"status": "nonsense"}, headers=AUTH)
    assert bad.status_code == 422


def test_max_batch_guard():
    r = client.post("/v1/airlocks:generate", json={"count": 9999}, headers=AUTH)
    assert r.status_code == 400


def test_generate_requires_exactly_one():
    r = client.post("/v1/airlocks:generate", json={}, headers=AUTH)
    assert r.status_code == 422
    r2 = client.post("/v1/airlocks:generate",
                     json={"count": 1, "codes": ["12345"]}, headers=AUTH)
    assert r2.status_code == 422


def test_dashboard_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Airlock-STL-Generator" in r.text


def test_dashboard_no_key_leak_by_default():
    # Ohne AIRLOCK_UI_AUTOKEY darf der Key-WERT NICHT im Seitenquelltext stehen.
    r = client.get("/")
    assert "test-key" not in r.text
    assert "window.__AIRLOCK_KEY__=" not in r.text  # kein injiziertes Key-Script


def test_stats():
    client.post("/v1/airlocks:generate", json={"count": 2}, headers=AUTH)
    s = client.get("/v1/stats", headers=AUTH)
    assert s.status_code == 200
    body = s.json()
    assert body["code_space"] == 100000
    assert body["used"] >= 2
    assert body["used"] + body["free"] == body["code_space"]
    assert "generated" in body["by_status"]
    assert body["template_ready"] is True
    assert client.get("/v1/stats").status_code == 401


def test_batches_list():
    client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH)
    b = client.get("/v1/batches", headers=AUTH)
    assert b.status_code == 200
    rows = b.json()
    assert isinstance(rows, list) and len(rows) >= 1
    assert {"batch_id", "count", "status", "created_at"} <= set(rows[0])


def test_config_masks_key():
    c = client.get("/v1/config", headers=AUTH)
    assert c.status_code == 200
    body = c.json()
    assert body["api_key_masked"] != "test-key"      # nicht im Klartext
    assert body["profile"]["name"] == "DisposableLock_v2"
    assert body["max_batch"] == 50
    assert client.get("/v1/config").status_code == 401
