"""Erzeugung und Pruefung der Writer-API-Keys (native NFC-Writer-App).

Ein Writer-Key darf Airlocks lesen und NFC-Tags beschreiben (prepare/commit) –
aber nicht generieren, herunterladen, den Status wechseln oder verifizieren.
Gedacht fuer eine dedizierte iOS-App pro Geraet: least privilege, einzeln
widerrufbar. Keys werden ausschliesslich als SHA-256-Hash gespeichert und beim
Erzeugen genau einmal im Klartext angezeigt.
"""
from __future__ import annotations

import hashlib
import secrets

PREFIX = "alw_"
_PREFIX_SHOW = 12  # sichtbares Praefix (alw_ + 8 Hex) zur Wiedererkennung


def new_key() -> tuple[str, str, str]:
    """Erzeugt (klartext, key_hash, key_prefix)."""
    raw = PREFIX + secrets.token_hex(20)  # 40 Hex -> 160 Bit
    return raw, hash_key(raw), raw[:_PREFIX_SHOW]


def hash_key(key: str) -> str:
    return hashlib.sha256((key or "").strip().encode("utf-8")).hexdigest()


def looks_like_writer_key(key: str | None) -> bool:
    return bool(key) and key.strip().startswith(PREFIX)


def new_id() -> str:
    return secrets.token_hex(6)
