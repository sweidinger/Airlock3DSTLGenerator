"""NFC-Signierung: bindet einen Airlock-Code kryptografisch an eine Tag-UID.

Jeder NTAG hat eine ab Werk eindeutige UID. Wir schreiben in den Tag einen
signierten Token ``HMAC(secret, code|uid)`` und speichern die UID in der
Registry. Verifikation (später im KG-Tracker) liest UID (Hardware) + Code+Token
(NDEF) und prüft die Signatur gegen dieselbe UID.

Dadurch:
  * Fälschung  -> ausgeschlossen: ohne `secret` kein gültiger Token.
  * Duplizieren -> auffällig: ein Nachdruck hat eine ANDERE Tag-UID, der Token
    passt nicht mehr; zusätzlich ist der Code in der Registry nur für EINE
    aktive Schließung gültig.

Der NDEF-Inhalt ist ein kompakter Text-Record: ``AL1|<code>|<token>``.
"""
from __future__ import annotations

import hmac
import re
from hashlib import sha256

# Token-Länge in Hex-Zeichen (128 Bit = 32 Zeichen). Reicht als Signatur und
# passt locker in NTAG213 (144 Byte Nutzspeicher).
_TOKEN_HEX = 32
_NDEF_PREFIX = "AL1"


def normalize_uid(uid: str) -> str:
    """UID vereinheitlichen: nur Hex, Grossbuchstaben, ohne Trenner."""
    if not uid:
        raise ValueError("Leere Tag-UID.")
    u = re.sub(r"[^0-9a-fA-F]", "", uid).upper()
    if not (8 <= len(u) <= 20) or len(u) % 2 != 0:
        raise ValueError(f"Ungültige Tag-UID: {uid!r}")
    return u


def sign(code: str, uid: str, secret: str) -> str:
    """Signierter Token für (code, uid) -> Hex-String."""
    u = normalize_uid(uid)
    msg = f"{code}|{u}".encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), msg, sha256).hexdigest()
    return mac[:_TOKEN_HEX]


def verify(code: str, uid: str, token: str, secret: str) -> bool:
    """Prüft den Token zeitkonstant."""
    try:
        expected = sign(code, uid, secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, (token or "").strip().lower())


def ndef_text(code: str, token: str) -> str:
    """Kompakter NDEF-Text-Record-Inhalt für den Tag."""
    return f"{_NDEF_PREFIX}|{code}|{token}"


def parse_ndef_text(text: str) -> tuple[str, str] | None:
    """Zerlegt ``AL1|<code>|<token>`` -> (code, token) oder None."""
    parts = (text or "").strip().split("|")
    if len(parts) == 3 and parts[0] == _NDEF_PREFIX:
        return parts[1], parts[2]
    return None


def make_payload(code: str, uid: str, secret: str) -> dict:
    """Alles, was der Client zum Schreiben braucht."""
    u = normalize_uid(uid)
    token = sign(code, u, secret)
    return {
        "code": code,
        "uid": u,
        "token": token,
        "ndef_text": ndef_text(code, token),
    }


def secret_is_default(secret: str) -> bool:
    return secret.strip() in ("", "change-me-nfc-secret")
