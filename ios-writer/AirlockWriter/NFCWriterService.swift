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
/// Nicht `@MainActor`: Core NFC ruft die Delegate-Methoden auf seiner eigenen
/// Queue auf. Die Klasse wird immer seriell genutzt (nur eine Schreib-Sitzung
/// gleichzeitig), daher `@unchecked Sendable`.
final class NFCWriterService: NSObject, ObservableObject, NFCTagReaderSessionDelegate, @unchecked Sendable {

    struct WriteResult { let code: String; let uid: String }

    /// Reicht die nicht-Sendable Core-NFC-Objekte (`NFCTagReaderSession`,
    /// `NFCMiFareTag`) in den async-Kontext, ohne sie direkt einzufangen.
    /// Sicher, weil Core NFC sie seriell auf einer einzigen Queue liefert.
    private struct SendableBox<T>: @unchecked Sendable { let value: T }

    private var session: NFCTagReaderSession?
    private var api: AirlockAPI?
    private var code: String = ""
    private var rebind: Bool = false
    private var continuation: CheckedContinuation<WriteResult, Error>?

    /// Startet eine Schreib-Sitzung und liefert bei Erfolg die gebundene UID.
    /// `rebind=true` ersetzt bewusst eine bereits bestehende Tag-Bindung.
    func write(code: String, api: AirlockAPI, rebind: Bool = false) async throws -> WriteResult {
        guard NFCTagReaderSession.readingAvailable else {
            throw NSError(domain: "NFC", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "NFC ist auf diesem Gerät nicht verfügbar."])
        }
        self.api = api
        self.code = code
        self.rebind = rebind
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
        // session/mifare gebündelt durch die Box reichen -> keine nicht-Sendable Captures.
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
            try await api.commit(code: code, uid: payload.uid, rebind: rebind)

            session.alertMessage = "Tag geschrieben ✓"
            session.invalidate()
            finish(.success(WriteResult(code: code, uid: payload.uid)))
        } catch {
            session.invalidate(errorMessage: "Fehler: \(error.localizedDescription)")
            // Original-Fehler (z. B. HTTP 409 „bereits verheiratet") direkt an den
            // Aufrufer geben, damit die UI ein Neu-Verheiraten anbieten kann. Das
            // spätere didInvalidateWithError findet die Continuation dann leer vor.
            finish(.failure(error))
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
