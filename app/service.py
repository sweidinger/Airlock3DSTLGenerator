"""Orchestrierung eines Batch-Auftrags: Vergabe -> Rendern -> ZIP."""
from __future__ import annotations

import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from . import nfc as nfclib
from .config import settings
from .generator import Generator, validate_code
from .registry import Registry
from .threemf import Airlock3MFItem, build_3mf, build_obj


class AirlockService:
    def __init__(self, registry: Registry | None = None, generator: Generator | None = None):
        self.cfg = settings
        self.registry = registry or Registry(settings.db_path, settings.code_length)
        self.generator = generator or Generator()

    # ---- NFC-Secret: ENV-Override > DB > Default ----------------------
    def effective_nfc_secret(self) -> str:
        """Das tatsaechlich verwendete NFC-Secret.

        Reihenfolge: gesetzte ENV `AIRLOCK_NFC_SECRET` (Override) > in der DB
        hinterlegtes Secret > Default. So kann das Secret im Dashboard verwaltet
        werden, ohne eine bestehende ENV-Konfiguration zu entwerten.
        """
        env = settings.nfc_secret
        if env and not nfclib.secret_is_default(env):
            return env
        db = self.registry.get_kv("nfc_secret")
        if db:
            return db
        return env

    def nfc_secret_status(self) -> dict:
        env = settings.nfc_secret
        env_set = bool(env) and not nfclib.secret_is_default(env)
        db = self.registry.get_kv("nfc_secret")
        if env_set:
            source = "env"
        elif db:
            source = "db"
        else:
            source = "default"
        return {
            "configured": env_set or bool(db),
            "source": source,
            "env_override": env_set,
            "updated_at": self.registry.get_kv_updated("nfc_secret"),
            "bound_tags": self.registry.count_nfc_bound(),
        }

    def set_nfc_secret(self, secret: str) -> None:
        self.registry.set_kv("nfc_secret", secret)

    def _new_batch_id(self) -> str:
        return "b_" + uuid.uuid4().hex[:10]

    def generate(self, *, count: int | None, codes: list[str] | None,
                 requested_by: str, return_zip: bool,
                 idempotency_key: str | None = None) -> dict:
        # Idempotenz: gleicher Key -> vorhandenen Batch zurueckgeben
        if idempotency_key:
            existing = self.registry.find_batch_by_idempotency(idempotency_key)
            if existing:
                return self._batch_view(existing["batch_id"], return_zip)

        conflicts: list[str] = []
        if codes is not None:
            normalized = [validate_code(c, self.cfg.code_length) for c in codes]
            free, conflicts = self.registry.check_provided(normalized)
            chosen, source = free, "provided"
        else:
            chosen, source = self.registry.allocate_auto(int(count)), "auto"

        batch_id = self._new_batch_id()
        self.registry.create_batch(batch_id, len(chosen), requested_by, idempotency_key)

        rendered_paths: list[Path] = []
        for code in chosen:
            self.registry.add_airlock(code, batch_id, source, requested_by)
            res = self.generator.render(code)  # schreibt ins Output-Volume
            self.registry.mark_generated(code, str(res.path), res.sha256)
            rendered_paths.append(res.path)

        zip_path = None
        if return_zip and rendered_paths:
            zip_path = self._make_zip(batch_id, rendered_paths)

        batch_status = "completed"
        if codes is not None and conflicts:
            batch_status = "partial" if chosen else "failed"
        self.registry.finish_batch(batch_id, batch_status, str(zip_path) if zip_path else None)

        view = self._batch_view(batch_id, return_zip)
        view["conflicts"] = conflicts
        view["status"] = batch_status
        return view

    def build_threemf(self, *, codes: list[str] | None = None, batch_id: str | None = None,
                      requested_by: str = "dashboard", fmt: str = "3mf",
                      plate: float | None = None, margin: float | None = None,
                      gap: float | None = None) -> dict:
        """Erzeugt einen Mehrfarb-Export (Body schwarz, Code weiß) im Raster.

        `fmt`: "3mf" (Pro-Dreieck-Farbe, m:colorgroup) oder "obj" (Per-Vertex-Farbe).
        Beide liest Bambu Studio als zweifarbig ein. Codes kommen direkt oder aus
        einem Batch; Body- und Code-Teil werden je Code frisch gerendert.
        """
        fmt = (fmt or "3mf").lower()
        if fmt not in ("3mf", "obj", "p1s"):
            raise ValueError("format muss '3mf', 'obj' oder 'p1s' sein.")
        if batch_id:
            rows = self.registry.airlocks_of_batch(batch_id)
            code_list = [r["code"] for r in rows]
            if not code_list:
                raise ValueError(f"Batch {batch_id} enthält keine Airlocks.")
        elif codes:
            # Reihenfolge erhalten, Duplikate entfernen
            seen: set[str] = set()
            code_list = []
            for c in codes:
                cc = validate_code(c, self.cfg.code_length)
                if cc not in seen:
                    seen.add(cc)
                    code_list.append(cc)
        else:
            raise ValueError("codes oder batch_id angeben.")

        tmpdir = Path(tempfile.mkdtemp(prefix="airlock3mf_"))
        try:
            items: list[Airlock3MFItem] = []
            for c in code_list:
                bp = tmpdir / f"{c}_body.stl"
                cp = tmpdir / f"{c}_code.stl"
                self.generator.render(c, bp, part="body")
                self.generator.render(c, cp, part="code")
                items.append(Airlock3MFItem(c, bp, cp))

            out_dir = Path(self.cfg.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            token = "tmf_" + uuid.uuid4().hex[:12]

            if fmt == "p1s":
                # Druckfertiges Bambu-P1S-Projekt: zweifarbig + Pause bei 3 mm.
                from .p1s_project import build_p1s_project_3mf
                out_path = out_dir / f"{token}.3mf"
                pres = build_p1s_project_3mf(items, out_path)
                data = out_path.read_bytes()
                return {
                    "file": out_path.name,
                    "format": "p1s",
                    "download_url": f"/v1/threemf/{out_path.name}",
                    "count": pres.count,
                    "codes": code_list,
                    "cols": pres.cols,
                    "rows": pres.rows,
                    "plate": 256.0,
                    "fits_on_plate": pres.fits,
                    "printer": "Bambu Lab P1S 0.4",
                    "pause_at_mm": 3.0,
                    "sha256": __import__("hashlib").sha256(data).hexdigest(),
                    "bytes": len(data),
                }

            out_path = out_dir / f"{token}.{fmt}"
            builder = build_obj if fmt == "obj" else build_3mf
            res = builder(
                items, out_path,
                plate=plate if plate is not None else self.cfg.threemf_plate,
                margin=margin if margin is not None else self.cfg.threemf_margin,
                gap=gap if gap is not None else self.cfg.threemf_gap,
                color_body=self.cfg.threemf_color_body,
                color_code=self.cfg.threemf_color_code,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        return {
            "file": out_path.name,
            "format": fmt,
            "download_url": f"/v1/threemf/{out_path.name}",
            "count": res.count,
            "codes": code_list,
            "cols": res.cols,
            "rows": res.rows,
            "plate": res.plate,
            "fits_on_plate": res.fits_on_plate,
            "item_size_mm": [round(res.item_w, 2), round(res.item_h, 2)],
            "colors": {"lock": self.cfg.threemf_color_body, "code": self.cfg.threemf_color_code},
            "sha256": res.sha256,
            "bytes": res.bytes,
        }

    def _make_zip(self, batch_id: str, paths: list[Path]) -> Path:
        out_dir = Path(self.cfg.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_path = out_dir / f"{batch_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in paths:
                zf.write(p, arcname=p.name)
        return zip_path

    def _batch_view(self, batch_id: str, return_zip: bool) -> dict:
        b = self.registry.get_batch(batch_id)
        rows = self.registry.airlocks_of_batch(batch_id)
        airlocks = [{
            "code": r["code"], "status": r["status"], "source": r["source"],
            "batch_id": r["batch_id"], "stl_sha256": r["stl_sha256"],
            "stl_url": f"/v1/airlocks/{r['code']}/stl", "created_at": r["created_at"],
        } for r in rows]
        return {
            "batch_id": batch_id,
            "status": b["status"] if b else "unknown",
            "count": len(airlocks),
            "airlocks": airlocks,
            "zip_url": (f"/v1/batches/{batch_id}/zip" if (return_zip and b and b["zip_path"]) else None),
            "conflicts": [],
        }
