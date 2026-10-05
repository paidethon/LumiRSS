import Foundation
import Observation

/// Categories + subscriptions for the 订阅 tab.
@MainActor
@Observable
final class SubscriptionsViewModel {
    enum Phase: Equatable {
        case idle
        case loading
        case loaded
        case failed(String)
    }

    private(set) var phase: Phase = .idle
    private(set) var categories: [CategorySummary] = []
    private(set) var feeds: [FeedSummary] = []

    private let api: LumiAPIClient?

    init(api: LumiAPIClient?) {
        self.api = api
    }

    func loadIfNeeded() async {
        if case .loaded = phase { return }
        await load()
    }

    func load() async {
        guard phase != .loading else { return }
        phase = .loading
        guard let api else {
            phase = .failed(String(localized: "离线 — 订阅列表需要联网"))
            return
        }
        do {
            let cats = try await api.categories()
            let subs = try await api.subscriptions()
            categories = cats.sorted { $0.label.localizedCaseInsensitiveCompare($1.label) == .orderedAscending }
            feeds = subs.sorted { $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending }
            phase = .loaded
        } catch let error as LumiAPIError {
            phase = .failed(error.userMessage)
        } catch {
            phase = .failed(LumiAPIError.network(error.localizedDescription).userMessage)
        }
    }

    /// Feeds without a category (server may return category: null).
    var uncategorized: [FeedSummary] {
        feeds.filter { $0.categoryId == nil }
    }

    func feeds(in category: CategorySummary) -> [FeedSummary] {
        feeds.filter { $0.categoryId == category.categoryId }
    }
}
