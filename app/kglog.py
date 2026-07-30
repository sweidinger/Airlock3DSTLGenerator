"""In-Memory-Debug-Log der KG-Tracker-API-Zugriffe (Ringpuffer, letzte N).

Bewusst fluechtig: nach einem Neustart/Update ist der Log leer. Enthaelt NIE den
Key selbst – nur ein sichtbares Praefix und den vergebenen Namen. Dient dazu, die
Anfragen der KG-Tracker-App im Dashboard mitzulesen.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

MAX_ENTRIES = 500

_buf: "deque[dict]" = deque(maxlen=MAX_ENTRIES)
_lock = threading.Lock()
_seq = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add(*, method: str, path: str, status: int, key_id: str | None,
        key_prefix: str | None, key_name: str | None,
        client: str | None, note: str | None = None) -> None:
    global _seq
    with _lock:
        _seq += 1
        _buf.append({
            "seq": _seq, "ts": _now(), "method": method, "path": path,
            "status": status, "key_id": key_id, "key_prefix": key_prefix,
            "key_name": key_name, "client": client, "note": note,
        })


def entries(limit: int = 200) -> list[dict]:
    with _lock:
        items = list(_buf)
    items.reverse()  # neueste zuerst
    return items[:limit]


def clear() -> None:
    with _lock:
        _buf.clear()
