"""Orchestrierung eines Batch-Auftrags: Vergabe -> Rendern -> ZIP."""
from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

from .config import settings
from .generator import Generator, validate_code
from .registry import Registry


class AirlockService:
    def __init__(self, registry: Registry | None = None, generator: Generator | None = None):
        self.cfg = settings
        self.registry = registry or Registry(settings.db_path, settings.code_length)
        self.generator = generator or Generator()

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
