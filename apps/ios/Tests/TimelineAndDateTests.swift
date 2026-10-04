import XCTest
@testable import LumiRSS

final class TimelineMergeTests: XCTestCase {
    private func item(_ ref: String, title: String = "t") -> ArticleListItem {
        ArticleListItem(entryRef: ref, title: title, feedTitle: "f", read: false, starred: false)
    }

    func testFirstPageAppendsAll() {
        let result = TimelineViewModel.merge(base: [], page: [item("a"), item("b"), item("c")])
        XCTAssertEqual(result.merged.map(\.entryRef), ["a", "b", "c"])
        XCTAssertEqual(result.added, 3)
    }

    func testSecondPageDeduplicates() {
        let base = [item("a"), item("b")]
        let result = TimelineViewModel.merge(base: base, page: [item("b"), item("c")])
        XCTAssertEqual(result.merged.map(\.entryRef), ["a", "b", "c"])
        XCTAssertEqual(result.added, 1)
    }

    func testRefreshBoundaryDuplicateRefreshesMetadata() {
        let base = [item("a", title: "old title")]
        let result = TimelineViewModel.merge(base: base, page: [item("a", title: "new title")])
        XCTAssertEqual(result.added, 0)
        XCTAssertEqual(result.merged.first?.title, "new title")
    }

    func testOrderStableAcrossManyPages() {
        var current: [ArticleListItem] = []
        for page in 0..<5 {
            let items = (0..<10).map { item("p\(page)-\($0)") }
            current = TimelineViewModel.merge(base: current, page: items).merged
        }
        XCTAssertEqual(current.count, 50)
        XCTAssertEqual(current.first?.entryRef, "p0-0")
        XCTAssertEqual(current.last?.entryRef, "p4-9")
    }
}

final class LumiDateTests: XCTestCase {
    func testParsesPlainISO() {
        let date = LumiDate.parse("2026-10-01T08:30:00+00:00")
        XCTAssertNotNil(date)
    }

    func testParsesFractionalISO() {
        let date = LumiDate.parse("2026-10-01T08:30:00.123456+00:00")
        XCTAssertNotNil(date)
    }

    func testParsesZulu() {
        let date = LumiDate.parse("2026-10-01T08:30:00Z")
        XCTAssertNotNil(date)
    }

    func testNilAndEmptyRejected() {
        XCTAssertNil(LumiDate.parse(nil))
        XCTAssertNil(LumiDate.parse(""))
        XCTAssertNil(LumiDate.parse("not a date"))
    }

    func testListLabelEmptyForNil() {
        XCTAssertEqual(LumiDate.listLabel(nil), "")
    }
}
