import Foundation
import Security

/// Speichert die Basis-URL in UserDefaults und den Writer-Key im iOS-Keychain.
/// Der Writer-Key ist ein Secret – daher NICHT in UserDefaults, sondern im
/// Keychain (kSecClassGenericPassword).
@MainActor
final class SettingsStore: ObservableObject {
    @Published var baseURL: String {
        didSet { UserDefaults.standard.set(baseURL, forKey: Keys.baseURL) }
    }
    @Published var writerKey: String {
        didSet { Keychain.set(writerKey, account: Keys.writerKey) }
    }

    private enum Keys {
        static let baseURL = "airlock.baseURL"
        static let writerKey = "airlock.writerKey"
    }

    init() {
        self.baseURL = UserDefaults.standard.string(forKey: Keys.baseURL) ?? ""
        self.writerKey = Keychain.get(account: Keys.writerKey) ?? ""
    }

    var connection: Connection { Connection(baseURL: baseURL, writerKey: writerKey) }
}

/// Minimaler Keychain-Wrapper für ein einzelnes Secret pro Account.
enum Keychain {
    private static let service = "de.sweidinger.airlockwriter"

    @discardableResult
    static func set(_ value: String, account: String) -> Bool {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
    }

    static func get(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
