"""SQLite-Registry: Code-Vergabe, Batches, Status-Lebenszyklus.

Die Registry ist die generator-eigene Absicherung gegen Doppelvergabe.
Die finale Hoheit ueber Eindeutigkeit liegt bei KG-Tracker (Source-of-Truth).
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Erlaubte Statuswerte (Lebenszyklus)
STATUSES = (
    "reserved", "generated", "printed", "registered", "active", "retired", "voided",
)
_TERMINAL = {"retired", "voided"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CodeExhaustionError(RuntimeError):
    """Kein freier Code mehr im Nummernraum verfuegbar."""


class Registry:
    def __init__(self, db_path: str | Path, code_length: int = 5):
        self.db_path = Path(db_path)
        self.code_length = code_length
        self.code_space = 10 ** code_length
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id        TEXT PRIMARY KEY,
                    count           INTEGER NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    zip_path        TEXT,
                    idempotency_key TEXT UNIQUE,
                    requested_by    TEXT,
                    created_at      TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS airlocks (
                    code         TEXT PRIMARY KEY,
                    batch_id     TEXT REFERENCES batches(batch_id),
                    status       TEXT NOT NULL DEFAULT 'reserved',
                    stl_path     TEXT,
                    stl_sha256   TEXT,
                    source       TEXT NOT NULL DEFAULT 'auto',
                    requested_by TEXT,
                    created_at   TEXT NOT NULL,
                    metadata     TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_airlocks_batch  ON airlocks(batch_id);
                CREATE INDEX IF NOT EXISTS idx_airlocks_status ON airlocks(status);
                """
            )
            # Migration: NFC-Spalten nachrüsten, falls DB älter ist.
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(airlocks)")}
            if "nfc_uid" not in cols:
                self._conn.execute("ALTER TABLE airlocks ADD COLUMN nfc_uid TEXT")
            if "nfc_written_at" not in cols:
                self._conn.execute("ALTER TABLE airlocks ADD COLUMN nfc_written_at TEXT")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_airlocks_nfcuid ON airlocks(nfc_uid)"
            )
            # Eingeschraenkte API-Keys fuer die KG-Tracker-App (nur Hash gespeichert).
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS kg_api_keys (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    key_hash     TEXT NOT NULL UNIQUE,
                    key_prefix   TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at   TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_kgkeys_hash ON kg_api_keys(key_hash);
                CREATE TABLE IF NOT EXISTS app_kv (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TEXT
                );
                """
            )

    # ---- Code-Vergabe -------------------------------------------------
    def _exists(self, code: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM airlocks WHERE code = ?", (code,))
        return cur.fetchone() is not None

    def count_used(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM airlocks").fetchone()[0]

    def allocate_auto(self, count: int) -> list[str]:
        """Zieht `count` garantiert freie Zufallscodes und reserviert sie NICHT
        (nur Kandidaten). Aufrufer legt sie anschliessend im Batch an."""
        with self._lock:
            used = self.count_used()
            if used + count > self.code_space:
                raise CodeExhaustionError(
                    f"Nur {self.code_space - used} freie Codes, {count} angefordert."
                )
            picked: set[str] = set()
            attempts = 0
            max_attempts = max(10000, count * 50)
            while len(picked) < count and attempts < max_attempts:
                attempts += 1
                cand = str(secrets.randbelow(self.code_space)).zfill(self.code_length)
                if cand in picked or self._exists(cand):
                    continue
                picked.add(cand)
            if len(picked) < count:
                raise CodeExhaustionError(
                    "Konnte nicht genug freie Codes ziehen (Nummernraum fast voll)."
                )
            return sorted(picked)

    def check_provided(self, codes: Iterable[str]) -> tuple[list[str], list[str]]:
        """Teilt vorgegebene Codes in (frei, konflikt)."""
        free, conflict = [], []
        with self._lock:
            for c in codes:
                (conflict if self._exists(c) else free).append(c)
        return free, conflict

    # ---- Batches / Airlocks ------------------------------------------
    def find_batch_by_idempotency(self, key: str) -> sqlite3.Row | None:
        if not key:
            return None
        return self._conn.execute(
            "SELECT * FROM batches WHERE idempotency_key = ?", (key,)
        ).fetchone()

    def create_batch(self, batch_id: str, count: int, requested_by: str | None,
                     idempotency_key: str | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO batches(batch_id,count,status,idempotency_key,requested_by,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (batch_id, count, "pending", idempotency_key, requested_by, _now()),
            )

    def add_airlock(self, code: str, batch_id: str, source: str,
                    requested_by: str | None, metadata: dict | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO airlocks(code,batch_id,status,source,requested_by,created_at,metadata)"
                " VALUES(?,?,?,?,?,?,?)",
                (code, batch_id, "reserved", source, requested_by, _now(),
                 json.dumps(metadata or {})),
            )

    def mark_generated(self, code: str, stl_path: str, sha256: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE airlocks SET status='generated', stl_path=?, stl_sha256=? WHERE code=?",
                (stl_path, sha256, code),
            )

    def finish_batch(self, batch_id: str, status: str, zip_path: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE batches SET status=?, zip_path=? WHERE batch_id=?",
                (status, zip_path, batch_id),
            )

    def update_status(self, code: str, status: str) -> sqlite3.Row:
        if status not in STATUSES:
            raise ValueError(f"Ungueltiger Status: {status}")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE airlocks SET status=? WHERE code=?", (status, code)
            )
            if cur.rowcount == 0:
                raise KeyError(code)
        return self.get_airlock(code)

    # ---- NFC ----------------------------------------------------------
    def get_by_nfc_uid(self, uid: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM airlocks WHERE nfc_uid = ?", (uid,)
        ).fetchone()

    def set_nfc(self, code: str, uid: str) -> sqlite3.Row:
        """Bindet eine Tag-UID an einen Code. Fehler bei Konflikt/Unbekannt."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT code FROM airlocks WHERE code=?", (code,)
            ).fetchone()
            if row is None:
                raise KeyError(code)
            other = self._conn.execute(
                "SELECT code FROM airlocks WHERE nfc_uid=? AND code<>?", (uid, code)
            ).fetchone()
            if other is not None:
                raise ValueError(f"Tag-UID bereits an Code {other['code']} gebunden.")
            self._conn.execute(
                "UPDATE airlocks SET nfc_uid=?, nfc_written_at=? WHERE code=?",
                (uid, _now(), code),
            )
        return self.get_airlock(code)

    # ---- KG-Tracker-API-Keys -----------------------------------------
    def create_kg_key(self, key_id: str, name: str, key_hash: str,
                      key_prefix: str) -> sqlite3.Row:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO kg_api_keys(id,name,key_hash,key_prefix,created_at)"
                " VALUES(?,?,?,?,?)",
                (key_id, name, key_hash, key_prefix, _now()),
            )
        return self.get_kg_key(key_id)

    def get_kg_key(self, key_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM kg_api_keys WHERE id = ?", (key_id,)
        ).fetchone()

    def list_kg_keys(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM kg_api_keys ORDER BY created_at DESC"
        ).fetchall()

    def find_active_kg_key_by_hash(self, key_hash: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM kg_api_keys WHERE key_hash = ? AND revoked_at IS NULL",
            (key_hash,),
        ).fetchone()

    def revoke_kg_key(self, key_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE kg_api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (_now(), key_id),
            )
            if cur.rowcount:
                return True
            # Auch schon-widerrufene/existente Keys gelten als 'gefunden'.
            return self.get_kg_key(key_id) is not None

    def touch_kg_key(self, key_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE kg_api_keys SET last_used_at = ? WHERE id = ?",
                (_now(), key_id),
            )

    # ---- App-Key-Value (z. B. NFC-Secret) -----------------------------
    def get_kv(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM app_kv WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_kv_updated(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT updated_at FROM app_kv WHERE key = ?", (key,)
        ).fetchone()
        return row["updated_at"] if row else None

    def set_kv(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO app_kv(key,value,updated_at) VALUES(?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at",
                (key, value, _now()),
            )

    def count_nfc_bound(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM airlocks WHERE nfc_uid IS NOT NULL"
        ).fetchone()[0]

    # ---- Abfragen -----------------------------------------------------
    def get_airlock(self, code: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM airlocks WHERE code = ?", (code,)
        ).fetchone()

    def get_batch(self, batch_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()

    def list_airlocks(self, status: str | None = None, batch_id: str | None = None,
                      available: bool = False,
                      limit: int = 100, offset: int = 0) -> list[sqlite3.Row]:
        q = "SELECT * FROM airlocks WHERE 1=1"
        args: list = []
        if status:
            q += " AND status = ?"; args.append(status)
        if batch_id:
            q += " AND batch_id = ?"; args.append(batch_id)
        if available:
            # "Verfuegbar" = Tag gebunden und noch frei (nicht in Benutzung/entwertet).
            q += (" AND nfc_uid IS NOT NULL"
                  " AND status NOT IN ('active','retired','voided')")
        q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        return self._conn.execute(q, args).fetchall()

    def airlocks_of_batch(self, batch_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM airlocks WHERE batch_id = ? ORDER BY code", (batch_id,)
        ).fetchall()

    def list_batches(self, limit: int = 100, offset: int = 0) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM batches ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    def status_counts(self) -> dict[str, int]:
        """Anzahl Airlocks je Status (nur belegte Status)."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM airlocks GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def close(self) -> None:
        self._conn.close()
