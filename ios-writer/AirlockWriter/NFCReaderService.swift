import Foundation
@preconcurrency import CoreNFC

/// Liest einen Airlock-NFC-Tag zurück und verifiziert ihn serverseitig.
///
/// Zweck: „Tag prüfen" in der App — zeigt, WAS (roh + dekodiert) auf dem Tag
/// steht und ob der Server ihn als echt/gebunden bestätigt. Gleichzeitig ein
/// Diagnosewerkzeug: der rohe NDEF-Payload zeigt den Text-Record-Header
/// (Status-Byte + Sprachcode), den ein naiver Leser abschneiden muss.
///
/// Gleiche Concurrency-Regeln wie NFCWriterService (Core NFC callt auf eigener
/// Queue; seriell genutzt → `@unchecked Sendable`, `@preconcurrency import`).
final class NFCReaderService: NSObject, ObservableObject, NFCTagReaderSessionDelegate, @unchecked Sendable {

    private struct SendableBox<T>: @unchecked Sendable { let value: T }

    private var session: NFCTagReaderSession?
    private var api: AirlockAPI?
    private var continuation: CheckedContinuation<TagReport, Error>?

    /// Startet eine Lese-Sitzung und liefert den Prüfbericht.
    func read(api: AirlockAPI) async throws -> TagReport {
        guard NFCTagReaderSession.readingAvailable else {
            throw NSError(domain: "NFC", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "NFC ist auf diesem Gerät nicht verfügbar."])
        }
        self.api = api
        return try await withCheckedThrowingContinuation { cont in
            self.continuation = cont
            let s = NFCTagReaderSession(pollingOption: .iso14443, delegate: self, queue: nil)
            s?.alertMessage = "Tag zum Prüfen ans iPhone halten…"
            self.session = s
            s?.begin()
        }
    }

    // MARK: - NFCTagReaderSessionDelegate

    func tagReaderSessionDidBecomeActive(_ session: NFCTagReaderSession) {}

    func tagReaderSession(_ session: NFCTagReaderSession, didInvalidateWithError error: Error) {
        finish(.failure(error))
    }

    func tagReaderSession(_ session: NFCTagReaderSession, didDetect tags: [NFCTag]) {
        guard let tag = tags.first else { return }
        guard case let .miFare(mifare) = tag else {
            session.invalidate(errorMessage: "Nicht unterstützter Tag-Typ (NTAG213/216 verwenden).")
            return
        }
        let box = SendableBox(value: (session: session, mifare: mifare))
        session.connect(to: tag) { [weak self] error in
            guard let self else { return }
            let session = box.value.session
            if let error {
                session.invalidate(errorMessage: "Verbindung fehlgeschlagen: \(error.localizedDescription)")
                return
            }
            let uid = UID.hex(from: box.value.mifare.identifier)
            Task { await self.handle(mifare: box.value.mifare, uid: uid, session: box.value.session) }
        }
    }

    // MARK: - Ablauf

    private func handle(mifare: NFCMiFareTag, uid: String, session: NFCTagReaderSession) async {
        guard let api else { session.invalidate(errorMessage: "Kein API-Client."); return }
        do {
            session.alertMessage = "Lese Tag…"
            let message = try await readNDEF(from: mifare)

            var recordType = "keine NDEF-Nachricht"
            var decoded: String? = nil
            var rawHex = ""
            if let rec = message?.records.first {
                rawHex = rec.payload.map { String(format: "%02X", $0) }.joined(separator: " ")
                recordType = describe(rec)
                // SAUBER: Well-Known-Text-Record korrekt dekodieren (Header abgeschnitten).
                if let t = rec.wellKnownTypeTextPayload().0 {
                    decoded = t
                } else {
                    decoded = String(data: rec.payload, encoding: .utf8)
                }
            }

            var code: String? = nil
            var token: String? = nil
            var note: String? = nil
            if let d = decoded {
                let parts = d.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
                if parts.count == 3 && parts[0] == "AL1" {
                    code = parts[1]; token = parts[2]
                } else {
                    note = "Kein gültiger AL1|code|token-Record erkennbar."
                }
            } else if message == nil {
                note = "Der Tag enthält keine NDEF-Nachricht (leer/nicht beschrieben?)."
            }

            var server: VerifyResult? = nil
            if let c = code, let t = token {
                session.alertMessage = "Verifiziere…"
                server = try? await api.verify(code: c, uid: uid, token: t)
            }

            session.alertMessage = (server?.valid == true) ? "Tag gültig ✓" : "Tag gelesen"
            session.invalidate()
            finish(.success(TagReport(uid: uid, ndefFound: message != nil, recordType: recordType,
                                      decodedText: decoded, rawHex: rawHex, code: code, token: token,
                                      server: server, note: note)))
        } catch {
            session.invalidate(errorMessage: "Fehler: \(error.localizedDescription)")
            finish(.failure(error))
        }
    }

    /// NDEF lesen; leerer/nicht beschriebener Tag → nil (kein harter Fehler).
    private func readNDEF(from tag: NFCMiFareTag) async throws -> NFCNDEFMessage? {
        let status: NFCNDEFStatus = try await withCheckedThrowingContinuation { cont in
            tag.queryNDEFStatus { st, _, err in
                if let err { cont.resume(throwing: err) } else { cont.resume(returning: st) }
            }
        }
        if status == .notSupported { return nil }
        return await withCheckedContinuation { (cont: CheckedContinuation<NFCNDEFMessage?, Never>) in
            tag.readNDEF { msg, _ in cont.resume(returning: msg) }
        }
    }

    private func describe(_ rec: NFCNDEFPayload) -> String {
        switch rec.typeNameFormat {
        case .nfcWellKnown:
            let t = String(data: rec.type, encoding: .utf8) ?? "?"
            return "Well-Known „\(t)“ (Text)"
        case .absoluteURI: return "Absolute URI"
        case .media: return "Media/MIME"
        case .nfcExternal: return "External"
        case .empty: return "leer"
        default: return "TNF \(rec.typeNameFormat.rawValue)"
        }
    }

    private func finish(_ result: Result<TagReport, Error>) {
        guard let cont = continuation else { return }
        continuation = nil
        cont.resume(with: result)
    }
}
