import XCTest
@testable import LumiRSS

@MainActor
final class EntryStateStoreTests: XCTestCase {
    private func item(_ ref: String, read: Bool = false, starred: Bool = false) -> ArticleListItem {
        ArticleListItem(
            entryRef: ref, title: "t", feedTitle: "f",
            read: read, starred: starred
        )
    }

    func testHydrateSetsServerTruth() async {
        let store = EntryStateStore(writer: { _, _, _ in })
        store.hydrate(entryRef: "a", read: true, starred: false)
        XCTAssertTrue(store.readFlag(for: "a"))
        XCTAssertFalse(store.starredFlag(for: "a"))
    }

    func testSetSemanticsNeverToggles() async {
        var calls: [(String, Bool?, Bool?)] = []
        let store = EntryStateStore(writer: { ref, read, starred in
            calls.append((ref, read, starred))
        })
        store.hydrate(entryRef: "a", read: false, starred: false)
        await store.set(entryRef: "a", read: true)
        await store.set(entryRef: "a", read: true)
        await store.set(entryRef: "a", read: true)
        XCTAssertTrue(store.readFlag(for: "a"))
        XCTAssertEqual(calls.count, 3)
        // Every call asked the server for read=true — never a flip.
        XCTAssertTrue(calls.allSatisfy { $0.1 == true })
    }

    func testFailedWriteRollsBackAndFlags() async {
        struct Boom: Error {}
        let store = EntryStateStore(writer: { _, _, _ in throw Boom() })
        store.hydrate(entryRef: "a", read: false, starred: false)
        await store.set(entryRef: "a", starred: true)
        XCTAssertFalse(store.starredFlag(for: "a"), "rollback restores the previous flag")
        XCTAssertTrue(store.snapshot(for: "a")!.failed, "failure is visible to the UI")
    }

    func testOfflineWriteDoesNotPretendSuccess() async {
        let store = EntryStateStore(writer: { _, _, _ in }, canWrite: { false })
        store.hydrate(entryRef: "a", read: false, starred: false)
        await store.set(entryRef: "a", read: true)
        // Optimistic value kept for display but flagged unsynced.
        XCTAssertTrue(store.readFlag(for: "a"))
        XCTAssertTrue(store.snapshot(for: "a")!.failed)
    }

    func testReconcileKeepsInFlightOptimisticValue() async {
        // A writer that stays in flight until the test lets it finish.
        let store = EntryStateStore(writer: { _, _, _ in
            try await Task.sleep(nanoseconds: 400_000_000)
        })
        store.hydrate(entryRef: "a", read: false, starred: false)
        let write = Task { await store.set(entryRef: "a", read: true) }
        // Wait for the optimistic value to land (syncing == true).
        for _ in 0..<100 where !store.isSyncing("a") {
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertTrue(store.isSyncing("a"), "write should be in flight")
        // A concurrent refresh arrives claiming read=false — it must
        // not clobber the in-flight optimistic write.
        store.reconcile(with: [item("a", read: false, starred: false)])
        XCTAssertTrue(store.isSyncing("a"))
        _ = await write.value
        XCTAssertTrue(store.readFlag(for: "a"))
    }

    func testSuccessClearsFlags() async {
        let store = EntryStateStore(writer: { _, _, _ in })
        store.hydrate(entryRef: "a", read: false, starred: false)
        await store.set(entryRef: "a", read: true, starred: true)
        let snap = store.snapshot(for: "a")
        XCTAssertNotNil(snap)
        XCTAssertFalse(snap!.syncing)
        XCTAssertFalse(snap!.failed)
        XCTAssertTrue(snap!.read)
        XCTAssertTrue(snap!.starred)
    }
}
