import Foundation

/// UID-Normalisierung – muss zur Server-Logik (app/nfc.py) passen.
///
/// Der Server erwartet die Tag-UID als Hex in Großbuchstaben, ohne Trenner,
/// 8–20 Zeichen, gerade Länge. Core NFC liefert die UID von NTAG213/216
/// (NFC-Forum Type 2) als `Data`, deren Bytes bei NTAG mit `0x04` beginnen –
/// also bereits in der kanonischen Reihenfolge, die der Server erwartet.
enum UID {
    /// Wandelt die rohen UID-Bytes (z. B. `mifareTag.identifier`) in den
    /// Hex-String um, den `nfc/prepare` / `nfc/commit` erwarten.
    static func hex(from data: Data) -> String {
        data.map { String(format: "%02X", $0) }.joined()
    }

    /// Grundprüfung analog zum Server (nur Hex, gerade Länge, 8–20 Zeichen).
    static func isPlausible(_ hex: String) -> Bool {
        let up = hex.uppercased()
        guard up.count >= 8, up.count <= 20, up.count % 2 == 0 else { return false }
        return up.allSatisfy { $0.isHexDigit }
    }
}
