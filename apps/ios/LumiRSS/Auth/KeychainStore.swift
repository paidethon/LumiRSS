import Foundation
import Security

/// Minimal keychain abstraction (generic-password class). Protocol so
/// unit tests run on the simulator without touching the real keychain.
protocol SessionStore {
    func readData(forKey key: String) -> Data?
    func writeData(_ data: Data, forKey key: String)
    func removeValue(forKey key: String)
    func removeAll()
}

enum KeychainError: Error {
    case unexpectedStatus(OSStatus)
}

/// Real device/simulator keychain via the Security framework.
struct SystemKeychain: SessionStore {
    private let service: String

    init(service: String = "io.github.paidethon.LumiRSS.session") {
        self.service = service
    }

    func readData(forKey key: String) -> Data? {
        var query = baseQuery(forKey: key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess else { return nil }
        return result as? Data
    }

    func writeData(_ data: Data, forKey key: String) {
        var query = baseQuery(forKey: key)
        let attributesToUpdate: [String: Any] = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributesToUpdate as CFDictionary)
        if updateStatus == errSecSuccess { return }
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(query as CFDictionary, nil)
    }

    func removeValue(forKey key: String) {
        SecItemDelete(baseQuery(forKey: key) as CFDictionary)
    }

    func removeAll() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
        ]
        SecItemDelete(query as CFDictionary)
    }

    private func baseQuery(forKey key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
    }
}

/// In-memory store for unit tests and SwiftUI previews.
final class MemoryStore: SessionStore {
    private var storage: [String: Data] = [:]
    private let lock = NSLock()

    func readData(forKey key: String) -> Data? {
        lock.lock(); defer { lock.unlock() }
        return storage[key]
    }

    func writeData(_ data: Data, forKey key: String) {
        lock.lock(); defer { lock.unlock() }
        storage[key] = data
    }

    func removeValue(forKey key: String) {
        lock.lock(); defer { lock.unlock() }
        storage.removeValue(forKey: key)
    }

    func removeAll() {
        lock.lock(); defer { lock.unlock() }
        storage.removeAll()
    }
}
