import XCTest
@testable import LumiRSS

final class EntryCacheTests: XCTestCase {
    private var tempDir: URL!

    override func setUpWithError() throws {
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cache-tests-\(UUID().uuidString)", isDirectory: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempDir)
    }

    private func makeCache(maxBytes: Int = 64 * 1024 * 1024) -> EntryCache {
        EntryCache(root: tempDir, maxBytes: maxBytes)
    }

    private let alice = EntryCache.Keys(server: "https://rss.a.example", account: "alice")
    private let bob = EntryCache.Keys(server: "https://rss.a.example", account: "bob")
    private let otherServer = EntryCache.Keys(server: "https://rss.b.example", account: "alice")

    private func listItem(_ ref: String) -> ArticleListItem {
        ArticleListItem(
            entryRef: ref, title: "标题 \(ref)", feedTitle: "feed",
            read: false, starred: false
        )
    }

    func testListRoundTrip() {
        let cache = makeCache()
        cache.storeList([listItem("a"), listItem("b")], scopeKey: "all", keys: alice)
        let loaded = cache.loadList(scopeKey: "all", keys: alice)
        XCTAssertEqual(loaded?.map(\.entryRef), ["a", "b"])
    }

    func testScopeIsolation() {
        let cache = makeCache()
        cache.storeList([listItem("x")], scopeKey: "unread", keys: alice)
        XCTAssertNil(cache.loadList(scopeKey: "all", keys: alice))
        XCTAssertEqual(cache.loadList(scopeKey: "unread", keys: alice)?.count, 1)
    }

    func testAccountIsolation() {
        let cache = makeCache()
        cache.storeList([listItem("secret")], scopeKey: "all", keys: alice)
        XCTAssertNil(cache.loadList(scopeKey: "all", keys: bob), "another account must not see alice's cache")
        XCTAssertNotNil(cache.loadList(scopeKey: "all", keys: alice))
    }

    func testServerIsolation() {
        let cache = makeCache()
        cache.storeList([listItem("secret")], scopeKey: "all", keys: alice)
        XCTAssertNil(cache.loadList(scopeKey: "all", keys: otherServer))
    }

    func testEntryRoundTripWithDates() {
        let cache = makeCache()
        let detail = ArticleDetail(
            entryRef: "rss:1", title: "标题", feedTitle: "feed",
            author: "作者", url: "https://example.com/a",
            publishedAt: Date(timeIntervalSince1970: 1_760_000_000),
            crawledAt: nil, read: true, starred: false,
            contentHtml: "<p>正文</p>", contentText: "正文", feedUrl: "https://feed"
        )
        cache.storeEntry(detail, keys: alice)
        let loaded = cache.loadEntry(entryRef: "rss:1", keys: alice)
        XCTAssertEqual(loaded?.entryRef, "rss:1")
        XCTAssertEqual(loaded?.title, "标题")
        XCTAssertEqual(loaded?.publishedAt, detail.publishedAt)
        XCTAssertEqual(loaded?.contentHtml, "<p>正文</p>")
    }

    func testCorruptFileSelfHeals() throws {
        let cache = makeCache()
        cache.storeList([listItem("a")], scopeKey: "all", keys: alice)
        // Corrupt every file in the account directory.
        let dir = tempDir
        for file in try FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) where file.hasDirectoryPath {
            for inner in try FileManager.default.contentsOfDirectory(at: file, includingPropertiesForKeys: nil) {
                try Data("not json {{{".utf8).write(to: inner)
            }
        }
        XCTAssertNil(cache.loadList(scopeKey: "all", keys: alice), "corrupt cache reads as a miss, not a crash")
    }

    func testClearAllRemovesEverything() {
        let cache = makeCache()
        cache.storeList([listItem("a")], scopeKey: "all", keys: alice)
        cache.storeList([listItem("b")], scopeKey: "all", keys: bob)
        cache.clearAll()
        XCTAssertNil(cache.loadList(scopeKey: "all", keys: alice))
        XCTAssertNil(cache.loadList(scopeKey: "all", keys: bob))
        XCTAssertEqual(cache.totalBytes(), 0)
    }

    func testCapacityTrimEvictsOldestFirst() {
        let cache = makeCache(maxBytes: 2 * 1024)
        // ~200B each: 20 items exceed the 2KB budget.
        for index in 0..<20 {
            let entry = ArticleDetail(
                entryRef: "e\(index)", title: String(repeating: "标", count: 80),
                feedTitle: "f", read: false, starred: false,
                contentHtml: String(repeating: "x", count: 80), contentText: nil, feedUrl: nil
            )
            cache.storeEntry(entry, keys: alice)
            Thread.sleep(forTimeInterval: 0.02)
        }
        XCTAssertLessThan(cache.totalBytes(), 4 * 1024, "cache stays near its budget")
        XCTAssertNil(cache.loadEntry(entryRef: "e0", keys: alice), "oldest evicted")
        XCTAssertNotNil(cache.loadEntry(entryRef: "e19", keys: alice), "newest kept")
    }
}
