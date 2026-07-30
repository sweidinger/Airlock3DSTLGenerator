"""Passwortgeschuetztes Backup des NFC-Secrets.

Das Secret selbst ist ein starkes Zufalls-Secret; das Passwort verschluesselt
nur die exportierte Backup-Datei (scrypt-Schluesselableitung + AES-256-GCM).
So bleibt das Secret kryptografisch stark und die Backup-Datei kann gefahrlos
abgelegt werden.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_AAD = b"airlock-nfc-secret-backup-v1"
_N = 2 ** 15  # scrypt Kostenparameter


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _derive(password: str, salt: bytes) -> bytes:
    # maxmem grosszuegig setzen: scrypt(n=2^15, r=8) braucht ~32 MB und liegt sonst
    # genau am OpenSSL-Default-Limit ("memory limit exceeded").
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=8, p=1, dklen=32,
        maxmem=128 * 1024 * 1024,
    )


def export_backup(secret: str, password: str) -> str:
    """Verschluesselt `secret` unter `password` -> JSON-Backup-String."""
    if not password:
        raise ValueError("Passwort fehlt.")
    if not secret:
        raise ValueError("Kein Secret zum Sichern.")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive(password, salt)
    ct = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), _AAD)
    return json.dumps({
        "format": "airlock-nfc-secret-backup",
        "v": 1, "kdf": "scrypt", "n": _N,
        "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct),
    }, indent=2)


def import_backup(blob: str, password: str) -> str:
    """Entschluesselt ein Backup -> Secret (Klartext). Fehler bei falschem PW."""
    if not password:
        raise ValueError("Passwort fehlt.")
    try:
        d = json.loads(blob)
        salt = _ub64(d["salt"]); nonce = _ub64(d["nonce"]); ct = _ub64(d["ct"])
    except Exception:
        raise ValueError("Backup-Datei ungueltig oder unlesbar.")
    key = _derive(password, salt)
    try:
        pt = AESGCM(key).decrypt(nonce, ct, _AAD)
    except Exception:
        raise ValueError("Falsches Passwort oder beschaedigtes Backup.")
    return pt.decode("utf-8")
