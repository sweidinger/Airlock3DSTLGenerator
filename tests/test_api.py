"""End-to-End-Tests der REST-API (FastAPI TestClient)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
AUTH = {"X-API-Key": "test-key"}


def _printed_code():
    """Generiert einen Lock und setzt ihn auf 'printed' (bereit zum Tag-Schreiben)."""
    code = client.post("/v1/airlocks:generate", json={"count": 1},
                       headers=AUTH).json()["airlocks"][0]["code"]
    r = client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH)
    assert r.status_code == 200, r.text
    return code


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

    # Tag-Schreiben erst ab 'printed'
    client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH)
    p = client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH)
    assert p.status_code == 200, p.text
    pj = p.json()
    assert pj["uid"] == "04112233445580"          # normalisiert (Hex, ohne Trenner)
    assert pj["ndef_text"].startswith("AL1|")
    token = pj["token"]

    # binden -> Status wird automatisch von 'generated' auf 'registered' gehoben
    cm = client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH)
    assert cm.status_code == 200 and cm.json()["nfc_uid"] == "04112233445580"
    assert cm.json()["status"] == "registered"

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
    code2 = _printed_code()
    assert client.post(f"/v1/airlocks/{code2}/nfc/commit", json={"uid": uid}, headers=AUTH).status_code == 409

    # Auth
    assert client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}).status_code == 401


def test_config_masks_key():
    c = client.get("/v1/config", headers=AUTH)
    assert c.status_code == 200
    body = c.json()
    assert body["api_key_masked"] != "test-key"      # nicht im Klartext
    assert body["profile"]["name"] == "DisposableLock_NTAG213"
    assert body["max_batch"] == 50
    assert client.get("/v1/config").status_code == 401


import json as _json


def test_kg_keys_and_scoped_access():
    # Key erzeugen (nur mit vollem Key moeglich)
    c = client.post("/v1/kg/keys", json={"name": "Handy"}, headers=AUTH)
    assert c.status_code == 200, c.text
    j = c.json()
    assert j["name"] == "Handy" and j["key"].startswith("kgt_")
    KG = {"X-API-Key": j["key"]}

    # Liste ist maskiert (kein Klartext-Key)
    lst = client.get("/v1/kg/keys", headers=AUTH).json()
    me = [k for k in lst if k["id"] == j["id"]]
    assert me and me[0]["active"] is True
    assert all("key" not in k for k in lst)

    # Airlock (voller Key), dann mit KG-Key lesen + Status setzen
    b = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()
    code = b["airlocks"][0]["code"]
    assert client.get("/v1/airlocks", headers=KG).status_code == 200
    assert client.get(f"/v1/airlocks/{code}", headers=KG).status_code == 200
    # generated → printed ist ein erlaubter Einzelschritt (KG-Key darf Status setzen)
    assert client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=KG).status_code == 200

    # KG-Key darf NICHT generieren / STL laden / Tag schreiben / Keys verwalten
    assert client.post("/v1/airlocks:generate", json={"count": 1}, headers=KG).status_code == 401
    assert client.get(f"/v1/airlocks/{code}/stl", headers=KG).status_code == 401
    assert client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": "04112233445580"}, headers=KG).status_code == 401
    assert client.post("/v1/kg/keys", json={"name": "x"}, headers=KG).status_code == 401
    assert client.get("/v1/stats", headers=KG).status_code == 401

    # Widerruf -> Key wirkungslos
    assert client.post(f"/v1/kg/keys/{j['id']}/revoke", headers=AUTH).status_code == 200
    assert client.get("/v1/airlocks", headers=KG).status_code == 401
    # unbekannter Key -> 404
    assert client.post("/v1/kg/keys/deadbeef/revoke", headers=AUTH).status_code == 404


def test_kg_regenerate():
    j = client.post("/v1/kg/keys", json={"name": "Rot"}, headers=AUTH).json()
    old = {"X-API-Key": j["key"]}
    b = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()
    code = b["airlocks"][0]["code"]
    assert client.get(f"/v1/airlocks/{code}", headers=old).status_code == 200
    # regenerieren -> alter Key ungueltig, neuer gueltig, Name bleibt
    g = client.post(f"/v1/kg/keys/{j['id']}/regenerate", headers=AUTH).json()
    assert g["name"] == "Rot" and g["key"].startswith("kgt_") and g["key"] != j["key"]
    new = {"X-API-Key": g["key"]}
    assert client.get(f"/v1/airlocks/{code}", headers=old).status_code == 401
    assert client.get(f"/v1/airlocks/{code}", headers=new).status_code == 200


def test_kg_verify_require_status():
    code = _printed_code()
    uid = "04AABBCCDDEE80"
    tok = client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH).json()["token"]
    client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH)
    KG = {"X-API-Key": client.post("/v1/kg/keys", json={"name": "v"}, headers=AUTH).json()["key"]}

    v = client.post(f"/v1/airlocks/{code}/nfc/verify", json={"uid": uid, "token": tok}, headers=KG).json()
    assert v["valid"] is True
    # require_status=active, Status ist nach commit 'registered' -> mismatch
    m = client.post(f"/v1/airlocks/{code}/nfc/verify",
                    json={"uid": uid, "token": tok, "require_status": "active"}, headers=KG).json()
    assert m["valid"] is False and m["reason"] == "status_mismatch" and m["status"] == "registered"
    # auf active setzen -> jetzt gueltig
    client.patch(f"/v1/airlocks/{code}", json={"status": "active"}, headers=KG)
    ok = client.post(f"/v1/airlocks/{code}/nfc/verify",
                     json={"uid": uid, "token": tok, "require_status": "active"}, headers=KG).json()
    assert ok["valid"] is True


def test_available_filter():
    b = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()
    code = b["airlocks"][0]["code"]
    # frisch (kein Tag) -> nicht verfuegbar
    assert all(a["code"] != code for a in client.get("/v1/airlocks?available=true", headers=AUTH).json())
    # drucken, dann Tag binden -> verfuegbar
    client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH)
    client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": "04CAFEBABE1280"}, headers=AUTH)
    assert any(a["code"] == code for a in client.get("/v1/airlocks?available=true", headers=AUTH).json())
    # aktiv -> nicht mehr verfuegbar
    client.patch(f"/v1/airlocks/{code}", json={"status": "active"}, headers=AUTH)
    assert all(a["code"] != code for a in client.get("/v1/airlocks?available=true", headers=AUTH).json())


def test_kg_debug_log():
    client.post("/v1/kg/log:clear", headers=AUTH)
    kgkey = client.post("/v1/kg/keys", json={"name": "Logtest"}, headers=AUTH).json()["key"]
    KG = {"X-API-Key": kgkey}
    client.get("/v1/airlocks", headers=KG)
    entries = client.get("/v1/kg/log", headers=AUTH).json()["entries"]
    assert any(e["path"] == "/v1/airlocks" and e["method"] == "GET" and e["key_name"] == "Logtest"
               for e in entries)
    # Voll-Key-Anfragen tauchen NICHT im KG-Log auf
    client.get("/v1/stats", headers=AUTH)
    entries2 = client.get("/v1/kg/log", headers=AUTH).json()["entries"]
    assert all(e["path"] != "/v1/stats" for e in entries2)
    # Der Key-Klartext steht nie im Log
    assert kgkey not in _json.dumps(entries2)
    # Log-Zugriff selbst braucht den vollen Key
    assert client.get("/v1/kg/log", headers=KG).status_code == 401


def test_nfc_secret_management():
    # Ausgangszustand: kein echtes Secret (Default)
    st = client.get("/v1/nfc/secret/status", headers=AUTH).json()
    assert st["configured"] is False and st["source"] == "default" and st["env_override"] is False

    # generate ohne confirm -> 400
    assert client.post("/v1/nfc/secret/generate", json={}, headers=AUTH).status_code == 400

    # generate mit confirm -> Secret gesetzt (einmal sichtbar)
    g = client.post("/v1/nfc/secret/generate", json={"confirm": True}, headers=AUTH).json()
    secret1 = g["secret"]
    assert len(secret1) == 64 and g["source"] == "db" and g["configured"] is True
    assert client.get("/v1/nfc/secret/status", headers=AUTH).json()["source"] == "db"

    # Das effektive Secret wird tatsaechlich fuer Tokens genutzt
    code = _printed_code()
    uid = "04ABCDEF120380"
    p = client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH).json()
    assert p["secret_configured"] is True
    token = p["token"]
    client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH)
    assert client.post(f"/v1/airlocks/{code}/nfc/verify",
                       json={"uid": uid, "token": token}, headers=AUTH).json()["valid"] is True

    # Backup exportieren (Passwort schuetzt die Datei; kein Klartext-Secret drin)
    bk = client.post("/v1/nfc/secret/backup", json={"password": "geheim-123"}, headers=AUTH).json()
    blob = bk["backup"]
    assert secret1 not in blob and "airlock-nfc-secret-backup" in blob

    # Rotieren -> altes Token wird ungueltig
    g2 = client.post("/v1/nfc/secret/generate", json={"confirm": True}, headers=AUTH).json()
    assert g2["secret"] != secret1
    assert client.post(f"/v1/airlocks/{code}/nfc/verify",
                       json={"uid": uid, "token": token}, headers=AUTH).json()["reason"] == "bad_signature"

    # Restore aus Backup -> altes Secret zurueck, Token wieder gueltig
    r = client.post("/v1/nfc/secret/restore",
                    json={"password": "geheim-123", "backup": blob, "confirm": True}, headers=AUTH)
    assert r.status_code == 200
    assert client.post(f"/v1/airlocks/{code}/nfc/verify",
                       json={"uid": uid, "token": token}, headers=AUTH).json()["valid"] is True

    # Falsches Passwort -> 422; ohne confirm -> 400; ohne Key -> 401
    assert client.post("/v1/nfc/secret/restore",
                       json={"password": "falsch", "backup": blob, "confirm": True}, headers=AUTH).status_code == 422
    assert client.post("/v1/nfc/secret/restore",
                       json={"password": "geheim-123", "backup": blob}, headers=AUTH).status_code == 400
    assert client.get("/v1/nfc/secret/status").status_code == 401


def test_writer_keys_and_scoped_access():
    # Key erzeugen (nur mit vollem Key moeglich)
    c = client.post("/v1/writer/keys", json={"name": "iPhone Werkstatt"}, headers=AUTH)
    assert c.status_code == 200, c.text
    j = c.json()
    assert j["name"] == "iPhone Werkstatt" and j["key"].startswith("alw_")
    WR = {"X-API-Key": j["key"]}

    # Liste ist maskiert (kein Klartext-Key)
    lst = client.get("/v1/writer/keys", headers=AUTH).json()
    me = [k for k in lst if k["id"] == j["id"]]
    assert me and me[0]["active"] is True
    assert all("key" not in k for k in lst)

    # Airlock (voller Key), dann mit Writer-Key lesen + Tag beschreiben
    b = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()
    code = b["airlocks"][0]["code"]
    uid = "0455667788AA80"
    client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH)  # erst drucken
    assert client.get("/v1/airlocks", headers=WR).status_code == 200
    assert client.get(f"/v1/airlocks/{code}", headers=WR).status_code == 200
    assert client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=WR).status_code == 200
    cm = client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=WR)
    assert cm.status_code == 200 and cm.json()["nfc_uid"] == "0455667788AA80"

    # Writer-Key darf NICHT generieren / STL laden / Status setzen / Keys verwalten
    assert client.post("/v1/airlocks:generate", json={"count": 1}, headers=WR).status_code == 401
    assert client.get(f"/v1/airlocks/{code}/stl", headers=WR).status_code == 401
    assert client.patch(f"/v1/airlocks/{code}", json={"status": "active"}, headers=WR).status_code == 401
    assert client.post("/v1/writer/keys", json={"name": "x"}, headers=WR).status_code == 401
    assert client.get("/v1/stats", headers=WR).status_code == 401
    # Writer-Key DARF jetzt verifizieren (v1.10.0, Selbstkontrolle nach dem Schreiben)
    vw = client.post(f"/v1/airlocks/{code}/nfc/verify", json={"uid": uid, "token": "x"}, headers=WR)
    assert vw.status_code == 200 and vw.json()["valid"] is False

    # Ein KG-Key darf umgekehrt NICHT schreiben (Scopes bleiben getrennt)
    KG = {"X-API-Key": client.post("/v1/kg/keys", json={"name": "K"}, headers=AUTH).json()["key"]}
    assert client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=KG).status_code == 401

    # Widerruf -> Key wirkungslos
    assert client.post(f"/v1/writer/keys/{j['id']}/revoke", headers=AUTH).status_code == 200
    assert client.get("/v1/airlocks", headers=WR).status_code == 401
    # unbekannter Key -> 404
    assert client.post("/v1/writer/keys/deadbeef/revoke", headers=AUTH).status_code == 404


def test_writer_regenerate():
    j = client.post("/v1/writer/keys", json={"name": "Rot"}, headers=AUTH).json()
    old = {"X-API-Key": j["key"]}
    b = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()
    code = b["airlocks"][0]["code"]
    assert client.get(f"/v1/airlocks/{code}", headers=old).status_code == 200
    # regenerieren -> alter Key ungueltig, neuer gueltig, Name bleibt
    g = client.post(f"/v1/writer/keys/{j['id']}/regenerate", headers=AUTH).json()
    assert g["name"] == "Rot" and g["key"].startswith("alw_") and g["key"] != j["key"]
    new = {"X-API-Key": g["key"]}
    assert client.get(f"/v1/airlocks/{code}", headers=old).status_code == 401
    assert client.get(f"/v1/airlocks/{code}", headers=new).status_code == 200


def test_writer_key_in_debug_log():
    client.post("/v1/kg/log:clear", headers=AUTH)
    wrkey = client.post("/v1/writer/keys", json={"name": "LogWriter"}, headers=AUTH).json()["key"]
    WR = {"X-API-Key": wrkey}
    client.get("/v1/airlocks", headers=WR)
    entries = client.get("/v1/kg/log", headers=AUTH).json()["entries"]
    assert any(e["path"] == "/v1/airlocks" and e["key_name"] == "LogWriter" for e in entries)
    assert wrkey not in _json.dumps(entries)


def test_nfc_marriage_permanent_and_rebind():
    code = _printed_code()
    uid_x = "04AA11BB22CC80"
    uid_y = "04DD33EE44FF80"

    # Erstbindung -> ok, Status auf registered gehoben
    r = client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid_x}, headers=AUTH)
    assert r.status_code == 200 and r.json()["nfc_uid"] == uid_x
    assert r.json()["status"] == "registered"
    assert "warning" not in r.json()

    # Anderer Tag OHNE rebind -> Bindung ist endgueltig -> 409
    assert client.post(f"/v1/airlocks/{code}/nfc/commit",
                       json={"uid": uid_y}, headers=AUTH).status_code == 409

    # Gleicher Tag nochmal -> idempotent ok (dieselbe Ehe)
    assert client.post(f"/v1/airlocks/{code}/nfc/commit",
                       json={"uid": uid_x}, headers=AUTH).status_code == 200

    # Bewusstes Neu-Verheiraten mit freiem Tag -> ersetzt Bindung, mit Warnung
    r2 = client.post(f"/v1/airlocks/{code}/nfc/commit",
                     json={"uid": uid_y, "rebind": True}, headers=AUTH)
    assert r2.status_code == 200 and r2.json()["nfc_uid"] == uid_y
    assert "warning" in r2.json()

    # Tag von einem anderen Schloss "wegnehmen" ist ohne Beta-Flag verboten,
    # auch mit rebind (uid_y haengt jetzt an `code`).
    code2 = _printed_code()
    assert client.post(f"/v1/airlocks/{code2}/nfc/commit",
                       json={"uid": uid_y, "rebind": True}, headers=AUTH).status_code == 409


def test_registry_rebind_and_tag_move(tmp_path):
    import pytest

    from app.registry import Registry, TagBindingError

    reg = Registry(tmp_path / "r.db", code_length=5)
    reg.create_batch("bb", 2, "test", None)
    reg.add_airlock("11111", "bb", "auto", None)
    reg.add_airlock("22222", "bb", "auto", None)

    uid_a = "04AABBCCDDEE80"
    uid_b = "04FF00112233A0"

    # Promotion zu registered erfolgt nur aus 'printed' -> Testaufbau forcen
    reg.update_status("11111", "printed", force=True)
    res = reg.set_nfc("11111", uid_a)
    assert res["row"]["status"] == "registered"
    assert res["row"]["nfc_uid"] == uid_a
    assert res["rebound"] is False and res["moved_from"] is None

    # gleiche UID erneut -> idempotent, kein Fehler
    reg.set_nfc("11111", uid_a)

    # andere UID ohne rebind -> Konflikt
    with pytest.raises(TagBindingError):
        reg.set_nfc("11111", uid_b)

    # andere (freie) UID mit rebind -> ersetzt, rebound=True
    res2 = reg.set_nfc("11111", uid_b, rebind=True)
    assert res2["rebound"] is True and res2["row"]["nfc_uid"] == uid_b

    # uid_b haengt jetzt an 11111; Umzug nach 22222 ohne Beta -> verboten
    with pytest.raises(TagBindingError):
        reg.set_nfc("22222", uid_b, rebind=True, allow_tag_move=False)

    # mit Beta-Umzug -> Tag wandert, 11111 verliert ihn
    res3 = reg.set_nfc("22222", uid_b, rebind=True, allow_tag_move=True)
    assert res3["moved_from"] == "11111"
    assert reg.get_airlock("22222")["nfc_uid"] == uid_b
    assert reg.get_airlock("11111")["nfc_uid"] is None
    reg.close()


def test_status_transition_guard():
    code = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()["airlocks"][0]["code"]
    # unerlaubter Sprung generated -> active
    assert client.patch(f"/v1/airlocks/{code}", json={"status": "active"}, headers=AUTH).status_code == 409
    # erlaubter Einzelschritt generated -> printed
    assert client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH).status_code == 200
    # zurueck ohne force -> 409
    assert client.patch(f"/v1/airlocks/{code}", json={"status": "generated"}, headers=AUTH).status_code == 409
    # zurueck MIT force (voller Key) -> 200
    assert client.patch(f"/v1/airlocks/{code}",
                        json={"status": "generated", "force": True}, headers=AUTH).status_code == 200
    # Off-Ramp generated -> voided
    assert client.patch(f"/v1/airlocks/{code}", json={"status": "voided"}, headers=AUTH).status_code == 200
    # terminal: raus nur mit force
    assert client.patch(f"/v1/airlocks/{code}", json={"status": "active"}, headers=AUTH).status_code == 409
    assert client.patch(f"/v1/airlocks/{code}",
                        json={"status": "active", "force": True}, headers=AUTH).status_code == 200

    # force wird fuer NICHT-vollen Key ignoriert (KG-Key kann nicht erzwingen)
    KG = {"X-API-Key": client.post("/v1/kg/keys", json={"name": "F"}, headers=AUTH).json()["key"]}
    c2 = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()["airlocks"][0]["code"]
    assert client.patch(f"/v1/airlocks/{c2}",
                        json={"status": "active", "force": True}, headers=KG).status_code == 409


def test_tag_gate_requires_printed():
    code = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()["airlocks"][0]["code"]
    uid = "0412ABCDEF3480"
    # generated (kein Tag) -> prepare/commit abgelehnt
    assert client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH).status_code == 409
    assert client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH).status_code == 409
    # printed -> erlaubt, bindet + hebt auf registered
    client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH)
    assert client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH).status_code == 200
    cm = client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH)
    assert cm.status_code == 200 and cm.json()["status"] == "registered"
    # re-commit desselben Tags auf bereits gebundenem (registered) Lock -> weiter erlaubt
    assert client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH).status_code == 200


def test_status_history():
    code = client.post("/v1/airlocks:generate", json={"count": 1}, headers=AUTH).json()["airlocks"][0]["code"]
    uid = "04A1B2C3D4E5F0"
    client.patch(f"/v1/airlocks/{code}", json={"status": "printed"}, headers=AUTH)
    client.post(f"/v1/airlocks/{code}/nfc/commit", json={"uid": uid}, headers=AUTH)
    client.patch(f"/v1/airlocks/{code}", json={"status": "active"}, headers=AUTH)

    h = client.get(f"/v1/airlocks/{code}/history", headers=AUTH)
    assert h.status_code == 200
    entries = h.json()
    assert [e["to"] for e in entries] == ["reserved", "generated", "printed", "registered", "active"]
    by_to = {e["to"]: e for e in entries}
    assert by_to["reserved"]["source"] == "system"
    assert by_to["generated"]["source"] == "system"
    assert by_to["printed"]["source"] == "api"
    assert by_to["registered"]["source"] == "app"       # Tag geschrieben (App)
    assert by_to["active"]["source"] == "api"
    assert all(e["forced"] is False for e in entries)

    # forcierter Uebergang wird als forced=True markiert
    client.patch(f"/v1/airlocks/{code}", json={"status": "generated", "force": True}, headers=AUTH)
    last = client.get(f"/v1/airlocks/{code}/history", headers=AUTH).json()[-1]
    assert last["to"] == "generated" and last["forced"] is True

    # history braucht Lesezugriff
    assert client.get(f"/v1/airlocks/{code}/history").status_code == 401


def test_nfc_prepare_url_record():
    """prepare liefert das url-Feld: leer ohne Basis, sonst <base>/t/<code>."""
    import app.main as m
    code = _printed_code()
    uid = "04:11:22:33:44:55:80"
    p = client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH)
    assert p.status_code == 200, p.text
    assert p.json().get("url") == ""          # keine Basis gesetzt -> leer (Alt-Verhalten)

    object.__setattr__(m.settings, "tag_url_base", "https://nfc.neurorelatepoly.app/")
    try:
        p2 = client.post(f"/v1/airlocks/{code}/nfc/prepare", json={"uid": uid}, headers=AUTH).json()
        assert p2["url"] == f"https://nfc.neurorelatepoly.app/t/{code}"   # rstrip("/") greift
    finally:
        object.__setattr__(m.settings, "tag_url_base", "")
