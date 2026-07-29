"""Versionsinfo der laufenden Instanz.

Version kommt aus der `VERSION`-Datei (ins Image gebacken); Git-SHA und
Build-Datum werden beim Build als Build-Args/Env mitgegeben.
"""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read_version() -> str:
    try:
        return (_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


APP_VERSION = _read_version()
GIT_SHA = os.environ.get("GIT_SHA", "unknown")
BUILD_DATE = os.environ.get("BUILD_DATE", "unknown")


def semver(s: str) -> tuple[int, int, int]:
    """'v1.2.3' / '1.2.3' -> (1,2,3); robust gegen Murks."""
    try:
        parts = s.strip().lstrip("vV").split(".")
        nums = [int("".join(ch for ch in p if ch.isdigit()) or 0) for p in parts[:3]]
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums[:3])  # type: ignore[return-value]
    except Exception:
        return (0, 0, 0)
