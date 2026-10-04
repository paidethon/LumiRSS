import Foundation

/// Disk cache for timeline pages and article bodies.
///
/// Scope and limits (deliberately honest about what v1 is):
/// - Keyed by server origin + account id (or username) — switching
///   server or account can never surface another account's data.
/// - Caches list pages (per scope) and entry bodies. Images are NOT
///   cached — offline article bodies reference online images.
/// - Bounded: LRU-ish trimming by file access date; atomic writes
///   (temp + rename) so a crash cannot leave a torn file; unreadable
///   entries are deleted and treated as a miss (self-healing).
/// - A network failure never deletes cache content; only explicit
///   "clear cache" (settings / logout) removes it.
final class EntryCache: @unchecked Sendable {
    struct Keys {
        let server: String
        let account: String
    }

    private let root: URL
    private let maxBytes: Int
    private let fileManager: FileManager
    private let queue = DispatchQueue(label: "lumirss.entrycache", qos: .utility)

    static func defaultRoot() -> URL {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        return caches.appendingPathComponent("EntryCache", isDirectory: true)
    }

    init(root: URL = EntryCache.defaultRoot(), maxBytes: Int = 64 * 1024 * 1024) {
        self.root = root
        self.maxBytes = maxBytes
        self.fileManager = FileManager.default
        try? fileManager.createDirectory(at: root, withIntermediateDirectories: true)
    }

    // MARK: - Paths

    private func directory(for keys: Keys) -> URL {
        let serverToken = keys.server
            .addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "server"
        let accountToken = keys.account
            .addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "account"
        return root.appendingPathComponent("\(serverToken)_\(accountToken)", isDirectory: true)
    }

    private func listURL(scopeKey: String, keys: Keys) -> URL {
        let name = "list_\(stableHash(scopeKey)).json"
        return directory(for: keys).appendingPathComponent(name)
    }

    private func entryURL(entryRef: String, keys: Keys) -> URL {
        let name = "entry_\(stableHash(entryRef)).json"
        return directory(for: keys).appendingPathComponent(name)
    }

    private func stableHash(_ input: String) -> String {
        var hash: UInt64 = 1_469_598_103_934_665_603
        for byte in input.utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 1_099_511_628_211
        }
        return String(format: "%016llx", hash)
    }

    // MARK: - Timeline pages

    struct CachedEnvelope<T: Codable>: Codable {
        var storedAt: Date
        var payload: T
    }

    func storeList(_ items: [ArticleListItem], scopeKey: String, keys: Keys) {
        let envelope = CachedEnvelope(storedAt: Date(), payload: items)
        write(encoder: JSONEncoder(), value: envelope, to: listURL(scopeKey: scopeKey, keys: keys))
    }

    func loadList(scopeKey: String, keys: Keys) -> [ArticleListItem]? {
        let url = listURL(scopeKey: scopeKey, keys: keys)
        guard let data = readFile(at: url) else { return nil }
        let decoder = JSONDecoder()
        guard let envelope = try? decoder.decode(CachedEnvelope<[ArticleListItem]>.self, from: data) else {
            try? fileManager.removeItem(at: url)
            return nil
        }
        touch(at: url)
        return envelope.payload
    }

    // MARK: - Article bodies

    func storeEntry(_ detail: ArticleDetail, keys: Keys) {
        let envelope = CachedEnvelope(storedAt: Date(), payload: detail)
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        write(encoder: encoder, value: envelope, to: entryURL(entryRef: detail.entryRef, keys: keys))
    }

    func loadEntry(entryRef: String, keys: Keys) -> ArticleDetail? {
        let url = entryURL(entryRef: entryRef, keys: keys)
        guard let data = readFile(at: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let envelope = try? decoder.decode(CachedEnvelope<ArticleDetail>.self, from: data) else {
            try? fileManager.removeItem(at: url)
            return nil
        }
        touch(at: url)
        return envelope.payload
    }

    // MARK: - Maintenance

    func clearAll() {
        queue.sync {
            guard let children = try? fileManager.contentsOfDirectory(
                at: root, includingPropertiesForKeys: nil
            ) else { return }
            for child in children {
                try? fileManager.removeItem(at: child)
            }
        }
    }

    func totalBytes() -> Int {
        queue.sync { Self.size(of: root, fileManager: fileManager) }
    }

    static func size(of directory: URL, fileManager: FileManager) -> Int {
        guard let children = try? fileManager.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: [.isDirectoryKey, .fileSizeKey]
        ) else { return 0 }
        var total = 0
        for child in children {
            if let isDir = try? child.resourceValues(forKeys: [.isDirectoryKey]).isDirectory, isDir {
                total += size(of: child, fileManager: fileManager)
            } else if let size = try? child.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                total += size
            }
        }
        return total
    }

    // MARK: - Primitives

    private func readFile(at url: URL) -> Data? {
        queue.sync { try? Data(contentsOf: url) }
    }

    private func write<T: Codable>(encoder: JSONEncoder, value: T, to url: URL) {
        queue.sync {
            try? fileManager.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            guard let data = try? encoder.encode(value) else { return }
            let tmp = url.deletingLastPathComponent()
                .appendingPathComponent(".tmp_\(UUID().uuidString)")
            do {
                try data.write(to: tmp, options: .atomic)
                _ = try fileManager.replaceItemAt(url, withItemAt: tmp)
                trimIfNeeded()
            } catch {
                try? fileManager.removeItem(at: tmp)
            }
        }
    }

    private func touch(at url: URL) {
        queue.sync {
            try? fileManager.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)
        }
    }

    private func trimIfNeeded() {
        // Called only on the queue.
        let budget = maxBytes
        var entries: [(url: URL, size: Int, date: Date)] = []
        guard let dirs = try? fileManager.contentsOfDirectory(at: root, includingPropertiesForKeys: nil) else {
            return
        }
        for dir in dirs {
            guard let files = try? fileManager.contentsOfDirectory(
                at: dir, includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey]
            ) else { continue }
            for file in files {
                let values = try? file.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
                let size = values?.fileSize ?? 0
                let date = values?.contentModificationDate ?? .distantPast
                entries.append((file, size, date))
            }
        }
        var total = entries.reduce(0) { $0 + $1.size }
        guard total > budget else { return }
        for oldest in entries.sorted(by: { $0.date < $1.date }) {
            guard total > budget else { break }
            try? fileManager.removeItem(at: oldest.url)
            total -= oldest.size
        }
    }
}
