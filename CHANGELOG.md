# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

## [1.3.2] - 2026-07-30
### Behoben
- Dashboard: Cache-Busting für `/static`-Assets (`app.css`/`app.js`/`viewer.js`
  mit `?v=<Version>`). Der Browser lädt nach einem Update jetzt automatisch die
  neuen Dateien — kein manuelles Hard-Reload mehr nötig (dadurch wurden z. B. die
  neuen Checkboxen aus 1.3.1 erst nach Cache-Leeren sichtbar).

## [1.3.1] - 2026-07-30
### Behoben
- Dashboard: Auswahl-Checkboxen in der Airlock-Tabelle waren durch die globale
  Input-Formatierung unsichtbar/nicht bedienbar — jetzt native Checkboxen.
### Geändert
- Button „3MF aus Auswahl" heißt jetzt „3MF erstellen" und ist ausgegraut,
  solange keine Airlocks markiert sind.

## [1.3.0] - 2026-07-30
### Hinzugefügt
- Mehrfarb-3MF-Export für Bambu Lab (X1/P1/A1, 256×256): Schloss in Schwarz,
  Nummer in Weiß als getrennte Objekte, im Raster auf der Bauplatte angeordnet.
  Farben über Basismaterialien (keine feste AMS-Slot-Zuweisung).
- API: `POST /v1/airlocks:threemf` (aus Codes oder einem Batch) und
  `GET /v1/threemf/{name}` zum Download.
- Dashboard: Checkboxen je Airlock plus „3MF aus Auswahl", 3MF-Button je Batch
  und im Generier-Ergebnis. Rückmeldung zu Rastergröße und Plattenpassung.
- Generator: OpenSCAD-Vorlage um `part` erweitert (`body`/`code`/`both`); Body
  trägt die Code-Aussparung, der Code füllt sie exakt (kein Überlappen).

### Behoben
- CI: Actions auf Node-24-Versionen gehoben (`actions/checkout@v5`,
  `actions/setup-python@v6`) — Node-20-Deprecation-Warnung entfällt.

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
