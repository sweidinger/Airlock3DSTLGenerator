"""Update-Status (Container-Seite).

Der Container fasst NICHT Docker/Git an. Er liest nur `status.json`, das der
Host-Watcher schreibt, und legt bei Bedarf `update.request` an. Der Watcher auf
der NAS erledigt `git fetch` / `git checkout <tag>` + Rebuild.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .version import APP_VERSION, GIT_SHA, semver


def _dir() -> Path:
    d = Path(settings.control_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_status() -> dict:
    d = _dir()
    st: dict = {}
    f = d / "status.json"
    if f.is_file():
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    latest = st.get("latest")
    update_available = bool(latest) and semver(latest) > semver(APP_VERSION)
    return {
        "current": APP_VERSION,
        "current_sha": GIT_SHA,
        "latest": latest,
        "update_available": update_available,
        "checked_at": st.get("checked_at"),
        "history": st.get("history", []),
        "latest_notes": st.get("latest_notes", ""),
        "requested": (d / "update.request").is_file(),
        "applying": (d / "update.applying").is_file(),
        "last_result": st.get("last_result"),
        "watcher_active": f.is_file(),
    }


def request_update() -> dict:
    d = _dir()
    if (d / "update.applying").is_file():
        return {"requested": False, "reason": "Update läuft bereits."}
    (d / "update.request").write_text(
        json.dumps({"requested_by": "dashboard", "at": _now()}), encoding="utf-8"
    )
    return {"requested": True, "at": _now()}
