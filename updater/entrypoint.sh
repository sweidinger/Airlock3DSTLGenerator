#!/bin/sh
# Führt den Host-Update-Watcher periodisch aus.
INTERVAL="${WATCH_INTERVAL:-60}"
echo "[updater] gestartet, Intervall ${INTERVAL}s, Repo ${AIRLOCK_REPO:-/repo}"
while true; do
  python3 "${AIRLOCK_REPO:-/repo}/scripts/nas_update_watcher.py" 2>&1 | tail -c 1500 || echo "[updater] Watcher-Lauf fehlgeschlagen"
  sleep "$INTERVAL"
done
