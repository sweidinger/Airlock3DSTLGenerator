"""FastAPI-App: REST-Schnittstelle des Airlock-Generators."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from . import nfc as nfclib
from .auth import require_api_key
from .config import settings
from .generator import validate_code
from .models import (AirlockOut, BatchOut, GenerateRequest, NfcCommitRequest,
                     NfcPrepareRequest, NfcVerifyRequest, StatusUpdate, ThreeMFRequest)
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
         dependencies=[Depends(require_api_key)], tags=["airlocks"])
def list_airlocks(status: str | None = None, batch_id: str | None = None,
                  limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                  svc: AirlockService = Depends(get_service)):
    rows = svc.registry.list_airlocks(status=status, batch_id=batch_id, limit=limit, offset=offset)
    return [_airlock_row_to_out(r) for r in rows]


@app.get("/v1/airlocks/{code}", response_model=AirlockOut,
         dependencies=[Depends(require_api_key)], tags=["airlocks"])
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
           dependencies=[Depends(require_api_key)], tags=["airlocks"])
def update_status(code: str, upd: StatusUpdate, svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    try:
        r = svc.registry.update_status(code, upd.status)
    except KeyError:
        raise HTTPException(404, f"Airlock {code} nicht gefunden.")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _airlock_row_to_out(r)


# ---- NFC-Tag (signierter Token gebunden an Tag-UID) ------------------
@app.post("/v1/airlocks/{code}/nfc/prepare", dependencies=[Depends(require_api_key)], tags=["nfc"])
def nfc_prepare(code: str, req: NfcPrepareRequest, svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    if svc.registry.get_airlock(code) is None:
        raise HTTPException(404, f"Airlock {code} nicht gefunden.")
    try:
        payload = nfclib.make_payload(code, req.uid, settings.nfc_secret)
    except ValueError as e:
        raise HTTPException(422, str(e))
    payload["secret_configured"] = not nfclib.secret_is_default(settings.nfc_secret)
    return payload


@app.post("/v1/airlocks/{code}/nfc/commit", dependencies=[Depends(require_api_key)], tags=["nfc"])
def nfc_commit(code: str, req: NfcCommitRequest, svc: AirlockService = Depends(get_service)):
    code = _norm(code)
    try:
        uid = nfclib.normalize_uid(req.uid)
    except ValueError as e:
        raise HTTPException(422, str(e))
    try:
        r = svc.registry.set_nfc(code, uid)
    except KeyError:
        raise HTTPException(404, f"Airlock {code} nicht gefunden.")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _airlock_row_to_out(r)


@app.post("/v1/airlocks/{code}/nfc/verify", dependencies=[Depends(require_api_key)], tags=["nfc"])
def nfc_verify(code: str, req: NfcVerifyRequest, svc: AirlockService = Depends(get_service)):
    """Für den KG-Tracker: prüft Signatur, UID-Bindung und Status."""
    code = _norm(code)
    r = svc.registry.get_airlock(code)
    if r is None:
        return {"valid": False, "reason": "unknown_code"}
    try:
        uid = nfclib.normalize_uid(req.uid)
    except ValueError:
        return {"valid": False, "reason": "bad_uid"}
    if not nfclib.verify(code, uid, req.token, settings.nfc_secret):
        return {"valid": False, "reason": "bad_signature"}
    bound = r["nfc_uid"]
    if bound and bound != uid:
        return {"valid": False, "reason": "uid_mismatch", "bound_uid": bound}
    if r["status"] in ("retired", "voided"):
        return {"valid": False, "reason": f"status_{r['status']}", "status": r["status"]}
    return {"valid": True, "code": code, "uid": uid, "status": r["status"],
            "bound_uid": bound}


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
