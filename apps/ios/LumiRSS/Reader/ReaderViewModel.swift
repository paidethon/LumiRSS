import Foundation
import Observation

/// Loads and renders one article; read/star writes go through the
/// shared `EntryStateStore` (single source of truth).
@MainActor
@Observable
final class ReaderViewModel {
    enum LoadPhase: Equatable {
        case idle
        case loading
        case loadedOffline
        case loadedOnline
        case failed(String)
    }

    private(set) var phase: LoadPhase = .idle
    private(set) var detail: ArticleDetail?
    private(set) var isOfflineBody = false

    let listTile: ArticleListItem
    private let api: LumiAPIClient?
    private let cache: EntryCache
    private let cacheKeys: EntryCache.Keys
    private unowned let stateStore: EntryStateStore

    init(
        listTile: ArticleListItem,
        api: LumiAPIClient?,
        cache: EntryCache,
        cacheKeys: EntryCache.Keys,
        stateStore: EntryStateStore
    ) {
        self.listTile = listTile
        self.api = api
        self.cache = cache
        self.cacheKeys = cacheKeys
        self.stateStore = stateStore
        stateStore.hydrate(
            entryRef: listTile.entryRef, read: listTile.read, starred: listTile.starred
        )
    }

    var entryRef: String { listTile.entryRef }

    var read: Bool { stateStore.readFlag(for: entryRef) }
    var starred: Bool { stateStore.starredFlag(for: entryRef) }

    func markRead(_ value: Bool) async {
        await stateStore.set(entryRef: entryRef, read: value)
    }

    func toggleStarred() async {
        await stateStore.set(entryRef: entryRef, starred: !starred)
    }

    func load() async {
        guard phase != .loading else { return }
        phase = .loading
        // Offline-first: show the cached body immediately when present.
        if let cached = cache.loadEntry(entryRef: entryRef, keys: cacheKeys) {
            detail = cached
            stateStore.hydrate(entryRef: entryRef, read: cached.read, starred: cached.starred)
        }
        guard let api else {
            if detail != nil {
                isOfflineBody = true
                phase = .loadedOffline
            } else {
                phase = .failed(String(localized: "离线且没有缓存这篇文章"))
            }
            return
        }
        do {
            let fresh = try await api.entry(entryRef: entryRef)
            detail = fresh
            isOfflineBody = false
            cache.storeEntry(fresh, keys: cacheKeys)
            stateStore.hydrate(entryRef: entryRef, read: fresh.read, starred: fresh.starred)
            phase = .loadedOnline
        } catch let error as LumiAPIError {
            if detail != nil {
                // Keep showing the cached body; surface the failure subtly.
                isOfflineBody = true
                phase = .loadedOffline
            } else {
                phase = .failed(error.userMessage)
            }
        } catch {
            phase = .failed(LumiAPIError.network(error.localizedDescription).userMessage)
        }
    }

    var originalURL: URL? {
        guard let raw = detail?.url ?? listTile.url, let url = URL(string: raw),
              url.scheme == "http" || url.scheme == "https" else { return nil }
        return url
    }
}
