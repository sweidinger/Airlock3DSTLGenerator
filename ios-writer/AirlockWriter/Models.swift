import Foundation

/// Ein Airlock, wie ihn `GET /v1/airlocks` liefert (Teilmenge der Felder).
struct Airlock: Codable, Identifiable, Hashable {
    let code: String
    let status: String
    let source: String?
    let batchId: String?
    let nfcUid: String?
    let nfcWrittenAt: String?

    var id: String { code }
    var hasTag: Bool { (nfcUid?.isEmpty == false) }

    enum CodingKeys: String, CodingKey {
        case code, status, source
        case batchId = "batch_id"
        case nfcUid = "nfc_uid"
        case nfcWrittenAt = "nfc_written_at"
    }
}

/// Antwort von `POST /v1/airlocks/{code}/nfc/prepare`.
struct PreparePayload: Codable {
    let code: String
    let uid: String          // normalisierte UID (genau so an /commit zurückgeben)
    let token: String
    let ndefText: String     // exakt dieser String kommt auf den Tag: "AL1|code|token"
    let secretConfigured: Bool
    let url: String?          // optionaler Universal-Link-URL-Record (Tag Record 0)

    enum CodingKeys: String, CodingKey {
        case code, uid, token, url
        case ndefText = "ndef_text"
        case secretConfigured = "secret_configured"
    }
}

/// Antwort von `POST /v1/airlocks/{code}/nfc/verify` (Server prüft Signatur/UID/Status).
struct VerifyResult: Codable {
    let valid: Bool
    let reason: String?
    let code: String?
    let uid: String?
    let status: String?
    let boundUid: String?

    enum CodingKeys: String, CodingKey {
        case valid, reason, code, uid, status
        case boundUid = "bound_uid"
    }
}

/// Ergebnis des „Tag prüfen"-Rücklesens: was steht (roh und dekodiert) auf dem
/// Tag, wie wurde es geparst und was sagt der Server dazu.
struct TagReport: Identifiable {
    let id = UUID()
    let uid: String
    let ndefFound: Bool
    let recordType: String
    let decodedText: String?
    let rawHex: String
    let code: String?
    let token: String?
    let server: VerifyResult?
    let note: String?
}

/// Verbindungs-/Zugangsdaten (Basis-URL + Writer-Key).
struct Connection {
    var baseURL: String      // z. B. https://10.0.1.9:8453
    var writerKey: String    // alw_… (Writer-Key aus dem Airlock-Dashboard)

    /// Eingaben getrimmt (führende/abschließende Leerzeichen aus Copy&Paste raus).
    var trimmedBaseURL: String { baseURL.trimmingCharacters(in: .whitespacesAndNewlines) }
    var trimmedWriterKey: String { writerKey.trimmingCharacters(in: .whitespacesAndNewlines) }

    /// Eingerichtet = beide Felder gefüllt. Ob der Key gültig ist, entscheidet der
    /// Server (siehe „Verbindung testen"), nicht eine starre Präfix-Prüfung.
    var isConfigured: Bool {
        !trimmedBaseURL.isEmpty && !trimmedWriterKey.isEmpty
    }
}
