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


def test_viewer_assets_and_markup():
    # three.js-Vendor + aufgeteilte Assets werden unter /static ausgeliefert
    for path in ("/static/vendor/STLLoader.js", "/static/app.css",
                 "/static/app.js", "/static/viewer.js"):
        assert client.get(path).status_code == 200, path
    html = client.get("/").text
    assert "viewerModal" in html
    assert "/static/app.js" in html          # Gerüst verweist auf app.js
    assert "openSTLViewer" in client.get("/static/viewer.js").text
    # Cache-Busting: Asset-URLs tragen die Version, kein Platzhalter bleibt übrig
    assert "__ASSETVER__" not in html
    assert f"/static/app.css?v={_EXPECTED_VERSION}" in html
    assert f"/static/app.js?v={_EXPECTED_VERSION}" in html


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


import pathlib as _pl
_EXPECTED_VERSION = (_pl.Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()


def test_version():
    v = client.get("/v1/version", headers=AUTH)
    assert v.status_code == 200
    body = v.json()
    assert body["version"] == _EXPECTED_VERSION   # aus VERSION-Datei
    assert "git_sha" in body and "build_date" in body
    assert client.get("/v1/version").status_code == 401


def test_update_status_and_apply():
    s = client.get("/v1/update/status", headers=AUTH)
    assert s.status_code == 200
    body = s.json()
    assert body["current"] == _EXPECTED_VERSION
    assert body["update_available"] is False   # ohne status.json vom Watcher
    assert body["applying"] is False
    # Apply-Anforderung schreibt die Request-Datei
    a = client.post("/v1/update/apply", headers=AUTH)
    assert a.status_code == 200 and a.json()["requested"] is True
    assert client.get("/v1/update/status", headers=AUTH).json()["requested"] is True
    assert client.get("/v1/update/status").status_code == 401


def test_threemf_export():
    import io
    import zipfile

    # Batch anlegen, dann Mehrfarb-3MF daraus bauen
    b = client.post("/v1/airlocks:generate", json={"count": 3}, headers=AUTH).json()
    r = client.post("/v1/airlocks:threemf", json={"batch_id": b["batch_id"]}, headers=AUTH)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] == 3
    assert j["cols"] >= 1 and j["rows"] >= 1
    assert j["fits_on_plate"] is True
    assert j["file"].startswith("tmf_") and j["file"].endswith(".3mf")

    # Download + Struktur der 3MF prüfen
    d = client.get(j["download_url"], headers=AUTH)
    assert d.status_code == 200
    assert d.headers["content-type"] == "model/3mf"
    zf = zipfile.ZipFile(io.BytesIO(d.content))
    names = zf.namelist()
    assert "3D/3dmodel.model" in names and "[Content_Types].xml" in names
    model = zf.read("3D/3dmodel.model").decode()
    assert model.count("<m:colorgroup") == 1   # eine Farbgruppe
    assert model.count("<m:color ") == 2       # zwei Farben (Body/Code)
    assert 'p1="0"' in model and 'p1="1"' in model  # Pro-Dreieck-Farbe je Teil
    assert model.count("<item ") == 3          # ein Bau-Item je Airlock

    # Direkte Code-Vorgabe inkl. Dedup
    r2 = client.post("/v1/airlocks:threemf",
                     json={"codes": ["73412", "73412", "42"]}, headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["count"] == 2
    assert r2.json()["codes"] == ["73412", "00042"]

    # Auth + Validierung
    assert client.post("/v1/airlocks:threemf", json={"batch_id": b["batch_id"]}).status_code == 401
    assert client.post("/v1/airlocks:threemf", json={}, headers=AUTH).status_code == 422
    assert client.get("/v1/threemf/tmf_deadbeefcafe.3mf", headers=AUTH).status_code == 404
    assert client.get("/v1/threemf/not-a-token.3mf", headers=AUTH).status_code == 400

    # OBJ-Format (Per-Vertex-Farbe, Body schwarz / Code weiss)
    ro = client.post("/v1/airlocks:threemf",
                     json={"batch_id": b["batch_id"], "format": "obj"}, headers=AUTH)
    assert ro.status_code == 200
    jo = ro.json()
    assert jo["format"] == "obj" and jo["file"].endswith(".obj")
    do = client.get(jo["download_url"], headers=AUTH)
    assert do.status_code == 200 and do.headers["content-type"] == "model/obj"
    objtxt = do.content.decode()
    assert "0 0 0" in objtxt and "1 1 1" in objtxt   # zwei Vertex-Farben
    # ungültiges Format -> 422
    assert client.post("/v1/airlocks:threemf",
                       json={"batch_id": b["batch_id"], "format": "stl"}, headers=AUTH).status_code == 422


def test_nfc_tag_binding():
    b = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()
    code = b["airlocks"][0]["code"]
    uid = "04:11:22:33:44:55:80"

    p = client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH)
    assert p.status_code == 200, p.text
    pj = p.json()
    assert pj["uid"] == "04112233445580"          # normalisiert (Hex, ohne Trenner)
    assert pj["ndef_text"].startswith("AL1|")
    token = pj["token"]

    # binden
    cm = client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH)
    assert cm.status_code == 200 and cm.json()["nfc_uid"] == "04112233445580"

    # gültige Verifikation
    v = client.post(f"/v1/airlocks/{code}/nfc/verify",
                    json={"uid": uid, "token": token}, headers=AUTH).json()
    assert v["valid"] is True

    # falscher Token
    bad = client.post(f"/v1/airlocks/{code}/nfc/verify",
                      json={"uid": uid, "token": "00" * 16}, headers=AUTH).json()
    assert bad["valid"] is False and bad["reason"] == "bad_signature"

    # fremde UID (Klon mit neuem Tag) -> abgelehnt
    clone = client.post(f"/v1/airlocks/{code}/nfc/verify",
                        json={"uid": "04:99:99:99:99:99:80", "token": token}, headers=AUTH).json()
    assert clone["valid"] is False

    # dieselbe UID an einen anderen Code binden -> Konflikt
    b2 = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()
    code2 = b2["airlocks"][0]["code"]
    assert client.post(f"/v1/airlocks/{code2}/nfc/commit", json={"uid": uid}, headers=AUTH).status_code == 409

    # Auth
    assert client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}).status_code == 401


def test_config_masks_key():
    c = client.get("/v1/config", headers=AUTH)
    assert c.status_code == 200
    body = c.json()
    assert body["api_key_masked"] != "test-key"      # nicht im Klartext
    assert body["profile"]["name"] == "DisposableLock_v2"
    assert body["max_batch"] == 50
    assert client.get("/v1/config").status_code == 401
