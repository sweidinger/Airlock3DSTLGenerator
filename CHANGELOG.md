# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

## [1.2.2] - 2026-07-30
### Geändert
- Intern: `index.html` in schlankes Gerüst plus `app.css`, `app.js` und
  `viewer.js` aufgeteilt (kleinere Dateien, sauberere Diffs, keine Funktionsänderung).

## [1.2.1] - 2026-07-30
### Geändert
- Updates/Changelog jetzt als eigene Seite statt Popup; Navigationsleiste oben
  rechts im Header (Dashboard / Changelog).
- Das „Version & Updates"-Feld ist von der Hauptseite entfernt.

## [1.2.0] - 2026-07-29
### Hinzugefügt
- Update-Seite im Dashboard („Updates & Changelog") mit Release-Notes je Version.
- Hinweisbox im Header nach der Versionsnummer, sobald ein Update verfügbar ist.
- Versionierte `CHANGELOG.md`; der Update-Watcher liest die Notes zum neuesten Tag.

## [1.1.1] - 2026-07-29
### Behoben
- CI: `pytest`-Importpfad über `pyproject.toml` (`pythonpath`), damit die Tests
  auch bei bloßem `pytest` (ohne `python -m`) das `app`-Modul finden.
- Build-Logs werden nicht mehr versioniert (`.gitignore`).

## [1.1.0] - 2026-07-29
### Hinzugefügt
- Web-Dashboard unter `/`: Status/Statistik, Generierung, Airlock- und
  Batch-Browser mit Downloads und Statuswechsel, read-only Konfiguration.
- STL-Viewer (three.js, lokal eingebunden): 3D-Ansicht je Lock direkt im Browser.
- Versionierung: `VERSION`-Datei ins Image, `/v1/version` (mit Git-SHA/Build-Datum),
  Anzeige im Dashboard.
- Update-System: Host-Watcher bzw. Updater-Sidecar prüft neue Release-Tags und
  wendet Updates auf Anforderung an (Container ohne Docker-/Root-Rechte).
- GitHub Actions (CI): Tests + Docker-Build bei Push, Release bei Tag `v*`.
- Komfort-Flag `AIRLOCK_UI_AUTOKEY` für automatische Dashboard-Anmeldung im LAN.

## [1.0.0] - 2026-07-29
### Hinzugefügt
- Generator-Core (OpenSCAD): prägt eine erhabene 5-stellige Nummer auf die
  Airlock-Vorlage, validiert gegen das Original-Sample.
- REST-API (FastAPI): Batch-Erzeugung (Auto-Vergabe oder vorgegebene Codes),
  Einzel-/ZIP-Download, Statuspflege, API-Key-Auth, Idempotenz.
- SQLite-Registry mit Status-Lebenszyklus; Ausgabe als ZIP und ins Volume.
- Docker/Compose, Testsuite.
