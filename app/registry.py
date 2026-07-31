"""SQLite-Registry: Code-Vergabe, Batches, Status-Lebenszyklus.

Die Registry ist die generator-eigene Absicherung gegen Doppelvergabe.
Die finale Hoheit ueber Eindeutigkeit liegt bei KG-Tracker (Source-of-Truth).
"""
from __future__ import annotations

import hashlib
import json
import os
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
_TERMINAL = frozenset({"retired", "voided"})
# Beim Beschreiben eines Tags (nfc/commit) wird der Status automatisch auf
# 'registered' gehoben — jetzt NUR aus 'printed' (Tag-Schreiben setzt „gedruckt"
# voraus, durchgesetzt im API-Gate).
_NFC_PROMOTE_FROM = ("printed",)

# Erlaubte MANUELLE Uebergaenge via PATCH (update_status). Einzelschritt-Kette;
# '→generated' (System/Render) und '→registered' (App/nfc-commit) sind bewusst
# NICHT per PATCH erreichbar. 'voided' ist Off-Ramp aus jeder Vorstufe.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "reserved":   frozenset({"voided"}),
    "generated":  frozenset({"printed", "voided"}),
    "printed":    frozenset({"voided"}),
    "registered": frozenset({"active", "voided"}),
    "active":     frozenset({"retired"}),
    "retired":    frozenset(),
    "voided":     frozenset(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CodeExhaustionError(RuntimeError):
    """Kein freier Code mehr im Nummernraum verfuegbar."""


class TagBindingError(ValueError):
    """Tag-/Schloss-Bindungskonflikt (fuehrt in der API zu HTTP 409).

    Faelle:
      * Das Schloss ist bereits mit einem anderen Tag 'verheiratet' und
        `rebind` wurde nicht gesetzt (Bindung ist endgueltig).
      * Die Tag-UID haengt noch an einem anderen Schloss und ein Umzug ist
        nicht erlaubt (kein `rebind` bzw. Beta-Umzug aus).
    Erbt von ValueError, damit bestehende Handler es weiter als 409 behandeln.
    """


class TransitionError(ValueError):
    """Unerlaubter Status-Uebergang (fuehrt in der API zu HTTP 409).

    Der Lebenszyklus ist eine Einzelschritt-Kette (s. ALLOWED_TRANSITIONS). Nur
    der volle API-Key darf mit `force=True` bewusst ueberspringen.
    """


class Registry:
    def __init__(self, db_path: str | Path, code_length: int = 5):
        self.db_path = Path(db_path)
        self.code_length = code_length
        self.code_space = 10 ** code_length
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Ablage der Druck-Belege (Fotos) neben der DB (liegt auf demselben Volume).
        self._proofs_dir = self.db_path.parent / "proofs"
        self._proofs_dir.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS writer_api_keys (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    key_hash     TEXT NOT NULL UNIQUE,
                    key_prefix   TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked_at   TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_wrkeys_hash ON writer_api_keys(key_hash);
                CREATE TABLE IF NOT EXISTS app_kv (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS status_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    code        TEXT NOT NULL,
                    from_status TEXT,
                    to_status   TEXT NOT NULL,
                    at          TEXT NOT NULL,
                    source      TEXT NOT NULL,   -- system | app | api
                    actor       TEXT,            -- render / Key-Name / voll / backfill
                    forced      INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_history_code ON status_history(code);
                CREATE TABLE IF NOT EXISTS print_proofs (
                    code        TEXT PRIMARY KEY,
                    captured_at TEXT NOT NULL,
                    sha256      TEXT NOT NULL,
                    mime        TEXT NOT NULL,
                    bytes       INTEGER NOT NULL,
                    actor       TEXT
                );
                """
            )
            self._backfill_history()

    def _backfill_history(self) -> None:
        """Seedet den Status-Verlauf fuer bereits existierende Locks EINMALIG
        (naeherungsweise aus created_at / nfc_written_at), sofern noch leer."""
        have = self._conn.execute("SELECT COUNT(*) FROM status_history").fetchone()[0]
        if have:
            return
        for a in self._conn.execute(
            "SELECT code, status, created_at, nfc_written_at FROM airlocks"
        ).fetchall():
            ca, wa, st = a["created_at"], a["nfc_written_at"], a["status"]
            rows = [(None, "reserved", ca, "system", "backfill"),
                    ("reserved", "generated", ca, "system", "backfill")]
            covered = {"reserved", "generated"}
            if wa:
                rows.append(("printed", "registered", wa, "app", "backfill"))
                covered.add("registered")
            if st not in covered and st != "reserved":
                frm = "registered" if wa else "generated"
                rows.append((frm, st, wa or ca, "api", "backfill"))
            for frm, to, at, src, act in rows:
                self._conn.execute(
                    "INSERT INTO status_history(code,from_status,to_status,at,source,actor,forced)"
                    " VALUES(?,?,?,?,?,?,0)",
                    (a["code"], frm, to, at, src, act),
                )

    def _hist(self, code: str, frm: str | None, to: str, source: str,
              actor: str | None = None, forced: bool = False) -> None:
        """Schreibt eine Verlaufszeile. MUSS innerhalb eines gehaltenen
        `self._lock`/`self._conn`-Blocks aufgerufen werden (kein erneutes Lock)."""
        self._conn.execute(
            "INSERT INTO status_history(code,from_status,to_status,at,source,actor,forced)"
            " VALUES(?,?,?,?,?,?,?)",
            (code, frm, to, _now(), source, actor, 1 if forced else 0),
        )

    def get_history(self, code: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT from_status, to_status, at, source, actor, forced"
            " FROM status_history WHERE code=? ORDER BY id", (code,)
        ).fetchall()

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
            self._hist(code, None, "reserved", "system", "reserve")

    def mark_generated(self, code: str, stl_path: str, sha256: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE airlocks SET status='generated', stl_path=?, stl_sha256=? WHERE code=?",
                (stl_path, sha256, code),
            )
            self._hist(code, "reserved", "generated", "system", "render")

    def finish_batch(self, batch_id: str, status: str, zip_path: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE batches SET status=?, zip_path=? WHERE batch_id=?",
                (status, zip_path, batch_id),
            )

    def update_status(self, code: str, status: str, *, source: str = "api",
                      actor: str | None = None, force: bool = False) -> sqlite3.Row:
        """Setzt den Status mit Einzelschritt-Guard (s. ALLOWED_TRANSITIONS).

        - Gleicher Status = No-op (kein Verlaufseintrag).
        - Unerlaubter Uebergang → `TransitionError`, ausser `force=True`.
        - Jede echte Aenderung schreibt eine Verlaufszeile (mit `source`/`actor`;
          `forced=True`, wenn nur dank force durchgelassen).
        """
        if status not in STATUSES:
            raise ValueError(f"Ungueltiger Status: {status}")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT status FROM airlocks WHERE code=?", (code,)
            ).fetchone()
            if row is None:
                raise KeyError(code)
            cur = row["status"]
            if cur == status:
                return self.get_airlock(code)          # No-op
            allowed = status in ALLOWED_TRANSITIONS.get(cur, frozenset())
            if not allowed and not force:
                nxt = sorted(ALLOWED_TRANSITIONS.get(cur, frozenset())) or ["—"]
                raise TransitionError(
                    f"Uebergang {cur} → {status} nicht erlaubt "
                    f"(erlaubt ab {cur}: {', '.join(nxt)}). Nur mit force."
                )
            self._conn.execute(
                "UPDATE airlocks SET status=? WHERE code=?", (status, code)
            )
            self._hist(code, cur, status, source, actor, forced=not allowed)
        return self.get_airlock(code)

    # ---- NFC ----------------------------------------------------------
    def get_by_nfc_uid(self, uid: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM airlocks WHERE nfc_uid = ?", (uid,)
        ).fetchone()

    def set_nfc(self, code: str, uid: str, rebind: bool = False,
                allow_tag_move: bool = False, actor: str | None = None) -> dict:
        """Bindet eine Tag-UID an einen Code ('verheiraten').

        Grundregel (Produktion): Eine Bindung ist **endgueltig**. Ist der Code
        bereits mit einem anderen Tag verheiratet, wird abgelehnt.

        - `rebind=True` erlaubt bewusst das Neu-Verheiraten: die bestehende
          Bindung wird durch den neuen Tag ersetzt.
        - Haengt der Tag noch an einem ANDEREN Schloss, ist das nur mit
          `rebind=True` UND `allow_tag_move=True` (Beta) moeglich; der Tag wird
          dann dort geloest und hierher umgebunden.

        Statuslogik unveraendert: Vorstufe (reserved/generated/printed) ->
        'registered'; registered/active bleibt, terminale (retired/voided)
        werden nicht angetastet.

        Rueckgabe: ``{"row", "rebound", "moved_from"}`` –
        `rebound`=True wenn eine bestehende Bindung ersetzt wurde,
        `moved_from`=Code, von dem der Tag weggenommen wurde (oder None).
        Wirft ``KeyError`` (unbekannt) bzw. ``TagBindingError`` (Konflikt).
        """
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT code, status, nfc_uid FROM airlocks WHERE code=?", (code,)
            ).fetchone()
            if row is None:
                raise KeyError(code)
            current = row["nfc_uid"]
            rebound = False
            moved_from = None

            # Schloss ist bereits mit einem ANDEREN Tag verheiratet.
            if current and current != uid:
                if not rebind:
                    raise TagBindingError(
                        f"Schloss {code} ist bereits mit Tag {current} verheiratet. "
                        "Die Bindung ist endgueltig – zum Neu-Verheiraten 'rebind' setzen."
                    )
                rebound = True

            # Tag haengt (noch) an einem ANDEREN Schloss.
            other = self._conn.execute(
                "SELECT code FROM airlocks WHERE nfc_uid=? AND code<>?", (uid, code)
            ).fetchone()
            if other is not None:
                if not (rebind and allow_tag_move):
                    raise TagBindingError(
                        f"Tag-UID bereits an Schloss {other['code']} gebunden."
                    )
                # Beta-Umzug: Tag am bisherigen Schloss loesen.
                moved_from = other["code"]
                self._conn.execute(
                    "UPDATE airlocks SET nfc_uid=NULL, nfc_written_at=NULL WHERE code=?",
                    (moved_from,),
                )

            if row["status"] in _NFC_PROMOTE_FROM:
                self._conn.execute(
                    "UPDATE airlocks SET nfc_uid=?, nfc_written_at=?, status='registered'"
                    " WHERE code=?",
                    (uid, _now(), code),
                )
                self._hist(code, row["status"], "registered", "app",
                           actor or "writer")
            else:
                self._conn.execute(
                    "UPDATE airlocks SET nfc_uid=?, nfc_written_at=? WHERE code=?",
                    (uid, _now(), code),
                )
        return {"row": self.get_airlock(code), "rebound": rebound,
                "moved_from": moved_from}

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

    # ---- Writer-API-Keys (native NFC-Writer-App) ----------------------
    def create_writer_key(self, key_id: str, name: str, key_hash: str,
                          key_prefix: str) -> sqlite3.Row:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO writer_api_keys(id,name,key_hash,key_prefix,created_at)"
                " VALUES(?,?,?,?,?)",
                (key_id, name, key_hash, key_prefix, _now()),
            )
        return self.get_writer_key(key_id)

    def get_writer_key(self, key_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM writer_api_keys WHERE id = ?", (key_id,)
        ).fetchone()

    def list_writer_keys(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM writer_api_keys ORDER BY created_at DESC"
        ).fetchall()

    def find_active_writer_key_by_hash(self, key_hash: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM writer_api_keys WHERE key_hash = ? AND revoked_at IS NULL",
            (key_hash,),
        ).fetchone()

    def revoke_writer_key(self, key_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE writer_api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (_now(), key_id),
            )
            if cur.rowcount:
                return True
            # Auch schon-widerrufene/existente Keys gelten als 'gefunden'.
            return self.get_writer_key(key_id) is not None

    def touch_writer_key(self, key_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE writer_api_keys SET last_used_at = ? WHERE id = ?",
                (_now(), key_id),
            )

    # ---- Druck-Belege (Foto-Nachweis fuer generated -> printed) --------
    @staticmethod
    def _proof_ext(mime: str) -> str:
        return ".png" if mime == "image/png" else ".jpg"

    def save_print_proof(self, code: str, data: bytes, mime: str,
                         actor: str | None = None) -> dict:
        """Legt das Beleg-Foto als Datei (neben der DB) ab und upsertet die
        Metadaten. Ein Beleg pro Lock (Re-Scan ersetzt). Schreiben ist atomar
        (tmp + os.replace); alte Belege mit anderer Endung werden entfernt."""
        sha = hashlib.sha256(data).hexdigest()
        # Vorhandene Belege dieses Codes (egal welche Endung) entfernen.
        for ext in (".jpg", ".png"):
            old = self._proofs_dir / f"{code}{ext}"
            if old.exists():
                try:
                    old.unlink()
                except OSError:
                    pass
        path = self._proofs_dir / f"{code}{self._proof_ext(mime)}"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO print_proofs(code,captured_at,sha256,mime,bytes,actor)"
                " VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(code) DO UPDATE SET"
                "  captured_at=excluded.captured_at, sha256=excluded.sha256,"
                "  mime=excluded.mime, bytes=excluded.bytes, actor=excluded.actor",
                (code, _now(), sha, mime, len(data), actor),
            )
        return {"code": code, "sha256": sha, "mime": mime, "bytes": len(data)}

    def load_print_proof(self, code: str) -> dict | None:
        """Liest Metadaten + Datei-Bytes des Belegs; None wenn keiner da."""
        row = self._conn.execute(
            "SELECT * FROM print_proofs WHERE code = ?", (code,)
        ).fetchone()
        if row is None:
            return None
        path = self._proofs_dir / f"{code}{self._proof_ext(row['mime'])}"
        try:
            data = path.read_bytes()
        except OSError:
            return None
        return {"bytes": data, "mime": row["mime"], "sha256": row["sha256"],
                "captured_at": row["captured_at"], "actor": row["actor"]}

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
