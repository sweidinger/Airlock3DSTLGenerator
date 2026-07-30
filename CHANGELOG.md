# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

## [1.6.0] - 2026-07-30
### Hinzugefügt
- Eingeschränkte **KG-Tracker-API-Keys**: eigener Dashboard-Bereich „KG-Tracker",
  in dem man benannte Keys erzeugt (einmalig anzeigbar), widerruft und neu erzeugt
  (Regenerate). Diese Keys dürfen nur **lesen**, den **Status wechseln** und NFC
  **verifizieren** — nicht generieren, herunterladen oder Tags schreiben. Keys
  werden nur als SHA-256-Hash gespeichert. API: `POST/GET /v1/kg/keys`,
  `…/revoke`, `…/regenerate`.
- **Debug-Log** im Dashboard: In-Memory-Ringpuffer (letzte ~500) der KG-Key-
  Anfragen (Methode, Pfad, Key-Präfix/Name, HTTP-Status, Ergebnis) — ohne den Key
  selbst. API: `GET /v1/kg/log`, `POST /v1/kg/log:clear`.
- `GET /v1/airlocks?available=true`: liefert nur verfügbare Locks (NFC-Tag
  gebunden, Status noch frei) — für die Lock-Auswahl im KG-Tracker.
- `POST …/nfc/verify` optional mit `require_status` (z. B. `active`) → neuer Grund
  `status_mismatch`.
### Geändert
- `GET /v1/airlocks`, `GET /v1/airlocks/{code}`, `PATCH /v1/airlocks/{code}` und
  `…/nfc/verify` akzeptieren jetzt **auch** einen KG-Tracker-Key (zusätzlich zum
  vollen API-Key). Alle übrigen Endpunkte bleiben dem vollen Key vorbehalten.

## [1.5.0] - 2026-07-30
### Hinzugefügt
- NFC-Tag-Unterstützung als Echtheits-/Kopierschutz: pro Lock wird ein signierter
  Token (`HMAC(secret, Code|Tag-UID)`) erzeugt und die eindeutige Tag-UID in der
  Registry gebunden. Ein Nachdruck hätte eine andere UID → fällt auf; ohne das
  Secret lässt sich kein gültiger Token fälschen.
- API: `POST /v1/airlocks/{code}/nfc/prepare` (Payload erzeugen),
  `…/nfc/commit` (UID binden), `…/nfc/verify` (für den KG-Tracker).
- Dashboard: NFC-Button je Airlock — Schreiben per **Web NFC** (Android/Chrome,
  HTTPS) oder Fallback (UID eingeben, Payload mit eigenem Tool schreiben,
  bestätigen). Tag-Status wird in der Tabelle angezeigt.
- Optionaler HTTPS-Reverse-Proxy (Caddy, `docker-compose.proxy.yml`) als
  Voraussetzung für Web NFC; `AIRLOCK_NFC_SECRET` in `.env.example`;
  Spezifikation in `docs/NFC.md` (inkl. Verifikation für den KG-Tracker).

## [1.4.0] - 2026-07-30
### Hinzugefügt
- Mehrfarb-Export als **OBJ** (Per-Vertex-Farbe) zusätzlich zum 3MF. Format wird
  im Dashboard gewählt (3MF (Farbe) / OBJ (Farbe)); der Button heißt jetzt
  „Mehrfarbe erstellen". API: `format`-Feld in `POST /v1/airlocks:threemf`,
  Download über `/v1/threemf/{name}` auch für `.obj`.
### Geändert / Behoben
- 3MF-Farbe jetzt **pro Dreieck** über die 3MF-Material-Erweiterung
  (`m:colorgroup`) statt über Basismaterialien/Extruder-Zuweisung. Dadurch färbt
  Bambu Studio ALLE Locks eines Batches korrekt zweifarbig (vorher nur der erste)
  — Schloss schwarz, Nummer weiß. Beim Import mappt Bambu die zwei Farben auf die
  Filament-Slots.

## [1.3.3] - 2026-07-30
### Behoben
- Update-Watcher: Es zählen nur noch echte Release-Tags (`vX.Y.Z`). CI-/Test-Tags
  wie `vci-test-…` matchten zwar den `v*`-Filter, wurden aber als riesige Version
  fehlgedeutet und als „neueste" angezeigt — das ist jetzt ausgeschlossen.

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
