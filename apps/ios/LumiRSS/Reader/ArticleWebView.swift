import SwiftUI
import WebKit

/// WKWebView wrapper that renders exactly ONE document — the sandboxed
/// article HTML from `ArticleHTML.renderDocument`. Everything else is
/// denied:
///
/// - JavaScript disabled; no message handlers / native bridges exist.
/// - Non-persistent, empty website data store — the article view has no
///   cookies (the Lumi session lives only in URLSession's storage), so
///   third-party resources can never carry credentials.
/// - All navigation is cancelled by the policy delegate; link taps are
///   routed to the app-level handler (external, http/https only).
/// - Loading is driven by an identity-keyed document string, so state
///   writes (read/star) never rebuild the view or reset scroll.
struct ArticleWebView: UIViewRepresentable {
    final class Coordinator: NSObject, WKNavigationDelegate {
        var onLinkTap: ((URL) -> Void)?
        /// Document identity currently loaded into the web view; nil
        /// means "nothing loaded yet".
        var loadedDocumentID: String?

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            // 1) The initial document load (loadHTMLString arrives with
            //    an empty/about URL as a .other main-frame navigation).
            if navigationAction.navigationType == .other,
               navigationAction.targetFrame?.isMainFrame == true,
               let url = navigationAction.request.url,
               url.scheme == "about" || url.absoluteString.isEmpty {
                decisionHandler(.allow)
                return
            }
            if navigationAction.request.url == nil {
                decisionHandler(.cancel)
                return
            }
            // 2) Everything else — link taps, iframe loads, redirects —
            //    is cancelled; taps on http(s) links are surfaced to the
            //    app, which opens them externally.
            if navigationAction.navigationType == .linkActivated,
               let url = navigationAction.request.url,
               url.scheme == "http" || url.scheme == "https" {
                onLinkTap?(url)
            }
            decisionHandler(.cancel)
        }
    }

    /// Identity of the rendered document: changing it reloads (entry
    /// change, appearance flip). Same value = no reload, so state writes
    /// (read/star) never reset the reading position.
    let documentID: String
    let html: String
    let baseURL: URL?
    let onLinkTap: ((URL) -> Void)?

    func makeUIView(context: Context) -> WKWebView {
        let preferences = WKPreferences()
        preferences.javaScriptEnabled = false
        let configuration = WKWebViewConfiguration()
        configuration.preferences = preferences
        configuration.websiteDataStore = .nonPersistent()
        configuration.allowsInlineMediaPlayback = false
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.allowsLinkPreview = false
        webView.scrollView.alwaysBounceVertical = true
        context.coordinator.onLinkTap = onLinkTap
        context.coordinator.loadedDocumentID = documentID
        webView.loadHTMLString(html, baseURL: baseURL)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.onLinkTap = onLinkTap
        // Reload only when the document identity changed.
        if context.coordinator.loadedDocumentID != documentID {
            context.coordinator.loadedDocumentID = documentID
            webView.loadHTMLString(html, baseURL: baseURL)
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }
}
