import XCTest
@testable import LumiRSS

final class ArticleHTMLTests: XCTestCase {
    private let options = ArticleHTML.Options(
        fontSize: 17,
        baseURL: URL(string: "https://feed.example.com/posts/1"),
        darkMode: false
    )

    func testDocumentEmbedsRestrictiveCSP() {
        let doc = ArticleHTML.renderDocument(contentHtml: "<p>hi</p>", options: options)
        XCTAssertTrue(doc.contains("Content-Security-Policy"))
        XCTAssertTrue(doc.contains("default-src 'none'"))
        XCTAssertTrue(doc.contains("img-src http: https: data:"))
        XCTAssertFalse(doc.contains("script-src"))
    }

    func testFontSizeApplied() {
        let doc = ArticleHTML.renderDocument(contentHtml: "<p>x</p>", options: options)
        XCTAssertTrue(doc.contains("font: -apple-system 17px"))

        let bigger = ArticleHTML.renderDocument(
            contentHtml: "<p>x</p>",
            options: ArticleHTML.Options(fontSize: 22, baseURL: nil, darkMode: false)
        )
        XCTAssertTrue(bigger.contains("font: -apple-system 22px"))
    }

    func testRelativeImageSrcResolved() {
        let html = "<img src=\"/img/cat.png\">"
        let doc = ArticleHTML.resolveRelativeURLs(in: html, baseURL: options.baseURL)
        XCTAssertTrue(doc.contains("https://feed.example.com/img/cat.png"), doc)
    }

    func testRelativeHrefResolved() {
        let html = "<a href='../next'>next</a>"
        let doc = ArticleHTML.resolveRelativeURLs(in: html, baseURL: URL(string: "https://example.com/a/b/page"))
        XCTAssertTrue(doc.contains("https://example.com/a/next"), doc)
    }

    func testAbsoluteAndSpecialURLsUntouched() {
        let html = "<a href='https://x.example/p'>a</a><a href='mailto:a@b.c'>m</a><a href='#top'>t</a><img src='data:image/png;base64,AAAA'>"
        let resolved = ArticleHTML.resolveRelativeURLs(in: html, baseURL: options.baseURL)
        XCTAssertTrue(resolved.contains("https://x.example/p"))
        XCTAssertTrue(resolved.contains("mailto:a@b.c"))
        XCTAssertTrue(resolved.contains("#top"))
        XCTAssertTrue(resolved.contains("data:image/png;base64,AAAA"))
    }

    func testSingleQuotedAttributesResolved() {
        let html = "<img src='/pic.jpg'>"
        let resolved = ArticleHTML.resolveRelativeURLs(in: html, baseURL: URL(string: "https://example.com"))
        XCTAssertTrue(resolved.contains("https://example.com/pic.jpg"), resolved)
    }

    func testFallbackEscapesPlainText() {
        let doc = ArticleHTML.fallbackDocument(contentText: "<script>alert(1)</script>", options: options)
        XCTAssertTrue(doc.contains("&lt;script&gt;"))
        XCTAssertFalse(doc.contains("<script>alert"))
    }

    func testFallbackEmptyShowsHonestMessage() {
        let doc = ArticleHTML.fallbackDocument(contentText: nil, options: options)
        XCTAssertTrue(doc.contains("lumi-fallback"))
    }

    func testNoBaseURLLeavesMarkupUntouched() {
        let html = "<img src='/x.png'>"
        let resolved = ArticleHTML.resolveRelativeURLs(in: html, baseURL: nil)
        XCTAssertEqual(resolved, html)
    }
}
