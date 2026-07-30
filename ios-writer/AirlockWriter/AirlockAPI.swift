import Foundation

enum APIError: LocalizedError {
    case notConfigured
    case badURL
    case http(Int, String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "Basis-URL oder Writer-Key fehlt."
        case .badURL:        return "Ungültige Basis-URL."
        case .http(let c, let m): return "HTTP \(c): \(m)"
        case .decoding(let m):    return "Antwort nicht lesbar: \(m)"
        }
    }
}

/// Dünner REST-Client für die Airlock-API. Nutzt den Writer-Key (X-API-Key).
///
/// Genutzte Endpunkte (Writer-Scope, siehe CLAUDE.md):
///   GET  /v1/airlocks?available=true
///   POST /v1/airlocks/{code}/nfc/prepare   {"uid": "..."}
///   POST /v1/airlocks/{code}/nfc/commit    {"uid": "..."}
struct AirlockAPI {
    var connection: Connection

    /// Erlaubt selbstsignierte Caddy-`tls internal`-Zertifikate im LAN.
    /// (Für den Produktivbetrieb die Caddy-Root-CA aufs Gerät bringen und diesen
    /// Delegate entfernen.)
    private final class InsecureTrust: NSObject, URLSessionDelegate {
        func urlSession(_ session: URLSession,
                        didReceive challenge: URLAuthenticationChallenge,
                        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
            if let trust = challenge.protectionSpace.serverTrust {
                completionHandler(.useCredential, URLCredential(trust: trust))
            } else {
                completionHandler(.performDefaultHandling, nil)
            }
        }
    }

    private func makeRequest(_ path: String, method: String, body: [String: Any]? = nil) throws -> URLRequest {
        guard connection.isConfigured else { throw APIError.notConfigured }
        let base = connection.baseURL.trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: base + path) else { throw APIError.badURL }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(connection.writerKey, forHTTPHeaderField: "X-API-Key")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        return req
    }

    private func run(_ req: URLRequest) async throws -> Data {
        let session = URLSession(configuration: .ephemeral,
                                 delegate: InsecureTrust(), delegateQueue: nil)
        let (data, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse else {
            throw APIError.http(-1, "Keine HTTP-Antwort")
        }
        guard (200..<300).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? ""
            throw APIError.http(http.statusCode, msg)
        }
        return data
    }

    /// Verfügbare Locks (Tag gebunden ODER frei – hier ohne `available`, damit
    /// auch noch nicht getaggte Locks zum Beschreiben erscheinen).
    func listAirlocks(limit: Int = 500) async throws -> [Airlock] {
        let req = try makeRequest("/v1/airlocks?limit=\(limit)", method: "GET")
        let data = try await run(req)
        do { return try JSONDecoder().decode([Airlock].self, from: data) }
        catch { throw APIError.decoding("\(error)") }
    }

    func prepare(code: String, uid: String) async throws -> PreparePayload {
        let req = try makeRequest("/v1/airlocks/\(code)/nfc/prepare",
                                  method: "POST", body: ["uid": uid])
        let data = try await run(req)
        do { return try JSONDecoder().decode(PreparePayload.self, from: data) }
        catch { throw APIError.decoding("\(error)") }
    }

    @discardableResult
    func commit(code: String, uid: String) async throws -> Data {
        let req = try makeRequest("/v1/airlocks/\(code)/nfc/commit",
                                  method: "POST", body: ["uid": uid])
        return try await run(req)
    }
}
