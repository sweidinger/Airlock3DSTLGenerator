#!/usr/bin/env python3
"""Host-Update-Watcher für den Airlock-Generator (läuft auf der NAS per cron).

Aufgaben:
  * `git fetch --tags` und den neuesten Release-Tag ermitteln,
  * status.json ins geteilte control-Verzeichnis schreiben (Dashboard liest das),
  * wenn das Dashboard `update.request` anlegt: auf den neuesten Tag wechseln
    und den Container per `docker compose up -d --build` neu bauen.

Der Container selbst bekommt so KEINEN Docker-/Root-Zugriff — nur dieser
Host-Prozess (läuft als der NAS-Benutzer, der in der docker-Gruppe ist).

Installation (cron, jede Minute):
  * * * * * /usr/bin/python3 $HOME/airlock-stl-generator/scripts/nas_update_watcher.py >> $HOME/airlock-stl-generator/control/watcher.log 2>&1
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("AIRLOCK_REPO", str(Path.home() / "airlock-stl-generator")))
CTRL = REPO / "control"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(*args, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, **kw)


def semver(s: str):
    try:
        parts = s.strip().lstrip("vV").split(".")
        nums = [int("".join(c for c in p if c.isdigit()) or 0) for p in parts[:3]]
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums[:3])
    except Exception:
        return (0, 0, 0)


def read_version() -> str:
    f = REPO / "VERSION"
    return f.read_text().strip() if f.is_file() else "0.0.0"


def write_status(**extra) -> None:
    st = {}
    f = CTRL / "status.json"
    if f.is_file():
        try:
            st = json.loads(f.read_text())
        except Exception:
            st = {}
    st.update(extra)
    f.write_text(json.dumps(st, indent=2))


# Nur echte Release-Tags (vMAJOR.MINOR.PATCH) zaehlen. Sonstige Tags wie
# CI-Test-Tags (z. B. "vci-test-123...") werden ignoriert -- sie matchen zwar
# den v*-Glob, sind aber keine Versionen und wuerden sonst als "neueste"
# fehlgedeutet.
_VER_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def collect_history(limit: int = 15) -> list:
    out = git("for-each-ref", "--sort=-creatordate",
              "--format=%(refname:short)|%(creatordate:short)|%(contents:subject)",
              "refs/tags/v*").stdout.strip().splitlines()
    hist = []
    for line in out:
        p = line.split("|", 2)
        if len(p) >= 2 and _VER_RE.match(p[0]):
            hist.append({"version": p[0].lstrip("vV"), "date": p[1],
                         "subject": (p[2] if len(p) > 2 else "")})
        if len(hist) >= limit:
            break
    return hist


def latest_tag() -> str:
    tags = [t for t in git("tag", "-l", "v*").stdout.split() if _VER_RE.match(t)]
    tags.sort(key=semver)
    return tags[-1] if tags else ""


def read_changelog(ref: str) -> str:
    r = git("show", f"{ref}:CHANGELOG.md")
    return r.stdout if r.returncode == 0 else ""


def parse_changelog(text: str) -> dict:
    """Zerlegt CHANGELOG.md in {version: notes_text} anhand der ## -Überschriften."""
    sections: dict = {}
    cur = None
    buf: list = []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur:
                sections[cur] = "\n".join(buf).strip()
            m = re.search(r"(\d+\.\d+\.\d+)", line)
            cur = m.group(1) if m else None
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur:
        sections[cur] = "\n".join(buf).strip()
    return sections


def apply_update(latest: str) -> None:
    (CTRL / "update.applying").write_text(now())
    (CTRL / "update.request").unlink(missing_ok=True)
    log = [f"[{now()}] Update-Apply gestartet -> {latest or 'main'}"]
    git("fetch", "--tags", "--quiet", "origin")
    if latest:
        r = git("checkout", "-f", latest)
    else:
        r = git("pull", "--ff-only")
    log.append("checkout: " + (r.stderr + r.stdout).strip())
    env = os.environ.copy()
    env["GIT_SHA"] = git("rev-parse", "--short", "HEAD").stdout.strip() or "unknown"
    env["BUILD_DATE"] = now()
    # Nur den Generator-Service neu bauen (damit ein Updater-Sidecar sich nicht
    # selbst neu startet). AIRLOCK_COMPOSE_SERVICE leer -> alle Services.
    service = os.environ.get("AIRLOCK_COMPOSE_SERVICE", "").strip()
    compose_cmd = ["docker", "compose", "up", "-d", "--build"] + ([service] if service else [])
    build = subprocess.run(compose_cmd, cwd=REPO, capture_output=True, text=True, env=env)
    log.append(f"[{now()}] docker compose rc={build.returncode}")
    log.append(build.stdout[-3000:]); log.append(build.stderr[-3000:])
    newver = read_version()
    write_status(
        current_seen=newver, checked_at=now(),
        update_available=(semver(latest.lstrip("v")) > semver(newver)) if latest else False,
        last_result={"at": now(), "ok": build.returncode == 0, "version": newver, "tag": latest},
    )
    (CTRL / "update.log").write_text("\n".join(log)[-8000:])
    (CTRL / "update.applying").unlink(missing_ok=True)


def main() -> None:
    CTRL.mkdir(parents=True, exist_ok=True)
    lock = CTRL / ".watcher.lock"
    if lock.is_file() and (time.time() - lock.stat().st_mtime) < 1800:
        return  # anderer Lauf aktiv
    lock.write_text(str(os.getpid()))
    try:
        git("fetch", "--tags", "--quiet", "origin")
        cur = read_version()
        lt = latest_tag()
        latest_ver = lt.lstrip("vV") if lt else cur
        hist = collect_history()
        changelog = parse_changelog(read_changelog(lt) if lt else read_changelog("HEAD"))
        for h in hist:
            h["notes"] = changelog.get(h["version"], "")
        write_status(current_seen=cur, latest=latest_ver, checked_at=now(),
                     history=hist, latest_notes=changelog.get(latest_ver, ""),
                     update_available=semver(latest_ver) > semver(cur))
        if (CTRL / "update.request").is_file():
            apply_update(lt)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
