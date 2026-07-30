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
    nfc_uid: Optional[str] = None
    nfc_written_at: Optional[str] = None


class BatchOut(BaseModel):
    batch_id: str
    status: str
    count: int
    airlocks: list[AirlockOut] = []
    zip_url: Optional[str] = None
    conflicts: list[str] = Field(default_factory=list, description="Vorgegebene, bereits vergebene Codes")


class ThreeMFRequest(BaseModel):
    """Mehrfarb-Export: entweder `codes` ODER `batch_id`."""
    codes: Optional[list[str]] = Field(default=None, description="Konkrete Codes für den Export")
    batch_id: Optional[str] = Field(default=None, description="Alle Airlocks dieses Batches exportieren")
    format: str = Field(default="3mf", description="Ausgabeformat: '3mf' (Farbe) oder 'obj' (Farbe)")
    plate: Optional[float] = Field(default=None, gt=0, description="Bauplatten-Kantenlänge in mm (Default 256)")
    margin: Optional[float] = Field(default=None, ge=0, description="Randabstand in mm")
    gap: Optional[float] = Field(default=None, ge=0, description="Lücke zwischen den Teilen in mm")

    @field_validator("format")
    @classmethod
    def _fmt_ok(cls, v: str) -> str:
        v = (v or "3mf").lower()
        if v not in ("3mf", "obj"):
            raise ValueError("format muss '3mf' oder 'obj' sein.")
        return v

    @model_validator(mode="after")
    def _exactly_one(self):
        if bool(self.codes) == bool(self.batch_id):
            raise ValueError("Genau eines von 'codes' oder 'batch_id' angeben.")
        return self


class NfcPrepareRequest(BaseModel):
    """UID des (leeren) Tags, für den ein signierter Payload erzeugt werden soll."""
    uid: str = Field(description="Tag-UID (Hex), z. B. vom Reader gelesen")


class NfcCommitRequest(BaseModel):
    """Bestätigt, dass der Tag mit dieser UID beschrieben wurde."""
    uid: str = Field(description="Tag-UID (Hex)")


class NfcVerifyRequest(BaseModel):
    """Verifikation durch den KG-Tracker: UID + Token vom gelesenen Tag."""
    uid: str = Field(description="Tag-UID (Hex)")
    token: str = Field(description="Token aus dem NDEF-Record")
    require_status: Optional[str] = Field(
        default=None,
        description="Wenn gesetzt, muss der Airlock genau diesen Status haben (z. B. 'active').",
    )


class KgKeyCreate(BaseModel):
    """Erzeugt einen eingeschraenkten KG-Tracker-Key."""
    name: str = Field(default="KG-Tracker", max_length=64,
                      description="Anzeigename zur Wiedererkennung")


class WriterKeyCreate(BaseModel):
    """Erzeugt einen Writer-Key fuer die native NFC-Writer-App."""
    name: str = Field(default="Writer", max_length=64,
                      description="Anzeigename zur Wiedererkennung (z. B. iPhone Werkstatt)")


class NfcSecretGenerate(BaseModel):
    """Erzeugt/rotiert das NFC-Secret (macht bestehende Tags ungueltig!)."""
    confirm: bool = Field(default=False, description="Muss true sein (Bestaetigung).")


class NfcSecretBackupRequest(BaseModel):
    """Verschluesseltes Backup des aktuellen NFC-Secrets exportieren."""
    password: str = Field(min_length=1, description="Passwort zum Schutz der Backup-Datei")


class NfcSecretRestoreRequest(BaseModel):
    """Secret aus einem verschluesselten Backup wiederherstellen."""
    password: str = Field(min_length=1)
    backup: str = Field(min_length=1, description="Inhalt der Backup-Datei")
    confirm: bool = Field(default=False, description="Muss true sein (Bestaetigung).")


class StatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in STATUSES:
            raise ValueError(f"Status muss einer von {STATUSES} sein.")
        return v
