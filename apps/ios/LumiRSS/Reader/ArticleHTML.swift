import Foundation

/// Controlled transforms + the render-boundary wrapper for article HTML.
///
/// Threat model: `contentHtml` from the BFF is UNTRUSTED upstream RSS
/// HTML (the contract says the client owns sanitizing before render).
/// The v1 iOS boundary is:
///
/// 1. **No scripting**: the WKWebView renders with JavaScript fully
///    disabled (`javaScriptEnabled = false`) — scripts cannot run, so
///    `<script>`, inline handlers and javascript: URLs are inert.
/// 2. **No navigation**: every navigation decision goes through the
///    navigation-policy delegate, which cancels all loads except the
///    initial `loadHTMLString`; link taps surface as decisions handled
///    by the app (http/https only, external browser sheet). No bridges,
///    no message handlers, no `WKScriptMessageHandler`.
/// 3. **Content lock-down via CSP**: a restrictive meta CSP blocks
///    fetches of anything except http(s) images — no external CSS,
///    fonts, frames, forms or tracking pixels beyond plain images.
///    No credentials exist inside this WKWebView (its cookie store is
///    a non-persistent, empty `WKWebsiteDataStore`), so third-party
///    resource loads can never carry the Lumi session.
/// 4. **Controlled transforms** (NOT sanitization, and never
///    regex-based "cleaning"): relative src/href are resolved against
///    the article's own URL, and a local stylesheet sizes content.
enum ArticleHTML {
    struct Options {
        var fontSize: Int = 17
        var baseURL: URL?
        var darkMode: Bool = false

        init(fontSize: Int = 17, baseURL: URL? = nil, darkMode: Bool = false) {
            self.fontSize = fontSize
            self.baseURL = baseURL
            self.darkMode = darkMode
        }
    }

    /// Wrap article HTML into the sandboxed render document.
    static func renderDocument(contentHtml: String, options: Options) -> String {
        let resolved = resolveRelativeURLs(in: contentHtml, baseURL: options.baseURL)
        let palette = options.darkMode ? darkPalette : lightPalette
        return """
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src http: https: data:; style-src 'unsafe-inline'; font-src 'none'; media-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'">
        <style>
        \(palette)
        body {
            font: -apple-system \(options.fontSize)px/-apple-system-body;
            line-height: 1.65;
            margin: 0;
            padding: 16px 16px calc(16px + env(safe-area-inset-bottom));
            word-break: break-word;
            overflow-wrap: anywhere;
        }
        img, video, table { max-width: 100%; }
        img { height: auto; border-radius: 8px; }
        table { border-collapse: collapse; }
        td, th { border: 1px solid currentColor; opacity: 0.35; padding: 4px 8px; }
        pre { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        code { font-family: ui-monospace, monospace; }
        a { color: var(--lumi-link); text-decoration: none; }
        blockquote {
            margin-left: 0; padding-left: 12px;
            border-left: 3px solid var(--lumi-quote);
            color: var(--lumi-muted);
        }
        figure { margin: 1em 0; }
        figcaption { color: var(--lumi-muted); font-size: 0.85em; }
        .lumi-fallback { padding: 24px 0; color: var(--lumi-muted); }
        </style>
        </head>
        <body>
        \(resolved)
        </body>
        </html>
        """
    }

    /// Degraded body when no HTML body exists (upstream missing/empty):
    /// render the safe plain-text version instead of a blank page.
    static func fallbackDocument(contentText: String?, options: Options) -> String {
        let text = (contentText ?? "").htmlEscaped
            .replacingOccurrences(of: "\n", with: "<br>")
        let body = text.isEmpty
            ? "<div class='lumi-fallback'>\(String(localized: "这篇文章没有可显示的正文"))</div>"
            : "<div class='lumi-fallback'>\(text)</div>"
        return renderDocument(contentHtml: body, options: options)
    }

    /// Resolve relative `src`/`href` attribute values against the
    /// article URL so upstream relative pointers become absolute
    /// (fetchable through the CSP image rule). Purely additive — this
    /// never removes or "cleans" markup; script-execution is impossible
    /// by configuration (JS off), not by filtering.
    static func resolveRelativeURLs(in html: String, baseURL: URL?) -> String {
        guard let baseURL else { return html }
        let pattern = #"(src|href)\s*=\s*("([^"]*)"|'([^']*)')"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return html
        }
        let range = NSRange(html.startIndex..<html.endIndex, in: html)
        let matches = regex.matches(in: html, options: [], range: range)
        var result = ""
        var cursor = html.startIndex
        for match in matches {
            guard let full = Range(match.range, in: html),
                  let name = Range(match.range(at: 1), in: html),
                  let value = Range(match.range(at: 3), in: html).map({ String(html[$0]) })
                      ?? Range(match.range(at: 4), in: html).map({ String(html[$0]) })
            else { continue }
            result += html[cursor..<full.lowerBound]
            result += "\(html[name])=\"\(absolute(value, baseURL: baseURL))\""
            cursor = full.upperBound
        }
        result += html[cursor...]
        return result
    }

    private static func absolute(_ value: String, baseURL: URL) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              !trimmed.contains("://"),
              !trimmed.hasPrefix("data:"),
              !trimmed.hasPrefix("mailto:"),
              !trimmed.hasPrefix("#"),
              let resolved = URL(string: trimmed, relativeTo: baseURL)?.absoluteURL,
              resolved.scheme != nil
        else { return value }
        return resolved.absoluteString
    }

    private static var lightPalette: String {
        """
        :root { --lumi-bg: #fafafa; --lumi-text: #1c1c1e; --lumi-muted: #6b7280;
                --lumi-link: #4f59ce; --lumi-quote: #d3d6f2; }
        body { background: #fafafa; color: #1c1c1e; }
        @media (prefers-color-scheme: dark) { body { background: #0f1116; color: #e5e7eb; } }
        """
    }

    private static var darkPalette: String {
        """
        :root { --lumi-bg: #0f1116; --lumi-text: #e5e7eb; --lumi-muted: #9ca3af;
                --lumi-link: #98a1ff; --lumi-quote: #3a3f5c; }
        body { background: #0f1116; color: #e5e7eb; }
        """
    }
}

private extension String {
    var htmlEscaped: String {
        replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }
}
