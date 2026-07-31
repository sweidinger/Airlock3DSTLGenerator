# NFC-Tags: Echtheits- und Kopierschutz für Airlocks

## Warum

Die geprägte Nummer identifiziert einen Lock, schützt aber nicht gegen
**Duplizieren** (die Druckdatei mehrfach drucken). Ein in den Druck eingebetteter
NFC-Tag (NTAG213/215/216) schließt diese Lücke, weil jeder Tag eine ab Werk
**eindeutige, unveränderliche UID** besitzt.

Zwei Angriffe, zwei Abwehrmechanismen:

- **Fälschung** (gültige Nummer erfinden): ausgeschlossen durch den signierten
  Token — ohne das Geheimnis lässt sich kein gültiger Token erzeugen.
- **Duplizieren** (gültige Nummer kopieren): auffällig, weil ein Nachdruck einen
  anderen Tag (andere UID) hätte; der Token ist an genau eine UID gebunden, und
  in der Registry ist ein Code nur für **eine** aktive Schließung gültig.

Rest-Risiko: sogenannte „magic tags" mit änderbarer UID. Dagegen greift die
Registry-Einmal-Logik (derselbe Code/UID kann nicht gleichzeitig zweimal aktiv
sein) und die eindeutige UID-Bindung.

## Format auf dem Tag

Ein NDEF-**Text-Record** mit dem Inhalt:

```
AL1|<code>|<token>
```

- `code` — die 5-stellige Airlock-Nummer.
- `token` — `HMAC_SHA256(secret, "<code>|<UID>")`, die ersten **32 Hex-Zeichen**
  (128 Bit). Kleinschreibung.
- `UID` — Tag-UID als Hex, **Großbuchstaben, ohne Trenner** (z. B. `04A1B2C3D4E580`).

Das Geheimnis `secret` wird im **Dashboard → „KG-Tracker" → NFC-Secret** verwaltet
(erzeugen, verschlüsseltes Backup exportieren/wiederherstellen; in der DB
gespeichert). Alternativ per `AIRLOCK_NFC_SECRET` (Env) setzen — eine gesetzte
Env-Variable hat **Vorrang** vor dem DB-Wert. Ein neues Secret macht alle bereits
beschriebenen Tags ungültig, daher: einmal setzen, Backup sichern, nicht rotieren.

API (voller Key): `GET /v1/nfc/secret/status`, `POST /v1/nfc/secret/generate`
(`{confirm:true}`), `…/backup` (`{password}`), `…/restore`
(`{password,backup,confirm}`).

## API (Generator)

- `POST /v1/airlocks/{code}/nfc/prepare`  Body `{"uid": "..."}`
  → `{"code","uid","token","ndef_text","secret_configured"}`.
  Liefert den zu schreibenden Payload (UID muss vorher bekannt sein, z. B. vom
  Reader gelesen).
- `POST /v1/airlocks/{code}/nfc/commit`  Body `{"uid": "...", "rebind": false}`
  → speichert die UID am Code (`nfc_uid`). Eine Bindung ist **endgültig**:
  - Ist der Code bereits mit einem **anderen** Tag verheiratet → **409**.
    Erneutes Schreiben **desselben** Tags auf denselben Code ist erlaubt (idempotent).
  - `rebind: true` ersetzt die bestehende Bindung bewusst durch einen neuen
    (freien) Tag; die Antwort enthält dann ein `warning`.
  - Hängt die UID noch an einem **anderen** Code, ist ein Umzug nur mit
    `rebind: true` **und** gesetztem `AIRLOCK_BETA_TAG_MOVE=1` (Beta) möglich
    (der Tag wird dort gelöst; `warning` weist darauf hin). Sonst → **409**.
- `POST /v1/airlocks/{code}/nfc/verify`  Body `{"uid","token"}`
  → `{"valid": bool, "reason": "...", ...}`. Für den KG-Tracker.

## Verifikation im KG-Tracker (später)

1. Tag lesen → **UID** (Hardware) und **NDEF-Text** (`AL1|code|token`).
2. Entweder den Generator aufrufen: `POST /v1/airlocks/{code}/nfc/verify` mit
   `{uid, token}` …
3. … oder offline mit demselben `secret` prüfen:
   `token == HMAC_SHA256(secret, "<code>|<UID_normalisiert>")[:32]`,
   und zusätzlich prüfen, dass die UID die für diesen Code registrierte ist und
   der Status nicht `retired`/`voided` ist.

`reason`-Werte: `unknown_code`, `bad_uid`, `bad_signature`, `uid_mismatch`,
`status_retired`, `status_voided`.

## Schreiben (Dashboard)

Pro Airlock gibt es einen **NFC**-Button:

- **Web NFC** (Android + Chrome, über **HTTPS**): liest die Tag-UID, holt den
  signierten Payload, schreibt den Text-Record und bindet die UID – ein Tap.
- **Fallback** (iPhone / eigenes NFC-Tool): UID eingeben → „Payload erzeugen" →
  mit dem eigenen Tool auf den Tag schreiben → „Als geschrieben bestätigen".

> **iOS:** Safari unterstützt Web NFC nicht (OS-Grenze). Auf dem iPhone geht das
> Schreiben nur über eine native App oder ein NFC-Tool + den Fallback. Später
> kann die native KG-Tracker-App das per Core NFC übernehmen.

### Writer-Keys (native iOS-Writer-App)

Damit eine native App die Tags per Core NFC beschreiben kann, ohne dass der
**volle** API-Key aufs Gerät wandert, gibt es **Writer-Keys** (`alw_…`): eigener
Dashboard-Bereich „KG-Tracker" → „Writer-Keys". Ein Writer-Key darf Airlocks
**lesen** und Tags **beschreiben** (`nfc/prepare`, `nfc/commit`) — aber nicht
generieren, herunterladen, den Status wechseln oder verifizieren. Ein Key pro
Gerät, einzeln widerrufbar. API (voller Key): `POST/GET /v1/writer/keys`,
`…/revoke`, `…/regenerate`. Die KG-Tracker-Keys (`kgt_…`) bleiben davon getrennt
und dürfen weiterhin **nicht** schreiben.

## HTTPS (für Web NFC nötig)

Web NFC/WebUSB brauchen einen „secure context". Dafür liegt ein optionaler
Caddy-Reverse-Proxy bei:

```
AIRLOCK_UPSTREAM=airlock-generator:8000 \
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d
# -> https://<nas-host>:8443
```

Für warnungsfreie Nutzung die Caddy-Root-CA (`/data/caddy/pki/authorities/local/root.crt`
im caddy_data-Volume) auf dem Gerät/Handy installieren; alternativ die
Browser-Warnung einmalig akzeptieren.

## Hardware-Empfehlung

- **Tags:** NTAG213 (144 B) reicht; NTAG215/216 bei mehr Reserve. Als Inlay/
  Sticker in eine Aussparung der Vorlage einlegen (Design-Anpassung am Lock).
- **Reader (Phase 2, USB):** PN532 oder ACR122U, per WebUSB/Web-Serial am Gerät,
  auf dem das Dashboard offen ist.
