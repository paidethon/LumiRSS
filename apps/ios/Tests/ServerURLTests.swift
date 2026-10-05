import XCTest
@testable import LumiRSS

final class ServerURLTests: XCTestCase {
    func testBareHostGetsHTTPS() throws {
        let url = try ServerURL.normalize("rss.example.com")
        XCTAssertEqual(url.absoluteString, "https://rss.example.com")
    }

    func testTrailingPathAndAPISegmentDropped() throws {
        let url = try ServerURL.normalize("https://rss.example.com/api/v1/")
        XCTAssertEqual(url.absoluteString, "https://rss.example.com")
    }

    func testQueryAndFragmentDropped() throws {
        let url = try ServerURL.normalize("https://rss.example.com/?x=1#frag")
        XCTAssertEqual(url.absoluteString, "https://rss.example.com")
    }

    func testExplicitHTTPPreserved() throws {
        let url = try ServerURL.normalize("http://192.168.1.10:8080")
        XCTAssertEqual(url.absoluteString, "http://192.168.1.10:8080")
    }

    func testPortPreserved() throws {
        let url = try ServerURL.normalize("https://host.example.com:8443/path")
        XCTAssertEqual(url.absoluteString, "https://host.example.com:8443")
    }

    func testWhitespaceTrimmed() throws {
        let url = try ServerURL.normalize("  https://rss.example.com  \n")
        XCTAssertEqual(url.absoluteString, "https://rss.example.com")
    }

    func testEmptyRejected() {
        XCTAssertThrowsError(try ServerURL.normalize("   "))
    }

    func testUnsupportedSchemeRejected() {
        XCTAssertThrowsError(try ServerURL.normalize("ftp://example.com"))
        XCTAssertThrowsError(try ServerURL.normalize("javascript:alert(1)"))
    }

    func testUserinfoRejected() {
        XCTAssertThrowsError(try ServerURL.normalize("https://user:pass@example.com"))
    }

    func testGarbageRejected() {
        XCTAssertThrowsError(try ServerURL.normalize("https://"))
        XCTAssertThrowsError(try ServerURL.normalize("not a url at all"))
    }

    func testNormalizeIsIdempotent() throws {
        let once = try ServerURL.normalize("https://rss.example.com")
        let twice = try ServerURL.normalize(once.absoluteString)
        XCTAssertEqual(once, twice)
    }
}

final class ServerVersionTests: XCTestCase {
    func testCompatibleAtThree() {
        XCTAssertTrue(ServerVersion(version: "3.0.0", commit: "abc", apiVersion: 1).isCompatible)
        XCTAssertTrue(ServerVersion(version: "3.2.1", commit: "abc", apiVersion: 1).isCompatible)
    }

    func testIncompatibleBelowThree() {
        XCTAssertFalse(ServerVersion(version: "2.4.0", commit: "abc", apiVersion: 1).isCompatible)
        XCTAssertFalse(ServerVersion(version: "0.1.0", commit: "abc", apiVersion: 1).isCompatible)
    }

    func testGarbageVersionIsIncompatible() {
        XCTAssertFalse(ServerVersion(version: "unknown", commit: "abc", apiVersion: 1).isCompatible)
    }
}
