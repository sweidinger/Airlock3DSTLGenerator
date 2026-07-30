# Airlock NFC Writer (iOS)

Native iOS-App zum **Beschreiben** der Airlock-NFC-Tags per **Core NFC** – als
Ersatz für Web NFC, das es auf iPhone/Safari nicht gibt. Die App liest die
Tag-UID, holt vom Airlock-Server einen signierten Payload und schreibt ihn auf
den Tag (NTAG213/216). Sie ist bewusst schlank: eine dedizierte „Werkstatt"-App,
keine Portierung des KG-Trackers.

> Diese App **schreibt** Tags. Das **Lesen/Verifizieren** im Alltag macht die
> KG-Tracker-App gegen `POST /v1/airlocks/{code}/nfc/verify`. Der Airlock-Server
> bleibt Source of Truth (Weg A).

## Was sie kann

- Verfügbare Airlocks vom Server auflisten (`GET /v1/airlocks`).
- Ein Lock auswählen und den NFC-Tag in **einem Antippen** beschreiben:
  UID lesen → `nfc/prepare` → NDEF-Text schreiben → `nfc/commit`.
- Basis-URL + Writer-Key in den Einstellungen (Key nur im iOS-Keychain).

## Voraussetzungen

- iPhone mit iOS 15+ (NTAG-Schreiben via `NFCTagReaderSession`).
- **Apple Developer Account** (Core NFC läuft nicht im Simulator und braucht ein
  signiertes Entitlement).
- Ein **Writer-Key** aus dem Airlock-Dashboard → „KG-Tracker" → „Writer-Keys"
  (beginnt mit `alw_`). Airlock-App ≥ **v1.8.0**.

## Xcode-Projekt erzeugen (XcodeGen — empfohlen)

Das `.xcodeproj` ist **nicht** eingecheckt, sondern wird reproduzierbar aus
`project.yml` generiert (Bundle-ID, iOS-Target, Info.plist- und
Entitlements-Zuordnung stehen dort):

```
brew install xcodegen        # einmalig
cd ios-writer
xcodegen generate            # erzeugt AirlockWriter.xcodeproj
open AirlockWriter.xcodeproj
```

Dann im Projekt unter **Signing & Capabilities** dein Apple-Team wählen (oder in
`project.yml` `DEVELOPMENT_TEAM` setzen) und auf einem **echten iPhone** bauen.
Die NFC-Capability (`NDEF` + `TAG`) und `NFCReaderUsageDescription` sind über
`AirlockWriter.entitlements` bzw. `AirlockWriter/Info.plist` bereits gesetzt.

> `AirlockWriter.xcodeproj` gehört nicht ins Git (regenerierbar) und ist in
> `.gitignore` ausgenommen.

### Alternative: von Hand anlegen

1. Xcode → **File ▸ New ▸ Project… ▸ iOS ▸ App** (SwiftUI/Swift), Bundle-ID
   `de.sweidinger.airlockwriter`.
2. Die generierte `ContentView.swift`/`…App.swift` löschen, die Dateien aus
   `AirlockWriter/` ins Projekt ziehen.
3. **+ Capability ▸ Near Field Communication Tag Reading**; Entitlements mit
   `AirlockWriter/AirlockWriter.entitlements` abgleichen.
4. `INFOPLIST_FILE` auf `AirlockWriter/Info.plist` zeigen lassen (bzw.
   `NFCReaderUsageDescription` setzen).
5. Auf einem echten iPhone bauen.

## Einrichten & Benutzen

1. App öffnen → Zahnrad (Einstellungen).
2. **Basis-URL** eintragen, z. B. `https://10.0.1.9:8453` (der Caddy-HTTPS-Port).
3. **Writer-Key** eintragen (`alw_…`), im Dashboard erzeugt.
4. Zurück zur Liste → bei einem Lock **„Schreiben"** → leeren Tag ans iPhone.

## HTTPS / Zertifikat (LAN)

Der Airlock-Server läuft im LAN hinter Caddy mit `tls internal` (selbstsigniert).
Die App akzeptiert dieses Zertifikat aktuell über einen `URLSessionDelegate`
(`InsecureTrust` in `AirlockAPI.swift`) – praktisch fürs LAN, aber unsicher gegen
MITM. **Für den Dauerbetrieb:** die Caddy-Root-CA aufs iPhone bringen
(Profil installieren + unter *Einstellungen ▸ Allgemein ▸ Info ▸
Zertifikatsvertrauen* aktivieren) und den `InsecureTrust`-Delegate entfernen.

## Sicherheit

- Der Writer-Key hat **nur** Schreib-/Leserechte (prepare/commit/list), nicht den
  vollen API-Key. Verlorenes Gerät → Key im Dashboard einzeln widerrufen.
- Key liegt im **Keychain** (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`),
  nicht in UserDefaults.

## Dateien

Siehe `CLAUDE.md` für die vollständige Spezifikation (Architektur, API-Contract,
Core-NFC-Ablauf, UID-Normalisierung, offene Punkte).
