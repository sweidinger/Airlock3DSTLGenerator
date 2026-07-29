"""Pydantic-Schemas fuer die REST-API."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .registry import STATUSES


class GenerateRequest(BaseModel):
    """Batch-Auftrag: entweder `count` (Auto-Vergabe) ODER `codes` (Vorgabe)."""
    count: Optional[int] = Field(default=None, ge=1, description="Anzahl automatisch zu vergebender Codes")
    codes: Optional[list[str]] = Field(default=None, description="Konkret vorgegebene Codes")
    requested_by: str = Field(default="kg-tracker", max_length=64)
    return_zip: bool = Field(default=True, description="ZIP-URL in der Antwort bereitstellen")

    @model_validator(mode="after")
    def _exactly_one(self):
        if bool(self.count) == bool(self.codes):
            raise ValueError("Genau eines von 'count' oder 'codes' angeben.")
        return self


class AirlockOut(BaseModel):
    code: str
    status: str
    source: str
    batch_id: Optional[str] = None
    stl_url: Optional[str] = None
    stl_sha256: Optional[str] = None
    created_at: Optional[str] = None


class BatchOut(BaseModel):
    batch_id: str
    status: str
    count: int
    airlocks: list[AirlockOut] = []
    zip_url: Optional[str] = None
    conflicts: list[str] = Field(default_factory=list, description="Vorgegebene, bereits vergebene Codes")


class StatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in STATUSES:
            raise ValueError(f"Status muss einer von {STATUSES} sein.")
        return v
