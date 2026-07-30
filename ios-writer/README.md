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

## Xcode-Projekt anlegen

Dieses Repo enthält die **Quelldateien**, aber (noch) kein `.xcodeproj`. So wird
daraus ein lauffähiges Projekt:

1. Xcode → **File ▸ New ▸ Project… ▸ iOS ▸ App**.
   - Product Name: `AirlockWriter`
   - Interface: **SwiftUI**, Language: **Swift**
   - Bundle Identifier: z. B. `de.sweidinger.airlockwriter`
2. Die generierte `ContentView.swift`/`…App.swift` löschen und **alle Dateien aus
   `AirlockWriter/` hier** ins Projekt ziehen („Copy items if needed" aus, da schon
   im Repo; sonst „Create groups").
3. **Signing & Capabilities**:
   - Team auswählen (Dein Apple-Dev-Account).
   - **+ Capability ▸ Near Field Communication Tag Reading**. Xcode legt die
     Entitlements an – Inhalt mit `AirlockWriter/AirlockWriter.entitlements`
     abgleichen (`NDEF` + `TAG`).
4. **Info.plist**: den Schlüssel `NFCReaderUsageDescription` setzen (siehe
   `AirlockWriter/Info.plist`).
5. Auf einem **echten iPhone** bauen und starten.

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
