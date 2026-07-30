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

    enum CodingKeys: String, CodingKey {
        case code, uid, token
        case ndefText = "ndef_text"
        case secretConfigured = "secret_configured"
    }
}

/// Verbindungs-/Zugangsdaten (Basis-URL + Writer-Key).
struct Connection {
    var baseURL: String      // z. B. https://10.0.1.9:8453
    var writerKey: String    // alw_… (Writer-Key aus dem Airlock-Dashboard)

    var isConfigured: Bool {
        !baseURL.trimmingCharacters(in: .whitespaces).isEmpty &&
        writerKey.hasPrefix("alw_")
    }
}
