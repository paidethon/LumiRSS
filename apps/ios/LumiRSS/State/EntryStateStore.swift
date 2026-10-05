import Foundation
import Observation

/// Single source of truth for entry read/starred state across every
/// surface (timeline, reader, favorites).
///
/// Semantics (mirrors the BFF contract):
/// - Writes are SET semantics: `mark(read: true)` twice never flips
///   back; a repeated "already read" is a no-op.
/// - Optimistic updates apply immediately; a failed write rolls the
///   flag back AND records a sync failure so UI can show "未同步".
/// - Opening an article never marks it read — only explicit actions do.
@MainActor
@Observable
final class EntryStateStore {
    struct Snapshot: Equatable {
        var read: Bool
        var starred: Bool
        var syncing: Bool
        var failed: Bool
    }

    private(set) var states: [String: Snapshot] = [:]

    /// Performs the server write (set semantics). Injected so tests
    /// can simulate success/failure/offline without a network stack.
    private let writer: (String, Bool?, Bool?) async throws -> Void
    private let canWrite: () -> Bool
    private var inFlight: Set<String> = []

    init(
        writer: @escaping (String, Bool?, Bool?) async throws -> Void,
        canWrite: @escaping () -> Bool = { true }
    ) {
        self.writer = writer
        self.canWrite = canWrite
    }

    func hydrate(entryRef: String, read: Bool, starred: Bool) {
        // Server truth wins over a stale optimistic local value when the
        // local one is settled (not syncing / not failed).
        if let current = states[entryRef], current.syncing || current.failed { return }
        states[entryRef] = Snapshot(read: read, starred: starred, syncing: false, failed: false)
    }

    func snapshot(for entryRef: String) -> Snapshot? { states[entryRef] }

    func readFlag(for entryRef: String) -> Bool { states[entryRef]?.read ?? false }
    func starredFlag(for entryRef: String) -> Bool { states[entryRef]?.starred ?? false }
    func isSyncing(_ entryRef: String) -> Bool { states[entryRef]?.syncing ?? false }

    /// Apply an optimistic change and push it to the server.
    /// Rolls back and flags a failure when the write errors.
    func set(entryRef: String, read: Bool? = nil, starred: Bool? = nil) async {
        let current = states[entryRef] ?? Snapshot(read: false, starred: false, syncing: false, failed: false)
        let previous = current

        // Set semantics: identical value = still push (server is the
        // authority; maybe it drifted) but no visual flip happens.
        var next = current
        if let read { next.read = read }
        if let starred { next.starred = starred }
        next.syncing = true
        next.failed = false
        states[entryRef] = next

        guard canWrite(), !inFlight.contains(entryRef) else {
            // No API (offline) or a write for this entry is already in
            // flight: do not pretend success.
            var offline = next
            offline.syncing = false
            offline.failed = true
            states[entryRef] = offline
            return
        }
        inFlight.insert(entryRef)
        do {
            try await writer(entryRef, read, starred)
            var settled = states[entryRef] ?? next
            settled.syncing = false
            settled.failed = false
            states[entryRef] = settled
        } catch {
            var rolled = states[entryRef] ?? next
            rolled.read = previous.read
            rolled.starred = previous.starred
            rolled.syncing = false
            rolled.failed = true
            states[entryRef] = rolled
        }
        inFlight.remove(entryRef)
    }

    /// Coalesce the server's view after a refresh so stale optimistic
    /// values do not resurrect.
    func reconcile(with items: [ArticleListItem]) {
        for item in items {
            if let current = states[item.entryRef], current.syncing || current.failed {
                // Optimistic write in progress — let it settle.
                continue
            }
            states[item.entryRef] = Snapshot(
                read: item.read, starred: item.starred, syncing: false, failed: false
            )
        }
    }
}
