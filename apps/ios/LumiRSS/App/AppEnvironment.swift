import Foundation
import Observation

/// Composition root: owns the session controller, shared state store
/// and cache, and builds feature view models against them.
@MainActor
@Observable
final class AppEnvironment {
    let session: SessionController
    let entryState: EntryStateStore
    let cache: EntryCache

    var api: LumiAPIClient? { session.api }

    init(session: SessionController, cache: EntryCache = EntryCache()) {
        self.session = session
        self.cache = cache
        // Strong capture is safe: the store never outlives this
        // environment, and the closure does not capture the environment.
        self.entryState = EntryStateStore(
            writer: { entryRef, read, starred in
                guard let api = session.api else {
                    throw LumiAPIError.network("offline")
                }
                _ = try await api.setEntryState(entryRef: entryRef, read: read, starred: starred)
            },
            canWrite: { session.api != nil }
        )
    }

    static func live() -> AppEnvironment {
        AppEnvironment(session: SessionController())
    }

    var cacheKeys: EntryCache.Keys {
        EntryCache.Keys(
            server: session.serverOrigin?.absoluteString ?? "no-server",
            account: session.account?.userId ?? session.account?.username ?? "anonymous"
        )
    }

    // MARK: - View model factories

    func makeTimelineViewModel(scope: TimelineScope) -> TimelineViewModel {
        TimelineViewModel(
            scope: scope,
            api: session.api,
            cache: cache,
            cacheKeys: cacheKeys,
            stateStore: entryState
        )
    }

    func makeReaderViewModel(listTile: ArticleListItem) -> ReaderViewModel {
        ReaderViewModel(
            listTile: listTile,
            api: session.api,
            cache: cache,
            cacheKeys: cacheKeys,
            stateStore: entryState
        )
    }

    func makeSubscriptionsViewModel() -> SubscriptionsViewModel {
        SubscriptionsViewModel(api: session.api)
    }

    func makeSearchViewModel() -> SearchViewModel {
        SearchViewModel(api: session.api)
    }

    // MARK: - Actions

    func logout() async {
        cache.clearAll()
        await session.logout()
    }

    func clearCache() {
        cache.clearAll()
    }
}
