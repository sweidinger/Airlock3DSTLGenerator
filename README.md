# Airlock-STL-Generator

Eigenständiger Docker-Service, der aus der leeren Vorlage `DisposableLock_v2.stl`
Airlock-STLs mit einer **erhabenen, 5-stelligen Nummer** erzeugt — zur Verifikation
eines Chastity-Devices in der **KG-Tracker App**. Die AI-Keyholderin steuert den
Generator über eine REST-API (z. B. „generiere 10 Airlocks mit je eindeutiger Nummer").

Ausführliches Konzept: siehe [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Funktionsumfang

- Erzeugt binäre STLs mit korrekt platziertem, erhabenem Code (validiert gegen das Original-Sample).
- **Kombinierte Eindeutigkeit:** Auto-Vergabe kollisionsfreier Zufallscodes **oder** Übernahme vorgegebener Codes; finale Hoheit bei KG-Tracker.
- Auslieferung als **ZIP über die API** und zusätzlich in ein **gemountetes Ausgabe-Volume** (für den Druck-PC).
- SQLite-Registry mit Status-Lebenszyklus (`reserved → generated → printed → registered → active → retired`).
- API-Key-Authentifizierung, Idempotenz-Schlüssel, Batch-Limit.
- Automatische OpenAPI-Doku unter `/docs`.

## Basis-Vorlage

Die leere Basis-STL `templates/DisposableLock_v2.stl` ist **im Repository enthalten** —
der Generator und die Tests laufen out-of-the-box. Du kannst sie durch deine eigene
Konstruktionsdatei ersetzen; die gegen die Vorlage validierten Präge-Parameter stehen
in `app/config.py` (`TemplateProfile`) und in `ARCHITECTURE.md` §2.

## Schnellstart (Docker)

```bash
cp .env.example .env          # AIRLOCK_API_KEY setzen!
# Für Standalone-Test in docker-compose.yml das ports-Mapping einkommentieren
# und beim network 'kg-internal' external:true entfernen.
docker compose up --build
```

Danach: `http://localhost:8000/docs`

## Lokal ohne Docker

```bash
sudo apt-get install openscad fonts-liberation fonts-dejavu-core
pip install -r requirements.txt
export AIRLOCK_API_KEY=dev-secret
uvicorn app.main:app --reload
```

## API-Kurzreferenz

Alle `/v1`-Endpunkte erfordern den Header `X-API-Key: <secret>` (oder `Authorization: Bearer <secret>`).

| Methode & Pfad | Zweck |
|---|---|
| `POST /v1/airlocks:generate` | Batch erzeugen (`count` **oder** `codes`) |
| `GET  /v1/airlocks/{code}` | Metadaten eines Locks |
| `GET  /v1/airlocks/{code}/stl` | STL herunterladen |
| `PATCH /v1/airlocks/{code}` | Status setzen (z. B. `printed`, `registered`) |
| `GET  /v1/airlocks` | Liste/Filter |
| `GET  /v1/batches/{id}` | Batch-Manifest |
| `GET  /v1/batches/{id}/zip` | Alle STLs des Batches als ZIP |
| `GET  /healthz`, `/readyz` | Health-Checks (ohne Auth) |

### Beispiel

```bash
curl -X POST http://localhost:8000/v1/airlocks:generate \
  -H "X-API-Key: dev-secret" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"count": 10, "requested_by": "kg-tracker"}'
```

Antwort (gekürzt):

```json
{
  "batch_id": "b_2f9a7c1d0e",
  "status": "completed",
  "count": 10,
  "airlocks": [
    {"code": "73412", "status": "generated",
     "stl_url": "/v1/airlocks/73412/stl", "stl_sha256": "…", "source": "auto"}
  ],
  "zip_url": "/v1/batches/b_2f9a7c1d0e/zip"
}
```

Konkrete Codes vorgeben:

```json
{ "codes": ["73412", "10098"], "requested_by": "kg-tracker" }
```

Bereits vergebene Codes werden als `conflicts` gemeldet (Status `partial`).

## Konfiguration (Umgebungsvariablen)

| Variable | Default | Bedeutung |
|---|---|---|
| `AIRLOCK_API_KEY` | `change-me-in-production` | Gemeinsames Geheimnis |
| `AIRLOCK_MAX_BATCH` | `200` | Max. Locks pro Batch |
| `AIRLOCK_OUTPUT_DIR` | `./output` | Ausgabe-Volume (STLs, ZIPs) |
| `AIRLOCK_DB_PATH` | `./data/registry.db` | SQLite-Registry |
| `AIRLOCK_CODE_LENGTH` | `5` | Stellenzahl der Codes |
| `OPENSCAD_BIN` | `openscad` | Pfad zur OpenSCAD-Binary |

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

Die Tests prüfen u. a., dass die generierte STL in Ausrichtung und Außenmaßen
mit dem Original-Sample übereinstimmt, dass die Prägung wasserdicht ist und dass
die API-Flows (Auto-Vergabe, Vorgabe/Konflikt, Idempotenz, Status) korrekt sind.

## Prägeparameter

Die gegen das Sample validierten Werte stehen als Defaults in
`app/config.py` (`TemplateProfile`) und in `ARCHITECTURE.md` §2. Kernpunkt:
Die Vorlage wird vor dem Prägen um 180° um die Y-Achse in die Sample-Ausrichtung
gebracht; der Code sitzt erhaben (0,585 mm) auf der Paddle-Fläche
(`Liberation Sans Bold`, size 4.31, xscale 0.9573).

## Integration mit KG-Tracker (separates Arbeitspaket)

KG-Tracker ruft den Generator im internen Docker-Netz auf, persistiert die
zurückgemeldeten Codes als Airlock-Datensätze (Source-of-Truth) und wählt bei
einer Verschluss-Anforderung ein registriertes Lock aus. Details in
`ARCHITECTURE.md` §9.
