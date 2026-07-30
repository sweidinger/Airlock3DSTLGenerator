import Foundation
@preconcurrency import CoreNFC

/// Schreibt einen Airlock-NFC-Tag per Core NFC.
///
/// Ablauf in EINER Sitzung (ein Antippen):
///   1. Tag erkennen, verbinden, UID lesen.
///   2. `nfc/prepare` mit der UID aufrufen → signierter `ndef_text`.
///   3. NDEF-Text-Record ("AL1|code|token") auf den Tag schreiben.
///   4. `nfc/commit` mit der (normalisierten) UID → Bindung in der Registry.
///
/// Voraussetzung: Capability „Near Field Communication Tag Reading" +
/// `NFCReaderUsageDescription` in Info.plist (siehe CLAUDE.md).
@MainActor
final class NFCWriterService: NSObject, ObservableObject, NFCTagReaderSessionDelegate {

    struct WriteResult { let code: String; let uid: String }

    private var session: NFCTagReaderSession?
    private var api: AirlockAPI?
    private var code: String = ""
    private var continuation: CheckedContinuation<WriteResult, Error>?

    /// Startet eine Schreib-Sitzung und liefert bei Erfolg die gebundene UID.
    func write(code: String, api: AirlockAPI) async throws -> WriteResult {
        guard NFCTagReaderSession.readingAvailable else {
            throw NSError(domain: "NFC", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "NFC ist auf diesem Gerät nicht verfügbar."])
        }
        self.api = api
        self.code = code
        return try await withCheckedThrowingContinuation { cont in
            self.continuation = cont
            let s = NFCTagReaderSession(pollingOption: .iso14443, delegate: self, queue: nil)
            s?.alertMessage = "Airlock \(code): Tag ans iPhone halten…"
            self.session = s
            s?.begin()
        }
    }

    // MARK: - NFCTagReaderSessionDelegate

    func tagReaderSessionDidBecomeActive(_ session: NFCTagReaderSession) {}

    func tagReaderSession(_ session: NFCTagReaderSession, didInvalidateWithError error: Error) {
        // Wird auch nach erfolgreichem invalidate() aufgerufen – nur melden,
        // wenn die Continuation noch offen ist (echter Abbruch/Fehler).
        finish(.failure(error))
    }

    func tagReaderSession(_ session: NFCTagReaderSession, didDetect tags: [NFCTag]) {
        guard let tag = tags.first else { return }
        guard case let .miFare(mifare) = tag else {
            session.invalidate(errorMessage: "Nicht unterstützter Tag-Typ (NTAG213/216 verwenden).")
            return
        }
        session.connect(to: tag) { [weak self] error in
            guard let self else { return }
            if let error {
                session.invalidate(errorMessage: "Verbindung fehlgeschlagen: \(error.localizedDescription)")
                return
            }
            let uid = UID.hex(from: mifare.identifier)
            Task { await self.handle(mifare: mifare, uid: uid, session: session) }
        }
    }

    // MARK: - Ablauf

    private func handle(mifare: NFCMiFareTag, uid: String, session: NFCTagReaderSession) async {
        guard let api else {
            session.invalidate(errorMessage: "Kein API-Client.")
            return
        }
        do {
            session.alertMessage = "Signiere Tag…"
            let payload = try await api.prepare(code: code, uid: uid)
            if !payload.secretConfigured {
                session.invalidate(errorMessage: "Achtung: NFC-Secret ist noch Default – erst im Dashboard setzen.")
                return
            }
            guard let record = NFCNDEFPayload.wellKnownTypeTextPayload(
                string: payload.ndefText, locale: Locale(identifier: "de")) else {
                session.invalidate(errorMessage: "NDEF-Record konnte nicht gebaut werden.")
                return
            }
            let message = NFCNDEFMessage(records: [record])

            session.alertMessage = "Schreibe Tag…"
            try await writeNDEF(message, to: mifare)

            // Bindung erst NACH erfolgreichem Schreiben bestätigen.
            try await api.commit(code: code, uid: payload.uid)

            session.alertMessage = "Tag geschrieben ✓"
            session.invalidate()
            finish(.success(WriteResult(code: code, uid: payload.uid)))
        } catch {
            session.invalidate(errorMessage: "Fehler: \(error.localizedDescription)")
            // finish() folgt über didInvalidateWithError.
        }
    }

    /// completion-basierte Core-NFC-Aufrufe als async kapseln.
    private func writeNDEF(_ message: NFCNDEFMessage, to tag: NFCMiFareTag) async throws {
        let status: NFCNDEFStatus = try await withCheckedThrowingContinuation { cont in
            tag.queryNDEFStatus { status, _, error in
                if let error { cont.resume(throwing: error) } else { cont.resume(returning: status) }
            }
        }
        guard status == .readWrite else {
            throw NSError(domain: "NFC", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Tag ist nicht beschreibbar (schreibgeschützt?)."])
        }
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            tag.writeNDEF(message) { error in
                if let error { cont.resume(throwing: error) } else { cont.resume(returning: ()) }
            }
        }
    }

    private func finish(_ result: Result<WriteResult, Error>) {
        guard let cont = continuation else { return }
        continuation = nil
        cont.resume(with: result)
    }
}
