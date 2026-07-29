# Airlock 3D-STL-Generator — Architektur- & API-Design

**Projekt:** Airlock3DSTLGenerator (eigenständiges Erweiterungsmodul der KG-Tracker App)
**Status:** Konzept / Design-Freigabe (Implementierung folgt)
**Datum:** 2026-07-29
**Autor:** Erstellt gemeinsam mit Claude (Cowork)

---

## 1. Ziel & Kurzbeschreibung

Der Airlock-Generator ist ein **eigenständiger Docker-Container**, der aus einer leeren STL-Vorlage (`DisposableLock_v2.stl`) einzelne, eindeutig nummerierte Airlock-STLs erzeugt. Jede erzeugte Datei enthält eine **erhabene, 5-stellige Nummer** (wie im Sample `DisposableLock_v2_withCode_sample.stl` → „73412"). Diese Nummer dient der **Verifikation eines Chastity-Devices** in der KG-Tracker App.

Der Generator läuft als reiner Backend-Service. Die **AI-Keyholderin** der KG-Tracker App steuert ihn über eine **REST-API** — z. B. „generiere 10 Airlocks mit je eindeutiger Nummer". Die fertigen STLs werden anschließend gedruckt und die Nummern in KG-Tracker hinterlegt, sodass die AI-Keyholderin bei einer Verschluss-Anforderung ein konkretes, existierendes Lock auswählen kann.

**Abgrenzung:** Dieses Dokument beschreibt den Generator-Container und seine Schnittstelle. Die KG-Tracker-seitige Verwaltung (Airlock-Entität, Auswahl bei Verschluss-Anforderung) wird hier als Integrationsanforderung skizziert, aber separat implementiert.

---

## 2. Technische Machbarkeit — validiert

Der Präge-Ansatz wurde bereits gegen dein Sample geprüft und reproduziert es praktisch deckungsgleich.

**Vorlage `DisposableLock_v2.stl`**

| Eigenschaft | Wert |
|---|---|
| Abmessungen (X × Y × Z) | 34,90 × 55,86 × 4,00 mm |
| Dreiecke | 954 |
| Wasserdicht (manifold) | ja |
| Volumen | 1859,98 mm³ |
| Bounding-Box min | (15,225 / 20,014 / −3,000) |

**Sample `DisposableLock_v2_withCode_sample.stl`**

| Eigenschaft | Wert |
|---|---|
| Abmessungen | 34,90 × 55,86 × 4,585 mm |
| Dreiecke | 1834 |
| Volumen | 1919,40 mm³ (= +59,4 mm³ Schrift) |
| Nummer | „73412", erhaben auf der flachen Paddle-Fläche |

**Wichtiger Ausrichtungs-Fund (per ICP verifiziert):** Das Sample ist **nicht** einfach eine verschobene Vorlage, sondern die Vorlage **um 180° um die Y-Achse gedreht** und anschließend in den Ursprung normalisiert (ICP-Kosten 0,0; Restabstand mean 0,14 mm — das ist reine Mesh-Diskretisierung, physisch exakt). Es handelt sich also um dasselbe physische Bauteil, nur „umgedreht": In der Vorlage sitzt der Verriegelungs-Dorn unten links und die Paddle-Fläche rechts; nach der Drehung (= Sample-Konvention) liegt der Dorn rechts und die **Paddle-Fläche links**, und genau darauf gehört der Code. Ohne diese Drehung landet der Text neben der Fläche — das war der Positionsfehler in der ersten Fassung. **Der Generator muss die Vorlage vor dem Prägen in die Sample-Ausrichtung bringen.**

Transformation: `rotate([0,180,0])` um die Y-Achse, danach `translate([50.1246, −20.0138, 1])`, um die Bounding-Box wieder auf min = 0/0/0 zu legen. Die Code-Fläche liegt anschließend oben bei z = 4,0 mm.

**Gemessene & finabgestimmte Präge-Parameter (in Sample-Ausrichtung, Ursprung 0/0/0):**

| Parameter | Sample (gemessen) | Finaler Default |
|---|---|---|
| Schrift | schmaler Bold-Sans | `Liberation Sans:style=Bold` |
| Schriftgröße (`size`) | — | 4,31 |
| Horizontale Skalierung (`xscale`) | — | 0,9573 (Breite an Sample angepasst) |
| Zeichenhöhe (Cap-Height) | 4,26 mm | 4,25 mm (Treffer) |
| Textbreite (5 Ziffern) | 15,16 mm | 15,16 mm (Treffer) |
| Prägehöhe (Z, erhaben) | 0,585 mm | 0,585 mm |
| Startpunkt links (X) | Tinte ab 2,46 mm | tx = 2,214 (Tinte ab 2,46) |
| Grundlinie (Y) | 11,69 mm | ty = 11,76 |
| Oberkante Text (Z) | 4,585 mm | = Deckfläche 4,0 + 0,585 |

`Liberation Sans:style=Bold` trifft die schmale Sample-Schrift deutlich besser als DejaVu (das rund 20 % zu breit läuft). Eine leichte horizontale Skalierung (0,9573) bringt Breite und Glyph-Positionen aller fünf Ziffern zur Deckung. Ergebnis: X 2,46–17,62 mm (Ziel 2,46–17,61), Höhe 4,25 mm (Ziel 4,26), Zielhöhe Z 4,585 mm exakt. Das erzeugte Modell ist wasserdicht (ein einziges Volumen). Der Overlay-Vergleich (Anhang A) zeigt generierte und Sample-Ziffern nahezu deckungsgleich; verbleibende haardünne Ränder resultieren aus minimalen Glyph-Unterschieden des exakten Original-Fonts.

**Validierter OpenSCAD-Kern (finale Referenz):**

```scad
code   = "73412";
size   = 4.31;
xscale = 0.9573;                      // Breite an Sample angeglichen
depth  = 0.585;                       // erhabene Höhe
tx     = 2.214;                       // Tinte startet dann bei X=2.46
ty     = 11.76;                       // Grundlinie
font   = "Liberation Sans:style=Bold";
topz   = 4.0;                         // Deckfläche

union() {
  // Vorlage in Sample-Ausrichtung: 180° um Y, dann in Ursprung normalisieren
  translate([50.12457, -20.01378, 1])
    rotate([0,180,0])
      import("DisposableLock_v2.stl");
  // Code erhaben auf der (jetzt oben liegenden) Paddle-Fläche
  translate([tx, ty, topz - 0.2])     // 0.2 mm einsinken → sauberes Manifold
    scale([xscale, 1, 1])
      linear_extrude(height = depth + 0.2)
        text(code, size = size, font = font, halign = "left", valign = "baseline");
}
```

> **Design-Hinweis Manifold:** Text 0,2 mm in die Deckfläche einsinken lassen, damit die Boolesche Vereinigung ein einziges wasserdichtes Volumen ergibt (statt zweier sich berührender Körper). Bestätigt: Ergebnis ist watertight. Wichtig für saubere Slicer-Ergebnisse.

---

## 3. Systemüberblick / Komponenten

Der Container besteht aus vier logischen Bausteinen:

**Generator-Core** — eine Python-Bibliothek, die einen Code entgegennimmt und über OpenSCAD (headless) eine STL rendert. Kapselt Vorlage, Font, Positionsparameter und Manifold-Fix. Deterministisch: gleicher Code → bytegleiche STL.

**REST-API (FastAPI + Uvicorn)** — die von der AI-Keyholderin gesteuerte Schnittstelle. Nimmt Batch-Aufträge an, koordiniert Code-Vergabe und Rendering, liefert ZIP + Manifest zurück. Automatische OpenAPI/Swagger-Doku unter `/docs`.

**Registry-DB (SQLite)** — persistente Liste aller je vergebenen Codes samt Status, Batch-Zugehörigkeit und STL-Pfad. Sichert die generator-seitige Kollisionsfreiheit ab (finale Hoheit hat KG-Tracker, siehe §4).

**Ausgabe-Volume** — ein gemounteter Ordner, in den die fertigen STLs geschrieben werden, damit der Druck-PC direkt darauf zugreift. Parallel zum ZIP-Download über die API.

---

## 4. Nummernschema & Eindeutigkeit

**Format:** 5-stellig numerisch, `00000`–`99999` (führende Nullen erhalten), 100 000 mögliche Codes. Entspricht dem Sample „73412".

**Eindeutigkeit — kombiniertes Modell (gewählt):** Der Generator kann Codes **selbst erzeugen** (zufällig, unter Ausschluss aller in seiner Registry bereits vergebenen) **oder vorgegebene Codes** aus KG-Tracker übernehmen. Die **finale Hoheit über Eindeutigkeit liegt bei KG-Tracker** — es ist die Source-of-Truth, in der jedes Lock dauerhaft geführt wird. Die generator-eigene Registry ist eine zusätzliche Absicherung gegen Doppelvergabe und ermöglicht Reproduktion/Nachdruck.

- **Auto-Vergabe:** KG-Tracker fordert `count: N` an → Generator zieht N garantiert freie Zufallscodes, reserviert sie, rendert, liefert die Liste zurück → KG-Tracker persistiert sie.
- **Vorgabe:** KG-Tracker liefert konkrete Codes (`codes: [...]`) → Generator prüft gegen seine Registry, rendert, meldet Konflikte einzeln zurück.

**Kollisions- & Erschöpfungsverhalten:** Rejection-Sampling gegen die Registry. Nähert sich die Belegung 100 000, steigt die Zieh-Dauer; ab ~90 % Belegung sollte gewarnt und ein größeres Schema erwogen werden. Für den erwarteten Mengenbereich (Zehner bis wenige Tausend Locks) unkritisch.

**Optionale Prüfziffer (später):** Für fehlerresistente manuelle Eingabe ließe sich eine Stelle als Luhn-/Damm-Prüfziffer auslegen. Bewusst **nicht** im MVP — als Feature-Flag vorgesehen.

---

## 5. Datenmodell (Registry-DB)

**Tabelle `airlocks`:** `code` (PK), `batch_id`, `status`, `stl_path`, `stl_sha256`, `source` (`auto`|`provided`), `requested_by`, `created_at`, `metadata` (JSON).

**Tabelle `batches`:** `batch_id` (PK, UUID), `count`, `status` (`pending`|`completed`|`failed`|`partial`), `zip_path`, `idempotency_key` (unique), `requested_by`, `created_at`.

**Status-Lebenszyklus eines Airlocks:**

```
reserved ─► generated ─► printed ─► registered ─► active ─► retired
                                                     └────► voided
```

Der Generator setzt primär `reserved` → `generated`. Die weiteren Zustände werden i. d. R. von KG-Tracker geführt und optional per Status-Endpoint zurückgespiegelt.

---

## 6. REST-API-Design

**Basis:** `/v1`, JSON, automatische OpenAPI-Doku unter `/docs`. Alle mutierenden Aufrufe unterstützen einen `Idempotency-Key`-Header.

**Authentifizierung:** Statischer **API-Key** (`X-API-Key`-Header oder Bearer-Token), als Env-Variable. Der Generator ist **nicht öffentlich erreichbar**, sondern nur im internen Docker-Netz gegenüber KG-Tracker.

| Methode & Pfad | Zweck |
|---|---|
| `POST /v1/airlocks:generate` | Batch erzeugen (Auto-Vergabe **oder** Vorgabe) |
| `GET /v1/airlocks/{code}` | Metadaten eines Locks |
| `GET /v1/airlocks/{code}/stl` | Einzelne STL herunterladen |
| `PATCH /v1/airlocks/{code}` | Status aktualisieren (`printed`, `registered`, …) |
| `GET /v1/airlocks` | Liste/Filter (Status, Batch) |
| `GET /v1/batches/{batch_id}` | Batch-Manifest |
| `GET /v1/batches/{batch_id}/zip` | Alle STLs des Batches als ZIP |
| `GET /healthz` / `GET /readyz` | Liveness / Readiness |

**Beispiel — Auto-Vergabe von 10 Codes:**

```json
{ "count": 10, "requested_by": "kg-tracker", "return_zip": true }
```

**Response `201 Created`** enthält `batch_id`, `status`, `count`, die Liste `airlocks` (mit `code`, `status`, `stl_url`, `stl_sha256`, `source`) und `zip_url`.

**Konfliktfälle:** vorgegebener Code bereits vergeben → `409` bzw. Teilerfolg `status: "partial"` mit `conflicts`; ungültiges Format → `422`; `count` über Limit → `400`.

---

## 7. Ablauf End-to-End

1. AI-Keyholderin ruft `POST /v1/airlocks:generate {count: 10}` auf.
2. Generator zieht 10 freie Codes, legt `reserved`-Einträge + Batch an.
3. Generator-Core rendert je Code eine STL, schreibt sie ins Ausgabe-Volume, Status → `generated`, SHA-256 berechnet.
4. ZIP wird gepackt; Response mit Manifest geht an KG-Tracker zurück; Dateien liegen zusätzlich im Volume für den Druck-PC.
5. KG-Tracker speichert die Codes als Airlock-Datensätze (Source-of-Truth), Status `registered`.
6. STLs werden gedruckt; optional `PATCH …/{code}` → `printed`.
7. Bei einer Verschluss-Anforderung wählt die AI-Keyholderin aus verfügbaren, registrierten Airlocks eines aus → `active`.

---

## 8. Docker & Deployment

**Image:** `python:3.12-slim` + `openscad` (headless) + `fonts-liberation`/`fonts-dejavu-core` + App-Code. Rendering ohne X-Server, binäre STL via `openscad --export-format binstl`.

Kein öffentliches Port-Mapping — Erreichbarkeit ausschließlich über das interne Netz `kg-internal`, das KG-Tracker teilt. Registry-DB und Ausgabe-Volume sind persistent; das Ausgabe-Volume wird zusätzlich vom Druck-PC gemountet oder per Sync abgeholt.

**Performance:** Ein OpenSCAD-Render dauert typ. wenige Sekunden; ein 10er-Batch liegt im niedrigen zweistelligen Sekundenbereich (sequentiell), parallelisierbar. CPU-gebunden, nicht speicherkritisch.

---

## 9. Integration mit KG-Tracker

**Aufrufrichtung:** KG-Tracker → Generator (synchron über REST). Der Generator ruft KG-Tracker **nicht** aktiv auf; optional ein Webhook `on_batch_complete` (später).

**Netz & Auth:** Beide Container im selben internen Docker-Netz; Zugriff über Servicenamen `airlock-generator:8000`; gemeinsames Shared-Secret als API-Key.

**Neu in KG-Tracker zu implementieren (separates Arbeitspaket):**
- **Airlock-Entität** — Code, Status, Batch, Zuordnung zu User/Device, Erstellungsdatum.
- **Batch-Import** — Übernahme des Generator-Manifests (Codes + Prüfsummen) als Source-of-Truth.
- **Statuspflege** — `registered` → `active` → `retired`; Verhindern der Doppelnutzung.
- **Lock-Auswahl** — bei Verschluss-Anforderung Auswahl aus verfügbaren, registrierten Airlocks; gewähltes Lock wird `active`.
- **Verifikations-Prüfung** — Abgleich der am Device abgelesenen Nummer gegen die registrierten Airlocks.

---

## 10. Sicherheit & Betrieb

**Zugriff:** kein öffentlicher Endpunkt; nur internes Netz + API-Key; optional mTLS/IP-Allowlist. Secrets nur als Env-Variablen.

**Eingaben:** strenge Validierung (Code-Regex `^\d{5}$`, Batch-Limit, JSON-Schema); Dateinamen deterministisch aus dem Code (keine Pfad-Injection); Rate-Limiting je Key.

**Determinismus & Nachvollziehbarkeit:** gleiche Eingabe → bytegleiche STL (SHA-256 in der Registry). Audit-Log aller Generierungen und Statuswechsel.

**Anti-Counterfeit (Ausblick):** Reine 5-stellige Nummern sind erratbar. Für höhere Fälschungssicherheit später möglich: kryptografische Signatur der Nummer (HMAC, in KG-Tracker verifiziert), Prüfziffer oder zusätzlicher QR/DataMatrix-Aufdruck — optionale Ausbaustufe.

---

## 11. Offene Entscheidungen

1. **Ausrichtung:** *Geklärt* — Vorlage per 180°-Y-Drehung in Sample-Ausrichtung + Normalisierung in den Ursprung (§2).
2. **Font:** *Weitgehend geklärt* — `Liberation Sans:style=Bold` mit `xscale = 0,9573`. Ein exakteres Match nur mit dem Original-CAD-Font; Rest-Abweichung sub-0,2 mm.
3. **Manifold-Merge:** 0,2 mm Einsinktiefe (empfohlen, bestätigt watertight).
4. **Erhaben vs. graviert:** Sample ist erhaben → übernommen. Gravur wäre abriebrobuster — als Option vormerken.
5. **Prüfziffer / Alphanumerik:** vorerst nein; als Feature-Flag vorsehen.
6. **Multi-Template:** Architektur erlaubt weitere Lock-Modelle als zusätzliche „Template-Profile" (siehe `app/config.py::TemplateProfile`).

---

## 12. Umsetzungs-Roadmap (Milestones)

1. **M1 — Generator-Core** ✅ OpenSCAD-Template + Python-Wrapper, Test gegen Sample.
2. **M2 — Registry & Vergabe** ✅ SQLite, Auto-Vergabe, Vorgabe-Modus, Status-Lebenszyklus.
3. **M3 — REST-API** ✅ Endpunkte, Auth, Idempotenz, ZIP + Volume, OpenAPI-Doku.
4. **M4 — Container** ✅ Dockerfile, docker-compose, Health-Checks, Persistenz.
5. **M5 — KG-Tracker-Integration** ⏳ Airlock-Entität, Batch-Import, Status/Lock-Auswahl (separates KG-Tracker-Arbeitspaket).
6. **M6 — Härtung** ⏳ Rate-Limiting, Audit-Log, Backups, optionale Anti-Counterfeit-Stufe.

Der Stand M1–M4 ist in diesem Repository implementiert und getestet.
