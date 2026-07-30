# Airlock NFC Writer (iOS) — Spezifikation & Implementierungsleitfaden

Diese Datei beschreibt Zweck, Architektur und API-Contract der nativen
iOS-Writer-App, damit eine Claude-Instanz (oder ein Mensch) sie in Xcode fertig
bauen kann. Sie ergänzt `AIRLOCK_NFC.md` aus dem KG-Tracker-Projekt.

## 1. Kontext & Rollen

Drei Komponenten, klare Trennung (Architektur „Weg A"):

- **Airlock3DSTLGenerator** (Docker, FastAPI) — **Source of Truth**. Erzeugt
  Druckdateien mit 5-stelligem Code, verwaltet die Registry und das NFC-Secret,
  signiert/validiert Tokens. Läuft im LAN, immer online.
- **KG-Tracker** (Next.js/Capacitor) — Frontend. **Liest** Tags und ruft
  `nfc/verify` auf. Schreibt keine Tags.
- **Airlock NFC Writer (dieses Projekt)** — native iOS-App, die die Tags
  **beschreibt** (Core NFC). Ersetzt Web NFC, das es auf iOS nicht gibt.

Warum eigene App: iOS/Safari hat **kein Web NFC**. Schreiben geht nur nativ über
**Core NFC** (kann NDEF lesen UND schreiben seit iOS 13).

## 2. Authentifizierung — Writer-Key

Die App nutzt einen **Writer-Key** (Präfix `alw_`), erzeugt im Airlock-Dashboard
unter „KG-Tracker" → „Writer-Keys" (Airlock ≥ v1.8.0). Scope des Keys:

- ERLAUBT: `GET /v1/airlocks`, `GET /v1/airlocks/{code}`,
  `POST /v1/airlocks/{code}/nfc/prepare`, `POST /v1/airlocks/{code}/nfc/commit`.
- VERBOTEN: generieren, STL/ZIP laden, Status ändern, `nfc/verify`, Key-/Secret-
  Verwaltung. (Das sind bewusst getrennte Scopes; KG-Keys `kgt_` dürfen umgekehrt
  nicht schreiben.)

Der Key wird als Header `X-API-Key: alw_…` gesendet. **Ein Key pro Gerät**, im
Dashboard einzeln widerrufbar/regenerierbar. Der volle `AIRLOCK_API_KEY` gehört
**nicht** auf ein mobiles Gerät.

Speicherung: Basis-URL in `UserDefaults`, Writer-Key im **iOS-Keychain**
(`kSecClassGenericPassword`, `…WhenUnlockedThisDeviceOnly`).

## 3. API-Contract (nur die genutzten Endpunkte)

Basis-URL im LAN, HTTPS (Caddy `tls internal`), z. B. `https://10.0.1.9:8453`.

### GET /v1/airlocks?limit=500
→ `[ { code, status, source, batch_id, nfc_uid, nfc_written_at }, … ]`
(Optional `?available=true` = nur Tag-gebundene, noch freie Locks.)

### POST /v1/airlocks/{code}/nfc/prepare   Body `{ "uid": "<HEX>" }`
→ `{ code, uid, token, ndef_text, secret_configured }`
- `uid`: **normalisierte** UID — genau diese an `commit` zurückgeben.
- `ndef_text`: exakt der String, der auf den Tag geschrieben wird:
  `AL1|<code>|<token>`.
- `secret_configured`: false ⇒ Server nutzt noch das Default-Secret ⇒ **abbrechen**
  und den Nutzer bitten, im Dashboard ein Secret zu setzen.

### POST /v1/airlocks/{code}/nfc/commit    Body `{ "uid": "<HEX>" }`
→ bindet die UID an den Code (`nfc_uid`). 409 bei Konflikt (UID schon an anderen
Code gebunden). **Erst nach erfolgreichem Schreiben** aufrufen.

## 4. NFC-Format auf dem Tag

Ein **NDEF-Text-Record** mit Inhalt `AL1|<code>|<token>`:
- `token = HMAC_SHA256(secret, "<code>|<UID>")`, erste 32 Hex-Zeichen, klein.
- Der Client berechnet den Token **nicht** selbst — er kommt fertig aus `prepare`.
- Text-Record-Sprache: `de` (konsistent mit dem Web-NFC-Pfad im Dashboard; die
  Verifikation hängt nur am Text-Inhalt, nicht an der Sprache).

## 5. UID-Normalisierung (muss zum Server passen)

Server (`app/nfc.py`): UID = Hex, **Großbuchstaben, ohne Trenner**, 8–20 Zeichen,
gerade Länge. Heuristik `canonicalUid`: NTAG-UID beginnt mit `04`; falls nicht,
Byte-Paare umdrehen (fängt iOS↔Android-Byteorder ab).

Core NFC liefert bei NTAG213/216 (`NFCMiFareTag.identifier`) die 7-Byte-UID
bereits **beginnend mit `0x04`** — also in kanonischer Reihenfolge. Der Client
schickt sie einfach als Großbuchstaben-Hex; der Server normalisiert final und gibt
die normierte UID in `prepare.uid` zurück (die für `commit` verwenden).

## 6. Core-NFC-Ablauf (eine Sitzung, ein Antippen)

Implementiert in `NFCWriterService.swift`:

1. `NFCTagReaderSession(pollingOption: .iso14443)` starten.
2. `didDetect` → Tag als `.miFare(NFCMiFareTag)` (NTAG = Type 2 / ISO 14443-A).
   Anderer Typ ⇒ Session mit Fehlermeldung beenden (nur NTAG213/216).
3. `session.connect(to:)`, dann `mifare.identifier` → UID-Hex.
4. `await api.prepare(code:uid:)`. `secret_configured == false` ⇒ abbrechen.
5. `NFCNDEFPayload.wellKnownTypeTextPayload(string: ndefText, locale: de)` →
   `NFCNDEFMessage`.
6. `mifare.queryNDEFStatus` (muss `.readWrite` sein) → `mifare.writeNDEF(message)`.
   Die completion-basierten Calls sind als `withCheckedThrowingContinuation`
   gekapselt.
7. `await api.commit(code:uid: payload.uid)`.
8. `session.invalidate()` mit Erfolgsmeldung.

Entitlement: **Near Field Communication Tag Reading** mit Formaten `NDEF` + `TAG`
(`AirlockWriter.entitlements`). Info.plist: `NFCReaderUsageDescription`.
Core NFC läuft **nur auf echter Hardware**, nicht im Simulator.

## 7. Dateiübersicht (Ist-Stand des Scaffolds)

| Datei | Zweck |
|---|---|
| `AirlockWriterApp.swift` | `@main`, injiziert `SettingsStore`. |
| `ContentView.swift` | Liste + „Schreiben"-Button, `SettingsView`. |
| `Models.swift` | `Airlock`, `PreparePayload`, `Connection`. |
| `AirlockAPI.swift` | REST-Client (list/prepare/commit), LAN-TLS-Trust. |
| `NFCWriterService.swift` | Core-NFC-Schreibfluss (siehe §6). |
| `SettingsStore.swift` | Basis-URL (UserDefaults) + Writer-Key (Keychain). |
| `UID.swift` | UID-Hex/Plausibilität. |
| `Info.plist` | `NFCReaderUsageDescription`. |
| `AirlockWriter.entitlements` | NFC-Formate `NDEF`+`TAG`. |

## 8. Offene Punkte / TODO

- **Xcode-Projekt (`.xcodeproj`) fehlt** — muss einmalig in Xcode angelegt werden
  (README, Abschnitt „Xcode-Projekt anlegen"). Alternativ ein Tuist/XcodeGen-
  `project.yml` ergänzen, damit das Projekt reproduzierbar generiert wird.
- **TLS-Trust härten:** `InsecureTrust` in `AirlockAPI.swift` akzeptiert jedes
  Serverzertifikat. Für Produktion: Caddy-Root-CA pinnen oder aufs Gerät
  installieren und den Delegate entfernen.
- **Fehler-UX:** 409 aus `commit` (UID-Konflikt) gezielt melden.
- **Batch-Schreiben:** optional mehrere Tags nacheinander in einer Session.
- **Kompilierung ist ungeprüft** (in dieser Umgebung kein iOS-SDK) — beim ersten
  Build in Xcode kleinere API-Anpassungen einplanen.

## 9. Testplan (auf echtem iPhone)

1. Einstellungen: Basis-URL + `alw_`-Key eintragen → Liste lädt Locks.
2. Falscher/kein Key → 401, klare Fehlermeldung.
3. Leeren NTAG213/216 an ein „generated" Lock schreiben → Erfolg; im Dashboard
   erscheint `nfc_uid` gebunden; `nfc_written_at` gesetzt.
4. Verifikation gegenprüfen (KG-Tracker oder `nfc/verify`): `valid: true`.
5. Denselben Tag an ein anderes Lock schreiben → `commit` 409, App meldet Konflikt.
6. Writer-Key im Dashboard widerrufen → App kann nicht mehr schreiben (401).
