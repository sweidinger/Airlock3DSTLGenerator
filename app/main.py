"""FastAPI-App: REST-Schnittstelle des Airlock-Generators."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from . import kgkeys, kglog, secretbackup, writerkeys
from . import nfc as nfclib
from .auth import require_api_key
from .config import settings
from .generator import validate_code
from .models import (AirlockOut, BatchOut, GenerateRequest, KgKeyCreate,
                     NfcCommitRequest, NfcPrepareRequest, NfcSecretBackupRequest,
                     NfcSecretGenerate, NfcSecretRestoreRequest, NfcVerifyRequest,
                     StatusUpdate, ThreeMFRequest, WriterKeyCreate)
from .registry import STATUSES, CodeExhaustionError
from .service import AirlockService
from .updates import read_status, request_update
from .version import APP_VERSION, BUILD_DATE, GIT_SHA

app = FastAPI(
    title="Airlock-STL-Generator",
    version="1.0.0",
    description="Erzeugt Airlock-STLs mit erhabener 5-stelliger Nummer für die KG-Tracker App.",
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Statische Assets (three.js-Vendor, Viewer) unter /static ausliefern.
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_service: AirlockService | None = None


def get_service() -> AirlockService:
    global _service
    if _service is None:
        _service = AirlockService()
    return _service


# ---- KG-Tracker-Zugriff (voller Key ODER eingeschraenkter KG-Key) --------
def _presented_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _identify_kg(presented: str, svc: AirlockService) -> dict | None:
    """Ordnet einen praesentierten Key einem KG-Key zu (statisch/ENV oder DB)."""
    if settings.kg_api_key and secrets.compare_digest(presented, settings.kg_api_key):
        return {"id": "env", "prefix": "env", "name": "ENV"}
    if kgkeys.looks_like_kg_key(presented):
        row = svc.registry.find_active_kg_key_by_hash(kgkeys.hash_key(presented))
        if row is not None:
            return {"id": row["id"], "prefix": row["key_prefix"], "name": row["name"]}
    return None


async def require_kg_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    svc: AirlockService = Depends(get_service),
) -> None:
    """Erlaubt den vollen Key ODER einen gueltigen KG-Tracker-Key.

    Fuer Lesen, Statuswechsel und NFC-verify. Schreibende/erzeugende Endpoints
    bleiben auf `require_api_key` (nur voller Key).
    """
    presented = _presented_key(x_api_key, authorization)
    if presented and secrets.compare_digest(presented, settings.api_key):
        return
    if presented and _identify_kg(presented, svc) is not None:
        if not (settings.kg_api_key and secrets.compare_digest(presented, settings.kg_api_key)):
            info = _identify_kg(presented, svc)
            if info and info["id"] != "env":
                svc.registry.touch_kg_key(info["id"])
        return
    raise HTTPException(
        status_code=401,
        detail="Ungueltiger oder fehlender API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _identify_writer(presented: str, svc: AirlockService) -> dict | None:
    """Ordnet einen praesentierten Key einem aktiven Writer-Key (DB) zu."""
    if writerkeys.looks_like_writer_key(presented):
        row = svc.registry.find_active_writer_key_by_hash(writerkeys.hash_key(presented))
        if row is not None:
            return {"id": row["id"], "prefix": row["key_prefix"], "name": row["name"]}
    return None


async def require_writer_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    svc: AirlockService = Depends(get_service),
) -> None:
    """Erlaubt den vollen Key ODER einen gueltigen Writer-Key.

    Fuer das Beschreiben der Tags (nfc/prepare, nfc/commit). Ein Writer-Key darf
    NICHT generieren, herunterladen, den Status wechseln oder verifizieren.
    """
    presented = _presented_key(x_api_key, authorization)
    if presented and secrets.compare_digest(presented, settings.api_key):
        return
    if presented:
        info = _identify_writer(presented, svc)
        if info is not None:
            svc.registry.touch_writer_key(info["id"])
            return
    raise HTTPException(
        status_code=401,
        detail="Ungueltiger oder fehlender API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_read_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    svc: AirlockService = Depends(get_service),
) -> None:
    """Lesezugriff: voller Key ODER KG-Key ODER Writer-Key.

    Fuer das Auflisten/Ansehen der Airlocks (beide App-Typen brauchen das).
    """
    presented = _presented_key(x_api_key, authorization)
    if not presented:
        raise HTTPException(
            status_code=401, detail="Ungueltiger oder fehlender API-Key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if secrets.compare_digest(presented, settings.api_key):
        return
    kg = _identify_kg(presented, svc)
    if kg is not None:
        if kg["id"] != "env":
            svc.registry.touch_kg_key(kg["id"])
        return
    wr = _identify_writer(presented, svc)
    if wr is not None:
        svc.registry.touch_writer_key(wr["id"])
        return
    raise HTTPException(
        status_code=401, detail="Ungueltiger oder fehlender API-Key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.middleware("http")
async def _kg_request_log(request: Request, call_next):
    """Protokolliert (nur) KG-Key-Anfragen an /v1 im In-Memory-Ringpuffer."""
    response = await call_next(request)
    try:
        path = request.url.path
        if path.startswith("/v1"):
            presented = _presented_key(
                request.headers.get("x-api-key"), request.headers.get("authorization")
            )
            if presented and not secrets.compare_digest(presented, settings.api_key):
                looks = (kgkeys.looks_like_kg_key(presented)
                         or writerkeys.looks_like_writer_key(presented))
                info = None
                try:
                    svc = get_service()
                    info = _identify_kg(presented, svc) or _identify_writer(presented, svc)
                except Exception:
                    info = None
                if info is not None or looks:
                    note = response.headers.get("X-Airlock-Note")
                    if "X-Airlock-Note" in response.headers:
                        del response.headers["X-Airlock-Note"]
                    kglog.add(
                        method=request.method, path=path, status=response.status_code,
                        key_id=(info or {}).get("id"),
                        key_prefix=(info or {}).get("prefix") or presented[:12],
                        key_name=(info or {}).get("name"),
                        client=(request.client.host if request.client else None),
                        note=note,
                    )
    except Exception:
        pass
    return response


# ---- Web-Dashboard (ohne Auth; API-Aufrufe darin nutzen den API-Key) ---
@app.get("/", include_in_schema=False)
def dashboard():
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "Dashboard nicht gefunden.")
    html = index.read_text(encoding="utf-8")
    # Cache-Busting: Asset-URLs mit der aktuellen Version versehen, damit der
    # Browser nach einem Update garantiert die neuen /static-Dateien lädt.
    html = html.replace("__ASSETVER__", APP_VERSION)
    # Optional: API-Key ins Dashboard injizieren (AIRLOCK_UI_AUTOKEY=1).
    # Achtung: Key ist dann im Seitenquelltext sichtbar -> nur im vertrauten LAN.
    if settings.ui_autokey:
        inject = f"<script>window.__AIRLOCK_KEY__={json.dumps(settings.api_key)};</script>"
        html = html.replace("</head>", inject + "\n</head>", 1)
    return HTMLResponse(html)


# ---- Health (ohne Auth) ----------------------------------------------
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz():
    ok = Path(settings.profile.base_stl).is_file()
    if not ok:
        raise HTTPException(503, "Vorlage nicht verfügbar.")
    return {"status": "ready", "template": settings.profile.name}


# ---- Airlocks ---------------------------------------------------------
@app.post("/v1/airlocks:generate", response_model=BatchOut, status_code=201,
          dependencies=[Depends(require_api_key)], tags=["airlocks"])
def generate(req: GenerateRequest,
             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
             svc: AirlockService = Depends(get_service)):
    if req.count and req.count > settings.max_batch:
        raise HTTPException(400, f"count überschreitet max_batch ({settings.max_batch}).")
    if req.codes and len(req.codes) > settings.max_batch:
        raise HTTPException(400, f"Zu viele Codes (max {settings.max_batch}).")
    try:
        result = svc.generate(
            count=req.count, codes=req.codes, requested_by=req.requested_by,
            return_zip=req.return_zip, idempotency_key=idempotency_key,
        )
    except CodeExhaustionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if req.codes and result["status"] == "failed":
        raise HTTPException(409, {"detail": "Alle vorgegebenen Codes bereits vergeben.",
                                  "conflicts": result["conflicts"]})
    return result


@app.get("/v1/airlocks", response_model=list[AirlockOut],
         dependencies=[Depends(require_read_access)], tags=["airlocks"])
def list_airlocks(status: str | None = None, batch_id: str | None = None,
                  available: bool = Query(False, description="Nur verfuegbare Locks (Tag gebunden, noch frei)"),
                  limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                  svc: AirlockService = Depends(get_service)):
    rows = svc.registry.list_airlocks(status=status, batch_id=batch_id,
                                      available=available, limit=limit, offset=offset)
    return [_airlock_row_to_out(r) for r in rows]


@app.get("/v1/airlocks/{code}", response_model=AirlockOut,
         dependencies=[Depends(require_read_access)], tags=["airlocks"])
def get_airlock(code: str, svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    r = svc.registry.get_airlock(code)
    if r is None:
        raise HTTPException(404, f"Airlock {code} nicht gefunden.")
    return _airlock_row_to_out(r)


@app.get("/v1/airlocks/{code}/stl", dependencies=[Depends(require_api_key)], tags=["airlocks"])
def download_stl(code: str, svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    r = svc.registry.get_airlock(code)
    if r is None or not r["stl_path"]:
        raise HTTPException(404, f"STL für {code} nicht gefunden.")
    p = Path(r["stl_path"])
    if not p.is_file():
        raise HTTPException(410, "STL-Datei nicht mehr auf dem Datenträger.")
    return FileResponse(p, media_type="model/stl", filename=p.name)


@app.patch("/v1/airlocks/{code}", response_model=AirlockOut,
           dependencies=[Depends(require_kg_access)], tags=["airlocks"])
def update_status(code: str, upd: StatusUpdate, response: Response,
                  svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    try:
        r = svc.registry.update_status(code, upd.status)
    except KeyError:
        raise HTTPException(404, f"Airlock {code} nicht gefunden.")
    except ValueError as e:
        raise HTTPException(422, str(e))
    response.headers["X-Airlock-Note"] = f"status={upd.status}"
    return _airlock_row_to_out(r)


# ---- NFC-Tag (signierter Token gebunden an Tag-UID) ------------------
@app.post("/v1/airlocks/{code}/nfc/prepare", dependencies=[Depends(require_writer_access)], tags=["nfc"])
def nfc_prepare(code: str, req: NfcPrepareRequest, svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    if svc.registry.get_airlock(code) is None:
        raise HTTPException(404, f"Airlock {code} nicht gefunden.")
    secret = svc.effective_nfc_secret()
    try:
        payload = nfclib.make_payload(code, req.uid, secret)
    except ValueError as e:
        raise HTTPException(422, str(e))
    payload["secret_configured"] = not nfclib.secret_is_default(secret)
    return payload


@app.post("/v1/airlocks/{code}/nfc/commit", dependencies=[Depends(require_writer_access)], tags=["nfc"])
def nfc_commit(code: str, req: NfcCommitRequest, response: Response,
               svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    try:
        uid = nfclib.normalize_uid(req.uid)
    except ValueError as e:
        raise HTTPException(422, str(e))
    try:
        res = svc.registry.set_nfc(
            code, uid, rebind=req.rebind, allow_tag_move=settings.beta_tag_move,
        )
    except KeyError:
        raise HTTPException(404, f"Airlock {code} nicht gefunden.")
    except ValueError as e:
        # TagBindingError erbt von ValueError -> Bindungskonflikt = 409.
        raise HTTPException(409, str(e))
    out = _airlock_row_to_out(res["row"])
    warnings = []
    if res["rebound"]:
        warnings.append("Schloss wurde neu verheiratet – bestehende Tag-Bindung wurde ersetzt.")
    if res["moved_from"]:
        warnings.append(
            f"Beta: Tag war an Schloss {res['moved_from']} gebunden und wurde von dort "
            "geloest. Das andere Schloss hat jetzt keinen Tag mehr."
        )
    if warnings:
        out["warning"] = " ".join(warnings)
        response.headers["X-Airlock-Note"] = "rebind" + ("+move" if res["moved_from"] else "")
    return out


@app.post("/v1/airlocks/{code}/nfc/verify", dependencies=[Depends(require_kg_access)], tags=["nfc"])
def nfc_verify(code: str, req: NfcVerifyRequest, response: Response,
               svc: AirlockService = Depends(get_service)):
    """Für den KG-Tracker: prüft Signatur, UID-Bindung und (optional) Status."""
    code = _norm(code)
    r = svc.registry.get_airlock(code)
    if r is None:
        res = {"valid": False, "reason": "unknown_code"}
    else:
        try:
            uid = nfclib.normalize_uid(req.uid)
        except ValueError:
            uid = None
        if uid is None:
            res = {"valid": False, "reason": "bad_uid"}
        elif not nfclib.verify(code, uid, req.token, svc.effective_nfc_secret()):
            res = {"valid": False, "reason": "bad_signature"}
        else:
            bound = r["nfc_uid"]
            if bound and bound != uid:
                res = {"valid": False, "reason": "uid_mismatch", "bound_uid": bound}
            elif r["status"] in ("retired", "voided"):
                res = {"valid": False, "reason": f"status_{r['status']}", "status": r["status"]}
            elif req.require_status and r["status"] != req.require_status:
                res = {"valid": False, "reason": "status_mismatch", "status": r["status"]}
            else:
                res = {"valid": True, "code": code, "uid": uid, "status": r["status"],
                       "bound_uid": bound}
    response.headers["X-Airlock-Note"] = f"verify {res.get('valid')} {res.get('reason', 'ok')}"
    return res


# ---- Mehrfarb-Export (Bambu): 3MF / OBJ ------------------------------
@app.post("/v1/airlocks:threemf", dependencies=[Depends(require_api_key)], tags=["airlocks"])
def build_threemf(req: ThreeMFRequest, svc: AirlockService = Depends(get_service)):
    if req.codes and len(req.codes) > settings.max_batch:
        raise HTTPException(400, f"Zu viele Codes (max {settings.max_batch}).")
    try:
        return svc.build_threemf(
            codes=req.codes, batch_id=req.batch_id, fmt=req.format,
            plate=req.plate, margin=req.margin, gap=req.gap,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/v1/threemf/{name}", dependencies=[Depends(require_api_key)], tags=["airlocks"])
def download_threemf(name: str):
    import re as _re
    mt = _re.fullmatch(r"tmf_[0-9a-f]{6,}\.(3mf|obj)", name)
    if not mt:
        raise HTTPException(400, "Ungültiger Export-Name.")
    p = Path(settings.output_dir) / name
    if not p.is_file():
        raise HTTPException(404, "Export nicht gefunden.")
    media = "model/obj" if mt.group(1) == "obj" else "model/3mf"
    return FileResponse(p, media_type=media, filename=name)


# ---- Batches ----------------------------------------------------------
@app.get("/v1/batches/{batch_id}", response_model=BatchOut,
         dependencies=[Depends(require_api_key)], tags=["batches"])
def get_batch(batch_id: str, svc: AirlockService = Depends(get_service)):
    if svc.registry.get_batch(batch_id) is None:
        raise HTTPException(404, f"Batch {batch_id} nicht gefunden.")
    return svc._batch_view(batch_id, return_zip=True)


@app.get("/v1/batches/{batch_id}/zip", dependencies=[Depends(require_api_key)], tags=["batches"])
def download_zip(batch_id: str, svc: AirlockService = Depends(get_service)):
    b = svc.registry.get_batch(batch_id)
    if b is None or not b["zip_path"]:
        raise HTTPException(404, f"ZIP für Batch {batch_id} nicht gefunden.")
    p = Path(b["zip_path"])
    if not p.is_file():
        raise HTTPException(410, "ZIP nicht mehr auf dem Datenträger.")
    return FileResponse(p, media_type="application/zip", filename=p.name)


# ---- Dashboard-Daten (Stats / Batches / Config) ----------------------
@app.get("/v1/stats", dependencies=[Depends(require_api_key)], tags=["dashboard"])
def stats(svc: AirlockService = Depends(get_service)):
    counts = svc.registry.status_counts()
    total = sum(counts.values())
    space = settings.code_space
    return {
        "template": settings.profile.name,
        "code_length": settings.code_length,
        "code_space": space,
        "used": total,
        "free": space - total,
        "usage_pct": round(100 * total / space, 3) if space else 0,
        "max_batch": settings.max_batch,
        "by_status": {s: counts.get(s, 0) for s in STATUSES},
        "template_ready": Path(settings.profile.base_stl).is_file(),
    }


@app.get("/v1/batches", dependencies=[Depends(require_api_key)], tags=["batches"])
def list_batches(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                 svc: AirlockService = Depends(get_service)):
    rows = svc.registry.list_batches(limit=limit, offset=offset)
    return [{
        "batch_id": r["batch_id"], "count": r["count"], "status": r["status"],
        "created_at": r["created_at"], "requested_by": r["requested_by"],
        "zip_url": (f"/v1/batches/{r['batch_id']}/zip" if r["zip_path"] else None),
    } for r in rows]


@app.get("/v1/config", dependencies=[Depends(require_api_key)], tags=["dashboard"])
def config():
    p = settings.profile
    key = settings.api_key
    masked = (key[:3] + "…" + key[-2:]) if len(key) > 6 else "••••"
    return {
        "api_key_masked": masked,
        "max_batch": settings.max_batch,
        "code_length": settings.code_length,
        "output_dir": str(settings.output_dir),
        "openscad_bin": settings.openscad_bin,
        "render_timeout": settings.render_timeout,
        "ui_autokey": settings.ui_autokey,
        "profile": {
            "name": p.name,
            "font": p.font,
            "size": p.size,
            "xscale": p.xscale,
            "depth": p.depth,
            "sink": p.sink,
            "tx": p.tx,
            "ty": p.ty,
            "topz": p.topz,
            "rotate_deg": list(p.rot),
            "translate": list(p.translate),
            "expected_bounds_max": list(p.expected_bounds_max),
        },
    }


# ---- Version & Update ------------------------------------------------
@app.get("/v1/version", dependencies=[Depends(require_api_key)], tags=["version"])
def version():
    return {"version": APP_VERSION, "git_sha": GIT_SHA, "build_date": BUILD_DATE}


@app.get("/v1/update/status", dependencies=[Depends(require_api_key)], tags=["version"])
def update_status():
    return read_status()


@app.post("/v1/update/apply", dependencies=[Depends(require_api_key)], tags=["version"])
def update_apply():
    res = request_update()
    if not res.get("requested"):
        raise HTTPException(409, res.get("reason", "Update konnte nicht angefordert werden."))
    return res


# ---- KG-Tracker: eingeschraenkte Keys + Zugriffs-Log (nur voller Key) ----
def _kg_key_public(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "key_prefix": r["key_prefix"],
        "created_at": r["created_at"], "last_used_at": r["last_used_at"],
        "revoked_at": r["revoked_at"], "active": r["revoked_at"] is None,
    }


@app.post("/v1/kg/keys", dependencies=[Depends(require_api_key)], tags=["kg"])
def kg_key_create(req: KgKeyCreate, svc: AirlockService = Depends(get_service)):
    raw, key_hash, prefix = kgkeys.new_key()
    row = svc.registry.create_kg_key(kgkeys.new_id(), req.name, key_hash, prefix)
    out = _kg_key_public(row)
    out["key"] = raw  # nur EINMAL im Klartext
    out["note"] = "Dieser Key wird nur einmal angezeigt – jetzt kopieren."
    return out


@app.get("/v1/kg/keys", dependencies=[Depends(require_api_key)], tags=["kg"])
def kg_key_list(svc: AirlockService = Depends(get_service)):
    return [_kg_key_public(r) for r in svc.registry.list_kg_keys()]


@app.post("/v1/kg/keys/{key_id}/revoke", dependencies=[Depends(require_api_key)], tags=["kg"])
def kg_key_revoke(key_id: str, svc: AirlockService = Depends(get_service)):
    if not svc.registry.revoke_kg_key(key_id):
        raise HTTPException(404, "KG-Key nicht gefunden.")
    return {"ok": True, "id": key_id}


@app.post("/v1/kg/keys/{key_id}/regenerate", dependencies=[Depends(require_api_key)], tags=["kg"])
def kg_key_regenerate(key_id: str, svc: AirlockService = Depends(get_service)):
    old = svc.registry.get_kg_key(key_id)
    if old is None:
        raise HTTPException(404, "KG-Key nicht gefunden.")
    svc.registry.revoke_kg_key(key_id)
    raw, key_hash, prefix = kgkeys.new_key()
    row = svc.registry.create_kg_key(kgkeys.new_id(), old["name"], key_hash, prefix)
    out = _kg_key_public(row)
    out["key"] = raw
    out["replaced"] = key_id
    out["note"] = "Neuer Key – nur einmal sichtbar. Der bisherige ist ungueltig."
    return out


@app.get("/v1/kg/log", dependencies=[Depends(require_api_key)], tags=["kg"])
def kg_log(limit: int = Query(200, ge=1, le=kglog.MAX_ENTRIES)):
    return {"entries": kglog.entries(limit), "max": kglog.MAX_ENTRIES}


@app.post("/v1/kg/log:clear", dependencies=[Depends(require_api_key)], tags=["kg"])
def kg_log_clear():
    kglog.clear()
    return {"ok": True}


# ---- Writer-Keys: native NFC-Writer-App (nur voller Key) -------------
def _writer_key_public(r) -> dict:
    return {
        "id": r["id"], "name": r["name"], "key_prefix": r["key_prefix"],
        "created_at": r["created_at"], "last_used_at": r["last_used_at"],
        "revoked_at": r["revoked_at"], "active": r["revoked_at"] is None,
    }


@app.post("/v1/writer/keys", dependencies=[Depends(require_api_key)], tags=["writer"])
def writer_key_create(req: WriterKeyCreate, svc: AirlockService = Depends(get_service)):
    raw, key_hash, prefix = writerkeys.new_key()
    row = svc.registry.create_writer_key(writerkeys.new_id(), req.name, key_hash, prefix)
    out = _writer_key_public(row)
    out["key"] = raw  # nur EINMAL im Klartext
    out["note"] = "Dieser Key wird nur einmal angezeigt – jetzt in die Writer-App uebernehmen."
    return out


@app.get("/v1/writer/keys", dependencies=[Depends(require_api_key)], tags=["writer"])
def writer_key_list(svc: AirlockService = Depends(get_service)):
    return [_writer_key_public(r) for r in svc.registry.list_writer_keys()]


@app.post("/v1/writer/keys/{key_id}/revoke", dependencies=[Depends(require_api_key)], tags=["writer"])
def writer_key_revoke(key_id: str, svc: AirlockService = Depends(get_service)):
    if not svc.registry.revoke_writer_key(key_id):
        raise HTTPException(404, "Writer-Key nicht gefunden.")
    return {"ok": True, "id": key_id}


@app.post("/v1/writer/keys/{key_id}/regenerate", dependencies=[Depends(require_api_key)], tags=["writer"])
def writer_key_regenerate(key_id: str, svc: AirlockService = Depends(get_service)):
    old = svc.registry.get_writer_key(key_id)
    if old is None:
        raise HTTPException(404, "Writer-Key nicht gefunden.")
    svc.registry.revoke_writer_key(key_id)
    raw, key_hash, prefix = writerkeys.new_key()
    row = svc.registry.create_writer_key(writerkeys.new_id(), old["name"], key_hash, prefix)
    out = _writer_key_public(row)
    out["key"] = raw
    out["replaced"] = key_id
    out["note"] = "Neuer Key – nur einmal sichtbar. Der bisherige ist ungueltig."
    return out


# ---- NFC-Secret verwalten (voller Key) -------------------------------
@app.get("/v1/nfc/secret/status", dependencies=[Depends(require_api_key)], tags=["nfc"])
def nfc_secret_status(svc: AirlockService = Depends(get_service)):
    return svc.nfc_secret_status()


@app.post("/v1/nfc/secret/generate", dependencies=[Depends(require_api_key)], tags=["nfc"])
def nfc_secret_generate(req: NfcSecretGenerate, svc: AirlockService = Depends(get_service)):
    st = svc.nfc_secret_status()
    if st["env_override"]:
        raise HTTPException(409, "AIRLOCK_NFC_SECRET ist per ENV gesetzt und hat "
                                 "Vorrang – DB-Verwaltung ist deaktiviert.")
    if not req.confirm:
        raise HTTPException(400, "Bestaetigung erforderlich (confirm=true): Ein neues "
                                 "Secret macht ALLE bereits beschriebenen Tags ungueltig.")
    secret = secrets.token_hex(32)  # 256 Bit
    svc.set_nfc_secret(secret)
    out = svc.nfc_secret_status()
    out["secret"] = secret  # nur EINMAL im Klartext
    out["note"] = "Secret wird nur einmal angezeigt – jetzt sichern (Backup exportieren)."
    return out


@app.post("/v1/nfc/secret/backup", dependencies=[Depends(require_api_key)], tags=["nfc"])
def nfc_secret_backup(req: NfcSecretBackupRequest, svc: AirlockService = Depends(get_service)):
    secret = svc.effective_nfc_secret()
    if nfclib.secret_is_default(secret):
        raise HTTPException(409, "Kein echtes Secret gesetzt – zuerst erzeugen.")
    try:
        blob = secretbackup.export_backup(secret, req.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"filename": "airlock-nfc-secret.backup.json", "backup": blob}


@app.post("/v1/nfc/secret/restore", dependencies=[Depends(require_api_key)], tags=["nfc"])
def nfc_secret_restore(req: NfcSecretRestoreRequest, svc: AirlockService = Depends(get_service)):
    if svc.nfc_secret_status()["env_override"]:
        raise HTTPException(409, "AIRLOCK_NFC_SECRET ist per ENV gesetzt – "
                                 "DB-Verwaltung ist deaktiviert.")
    if not req.confirm:
        raise HTTPException(400, "Bestaetigung erforderlich (confirm=true): Das ersetzt "
                                 "das aktuelle Secret.")
    try:
        secret = secretbackup.import_backup(req.backup, req.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    svc.set_nfc_secret(secret)
    return svc.nfc_secret_status()


# ---- Helpers ----------------------------------------------------------
def _norm(code: str) -> str:
    try:
        return validate_code(code, settings.code_length)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _airlock_row_to_out(r) -> dict:
    keys = r.keys()
    return {
        "code": r["code"], "status": r["status"], "source": r["source"],
        "batch_id": r["batch_id"], "stl_sha256": r["stl_sha256"],
        "stl_url": f"/v1/airlocks/{r['code']}/stl", "created_at": r["created_at"],
        "nfc_uid": (r["nfc_uid"] if "nfc_uid" in keys else None),
        "nfc_written_at": (r["nfc_written_at"] if "nfc_written_at" in keys else None),
    }
