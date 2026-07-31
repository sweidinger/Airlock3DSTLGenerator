# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

## [1.13.0] - 2026-07-31
### Hinzugefügt
- **Druckfertiger P1S-Projekt-Export** (`format: "p1s"` bei `POST /v1/airlocks:threemf`,
  Dashboard: „P1S-Projekt (Pause 3 mm)"). Erzeugt statt eines reinen Modell-3MF ein
  vollwertiges **Bambu-Studio-P1S-Projekt**: eingebettetes P1S-0.4-Druckerprofil,
  zweifarbig (Korpus/Nummer via `paint_color`), Locks im Raster angeordnet (links vom
  Prime Tower bei x=205/y=150) und eine **Druck-Pause bei 3 mm** (`M400 U1` mit
  Displaymeldung „Tag(s) einlegen, dann fortsetzen") bereits eingebaut — zum Einlegen
  der NFC-Tags während der Druckpause. Neues Modul `app/p1s_project.py`; statische
  Profilteile als Golden Template unter `app/templates/p1s/`. Fix auf den P1S.
- (Später geplant: Projekt-Details wie Name/Beschreibung/Accessories automatisch
  mit ausfüllen.)

## [1.12.0] - 2026-07-31
### Geändert
- **Neue Standard-Vorlage `DisposableLock_NTAG213.stl`** ersetzt `DisposableLock_v2`
  vollständig. Das NTAG213-Schloss hat eine Print-Pause-Tasche für einen
  12 × 19 × 0,19-mm-Tag (Einlegen bei 3 mm Druckhöhe) und ein abgesenktes
  Zahlenfeld (19 × 12 mm, 0,5 mm tief) auf der Oberseite.
- **Nummer-Platzierung**: Die 5-stellige Nummer wird jetzt **zentriert und bündig**
  ins Zahlenfeld generiert (statt erhaben auf die Paddle-Fläche), lesbar
  links→rechts mit dem Bügel oben. Abriebgeschützt und ideal für den
  Mehrfarb-3MF-Export (`body`/`code`-Split unverändert nutzbar).
- **Toleranz**: Tag-Tasche auf 19,40 × 12,40 mm aufgeweitet (0,20 mm/Seite) für
  leichteres Einlegen während der Druckpause.
- `TemplateProfile` um `halign`/`valign` erweitert (Default `center`); das
  SCAD-Template platziert den Text darüber. Profil-Default-Name jetzt
  `DisposableLock_NTAG213`. Tests/ARCHITECTURE.md entsprechend aktualisiert.

## [1.11.0] - 2026-07-31
### Hinzugefügt
- **Universal-Link-Record auf dem Tag**: `nfc/prepare` liefert zusätzlich ein
  Feld `url` (`<AIRLOCK_TAG_URL_BASE>/t/<code>`). Ist `AIRLOCK_TAG_URL_BASE`
  gesetzt, schreibt die Writer-App einen zweiten NDEF-Record (URI **zuerst**,
  danach der bestehende Text-Record `AL1|code|token`). Damit kann ein Antippen
  des Tags die KG-Tracker-App über einen Universal Link öffnen. Rückwärts-
  kompatibel: ohne Basis bleibt es beim reinen Text-Record; Reader ignorieren
  den URI-Record (Suche über Well-Known-Typ „T").
### Konfiguration
- Neue Env-Variable `AIRLOCK_TAG_URL_BASE` (im `environment:`-Block der
  docker-compose.yml, Default `https://nfc.neurorelatepoly.app`).

## [1.10.0] - 2026-07-31
### Hinzugefügt
- **Erzwungener Status-Lebenszyklus**: Statuswechsel folgen jetzt der
  Einzelschritt-Kette `reserved→generated→printed→registered→active→retired`
  (`voided` als Off-Ramp aus jeder Vorstufe); unerlaubte Sprünge → **409**.
  Der volle API-Key kann per `force:true` bewusst überschreiben (im Verlauf als
  „forciert" markiert). `retired`/`voided` sind jetzt echt terminal.
- **Tag-Schreiben erst ab `printed`**: `nfc/prepare` + `nfc/commit` verlangen den
  Status `printed` (Ausnahme: bereits gebundene Locks fürs Neu-/Rückschreiben).
  Auto-Promotion nur noch `printed → registered`.
- **Status-Verlauf/Audit**: neue Tabelle + `GET /v1/airlocks/{code}/history` mit
  Zeitstempel, Quelle (`system`/`app`/`api`) und Akteur je Änderung; Backfill für
  bestehende Locks. Auch manuelle Dashboard-Änderungen werden protokolliert.
- **Dashboard**: „Abhängigkeiten-Leiste" (Stepper) pro Lock, „gedruckt"-Knopf
  (`generated→printed`), geführter Statuswechsel (nur erlaubte Ziele) +
  „⚙ Erzwingen"-Schalter, Verlauf-Dialog mit Zeit + Auslöser.
- **Writer-Key darf jetzt verifizieren** (`nfc/verify`) — für die Selbstkontrolle
  der Writer-App nach dem Schreiben. Das HMAC-Secret bleibt serverseitig.

## [1.9.1] - 2026-07-31
### Behoben
- Deploy: `AIRLOCK_BETA_TAG_MOVE` wird jetzt in `docker-compose.yml` an den
  Container durchgereicht (die `environment:`-Liste ist explizit). Ohne diese
  Zeile blieb der Beta-Tag-Umzug aus v1.9.0 im Container wirkungslos, auch wenn
  das Flag in der `.env` stand.

## [1.9.0] - 2026-07-31
### Geändert
- **Tag-Bindung ist jetzt endgültig** („einmal verheiratet, bleibt verheiratet"):
  Ist ein Schloss bereits mit einem Tag gebunden, lehnt `nfc/commit` das Binden
  eines anderen Tags mit **409** ab. Das erneute Schreiben desselben Tags auf
  dasselbe Schloss bleibt erlaubt (idempotent).
### Hinzugefügt
- **Bewusstes Neu-Verheiraten** über `rebind: true` im Body von `nfc/commit`:
  ersetzt die bestehende Bindung eines Schlosses durch einen neuen (freien) Tag.
  Die Antwort enthält dann ein `warning`. Im Dashboard gibt es dafür im
  NFC-Dialog die Checkbox „Neu verheiraten"; die iOS-Writer-App bietet bei 409
  einen Bestätigungsdialog an.
- **Beta-Tag-Umzug** (`AIRLOCK_BETA_TAG_MOVE=1`): erlaubt beim Neu-Verheiraten
  zusätzlich, einen Tag, der noch an einem **anderen** Schloss hängt, dort zu
  lösen und umzubinden (mit deutlichem Hinweis in `warning`). Nur für die
  Beta-Phase gedacht — ohne das Flag bleibt ein Tag dauerhaft an höchstens einem
  Schloss (Umzugsversuch → 409).

## [1.8.1] - 2026-07-31
### Geändert
- `nfc/commit` (Tag beschreiben – auch aus der nativen iOS-Writer-App) hebt den
  Status eines Airlocks jetzt automatisch von `reserved`/`generated`/`printed`
  auf **`registered`**: sobald ein physischer Tag gebunden wird, gilt der Lock als
  registriert (kein manuelles Umstellen im Dashboard mehr nötig). Bereits
  `registered`/`active` bleibt unverändert; terminale Status (`retired`/`voided`)
  werden nicht angetastet.

## [1.8.0] - 2026-07-30
### Hinzugefügt
- **Writer-Keys** für eine native NFC-Writer-App: eigener Dashboard-Bereich
  „KG-Tracker" → „Writer-Keys" (ein Key pro Gerät, benannt, einmalig anzeigbar,
  widerrufen/regenerieren). Ein Writer-Key (`alw_…`) darf Airlocks **lesen** und
  Tags **beschreiben** (`nfc/prepare`, `nfc/commit`) — aber nicht generieren,
  herunterladen, den Status wechseln oder verifizieren. So muss nie der volle
  API-Key aufs Handy; verlorene Geräte werden einzeln widerrufen. Keys werden nur
  als SHA-256-Hash gespeichert. API (voller Key): `POST/GET /v1/writer/keys`,
  `…/revoke`, `…/regenerate`. Auch Writer-Key-Anfragen erscheinen im Debug-Log.
### Geändert
- `nfc/prepare` und `nfc/commit` akzeptieren jetzt **auch** einen Writer-Key
  (zusätzlich zum vollen Key); `GET /v1/airlocks` und `GET /v1/airlocks/{code}`
  akzeptieren voller Key **oder** KG-Key **oder** Writer-Key. Die Scopes bleiben
  getrennt: KG-Keys dürfen weiterhin nicht schreiben, Writer-Keys nicht
  verifizieren/Status ändern.

## [1.7.0] - 2026-07-30
### Hinzugefügt
- **NFC-Secret-Verwaltung im Dashboard** (Bereich „KG-Tracker"): starkes
  Zufalls-Secret erzeugen (einmal anzeigbar), Status sehen und ein
  **passwortgeschütztes Backup** exportieren/wiederherstellen (scrypt +
  AES-256-GCM — das Passwort schützt nur die Backup-Datei). Das Secret liegt in
  der DB; eine gesetzte `AIRLOCK_NFC_SECRET`-Env behält **Vorrang**. Rotation ist
  mit Warnung abgesichert (macht bestehende Tags ungültig). API (voller Key):
  `GET/POST /v1/nfc/secret/status|generate|backup|restore`.
### Geändert
- `nfc/prepare` und `nfc/verify` nutzen jetzt das **effektive** Secret
  (Env-Override → DB → Default) statt nur der Env-Variable.

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
