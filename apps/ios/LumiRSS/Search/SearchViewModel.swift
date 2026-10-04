import Foundation
import Observation

/// Search against the real /api/v1/search endpoint. A new query
/// invalidates the previous one (generation counter) so stale results
/// can never overwrite a newer query.
@MainActor
@Observable
final class SearchViewModel {
    enum Phase: Equatable {
        case idle
        case searching
        case results
        case empty
        case failed(String)
    }

    private(set) var phase: Phase = .idle
    private(set) var results: [ArticleListItem] = []
    private(set) var nextCursor: String?
    private(set) var lastQuery: String = ""

    private let api: LumiAPIClient?
    private var generation = 0
    private var searchTask: Task<Void, Never>?

    init(api: LumiAPIClient?) {
        self.api = api
    }

    func search(_ rawQuery: String) {
        let query = rawQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        searchTask?.cancel()
        generation += 1
        let currentGeneration = generation
        guard !query.isEmpty else {
            results = []
            phase = .idle
            lastQuery = ""
            return
        }
        guard query != lastQuery || results.isEmpty else { return }
        phase = .searching
        lastQuery = query
        searchTask = Task { [weak self] in
            guard let self else { return }
            do {
                try Task.checkCancellation()
                guard let api = self.api else {
                    throw LumiAPIError.network("offline")
                }
                let page = try await api.search(query: query, cursor: nil)
                try Task.checkCancellation()
                guard self.generation == currentGeneration else { return }
                self.results = page.items.map(\.listTile)
                self.nextCursor = page.nextCursor
                self.phase = page.items.isEmpty ? .empty : .results
            } catch is CancellationError {
                // Superseded by a newer query — keep whatever it renders.
            } catch let error as LumiAPIError {
                guard self.generation == currentGeneration else { return }
                self.phase = .failed(error.userMessage)
            } catch {
                guard self.generation == currentGeneration else { return }
                self.phase = .failed(LumiAPIError.network(error.localizedDescription).userMessage)
            }
        }
    }

    func loadMore() async {
        guard case .results = phase, let cursor = nextCursor, !lastQuery.isEmpty, let api else { return }
        let currentGeneration = generation
        do {
            let page = try await api.search(query: lastQuery, cursor: cursor)
            guard generation == currentGeneration else { return }
            let known = Set(results.map(\.entryRef))
            for hit in page.items where !known.contains(hit.entryRef) {
                results.append(hit.listTile)
            }
            nextCursor = page.nextCursor
        } catch {
            // Keep current results; pagination just stops.
            nextCursor = nil
        }
    }
}
