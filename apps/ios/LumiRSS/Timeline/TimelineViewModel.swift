import Foundation
import Observation

/// Timeline list state for one scope (all / unread / starred / feed).
///
/// Pagination contract: `nextCursor` is opaque — passed back verbatim,
/// never parsed, never invented. Pages are merged with stable
/// de-duplication by entryRef; a refresh resets pagination; switching
/// scope cancels in-flight work via the generation counter.
@MainActor
@Observable
final class TimelineViewModel {
    enum Phase: Equatable {
        case idle
        case loadingInitial
        case showingOfflineCache
        case loaded(hasMore: Bool)
        case loadingMore
        case failed(String)
    }

    private(set) var phase: Phase = .idle
    private(set) var items: [ArticleListItem] = []
    private(set) var nextCursor: String?
    private(set) var filteredCount: Int = 0
    private(set) var isRefreshing = false

    let scope: TimelineScope
    private let api: LumiAPIClient?
    private let cache: EntryCache
    private let cacheKeys: EntryCache.Keys
    private unowned let stateStore: EntryStateStore

    /// Monotonic generation: bumped on scope change/refresh teardown so
    /// a stale page response can never overwrite a newer scope's list.
    private var generation = 0
    private var initialLoaded = false

    var scopeKey: String {
        switch scope {
        case .all: return "all"
        case .unread: return "unread"
        case .starred: return "starred"
        case .feed(let ref):
            if let url = ref.feedUrl { return "feed:\(url)" }
            if let id = ref.categoryId { return "category:\(id)" }
            return "feed:unknown"
        }
    }

    init(
        scope: TimelineScope,
        api: LumiAPIClient?,
        cache: EntryCache,
        cacheKeys: EntryCache.Keys,
        stateStore: EntryStateStore
    ) {
        self.scope = scope
        self.api = api
        self.cache = cache
        self.cacheKeys = cacheKeys
        self.stateStore = stateStore
    }

    var hasMore: Bool { nextCursor != nil }

    // MARK: - Loading

    func loadInitialIfNeeded() async {
        guard !initialLoaded else { return }
        initialLoaded = true
        await loadInitial()
    }

    func loadInitial() async {
        generation += 1
        let currentGeneration = generation
        guard phase != .loadingInitial else { return }
        phase = .loadingInitial

        // Offline first: cached page makes the list instantly usable.
        if items.isEmpty, let cached = cache.loadList(scopeKey: scopeKey, keys: cacheKeys) {
            items = Self.merge(base: [], page: cached).merged
            stateStore.reconcile(with: items)
            phase = .showingOfflineCache
        }

        guard let api else {
            if items.isEmpty {
                phase = .failed(String(localized: "离线且没有缓存"))
            } else {
                phase = .showingOfflineCache
            }
            return
        }
        do {
            let page = try await api.timeline(scope: scope, cursor: nil)
            guard generation == currentGeneration else { return }
            let merged = Self.merge(base: [], page: page.items)
            items = merged.merged
            nextCursor = page.nextCursor
            filteredCount = page.filteredCount ?? 0
            stateStore.reconcile(with: page.items)
            cache.storeList(page.items, scopeKey: scopeKey, keys: cacheKeys)
            phase = .loaded(hasMore: page.nextCursor != nil)
        } catch let error as LumiAPIError {
            guard generation == currentGeneration else { return }
            if items.isEmpty {
                phase = .failed(error.userMessage)
            } else {
                // A failed refresh must not wipe what's on screen.
                phase = .loaded(hasMore: nextCursor != nil)
            }
        } catch {
            guard generation == currentGeneration else { return }
            phase = items.isEmpty
                ? .failed(LumiAPIError.network(error.localizedDescription).userMessage)
                : .loaded(hasMore: nextCursor != nil)
        }
    }

    func loadMoreIfNeeded(currentItem: ArticleListItem) async {
        guard case .loaded(let hasMore) = phase, hasMore,
              currentItem.entryRef == items.suffix(5).first?.entryRef || currentItem.entryRef == items.last?.entryRef
        else { return }
        await loadMore()
    }

    func loadMore() async {
        guard case .loaded(let hasMore) = phase, hasMore, let cursor = nextCursor, !isRefreshing else {
            return
        }
        let currentGeneration = generation
        phase = .loadingMore
        guard let api else {
            phase = .loaded(hasMore: nextCursor != nil)
            return
        }
        do {
            let page = try await api.timeline(scope: scope, cursor: cursor)
            guard generation == currentGeneration else { return }
            let result = Self.merge(base: items, page: page.items)
            items = result.merged
            nextCursor = page.nextCursor
            stateStore.reconcile(with: page.items)
            // Refresh the cache with the union we now hold.
            cache.storeList(result.merged, scopeKey: scopeKey, keys: cacheKeys)
            phase = .loaded(hasMore: page.nextCursor != nil)
        } catch {
            guard generation == currentGeneration else { return }
            phase = .loaded(hasMore: nextCursor != nil)
        }
    }

    func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        await loadInitial()
    }

    /// Server truth after an external change (e.g. state write from the
    /// reader) — refresh flags in place without rebuilding the list.
    func syncFlags() {
        // Flags are read from the shared EntryStateStore by the rows;
        // nothing to copy here.
    }

    // MARK: - State passthrough

    func readFlag(_ entryRef: String) -> Bool { stateStore.readFlag(for: entryRef) }
    func starredFlag(_ entryRef: String) -> Bool { stateStore.starredFlag(for: entryRef) }
    func isSyncing(_ entryRef: String) -> Bool { stateStore.isSyncing(entryRef) }

    func toggleRead(_ item: ArticleListItem) async {
        await stateStore.set(entryRef: item.entryRef, read: !stateStore.readFlag(for: item.entryRef))
    }

    func toggleStarred(_ item: ArticleListItem) async {
        await stateStore.set(entryRef: item.entryRef, starred: !stateStore.starredFlag(for: item.entryRef))
    }

    // MARK: - Pagination merge (pure, unit-tested)

    /// Merge a fetched page into the current list, keeping first-seen
    /// order and dropping duplicate entryRefs (stable across refresh
    /// boundaries where upstream repeats items).
    static func merge(base: [ArticleListItem], page: [ArticleListItem]) -> (merged: [ArticleListItem], added: Int) {
        var seen = Set(base.map(\.entryRef))
        var merged = base
        var added = 0
        for item in page {
            if seen.insert(item.entryRef).inserted {
                merged.append(item)
                added += 1
            } else if let index = merged.firstIndex(where: { $0.entryRef == item.entryRef }) {
                // Fresh copy of an already-seen item refreshes its metadata.
                merged[index] = item
            }
        }
        return (merged, added)
    }
}
