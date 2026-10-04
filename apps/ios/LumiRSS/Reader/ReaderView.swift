import SwiftUI

/// Article reading screen: native chrome, sandboxed WKWebView body.
struct ReaderView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var model: ReaderViewModel?
    @AppStorage("readerFontSize") private var readerFontSize = 17
    @Environment(\.colorScheme) private var colorScheme
    @State private var shareItem: ExternalTarget?
    @State private var externalLink: ExternalTarget?
    @State private var showLinkConfirm: URL?

    let listTile: ArticleListItem

    var body: some View {
        Group {
            if let model {
                readerBody(model)
            } else {
                ProgressView(String(localized: "加载中…"))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(model?.detail?.title ?? listTile.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                starButton
                readButton
                Menu {
                    if let url = model?.originalURL {
                        Button {
                            shareItem = ExternalTarget(url: url)
                        } label: {
                            Label(String(localized: "分享"), systemImage: "square.and.arrow.up")
                        }
                        Button {
                            externalLink = ExternalTarget(url: url)
                        } label: {
                            Label(String(localized: "打开原文"), systemImage: "safari")
                        }
                    }
                    Stepper(
                        value: $readerFontSize,
                        in: 14...24
                    ) {
                        Label(String(localized: "字号 \(readerFontSize)"), systemImage: "textformat.size")
                    }
                } label: {
                    Label(String(localized: "更多"), systemImage: "ellipsis.circle")
                }
                .accessibilityLabel(String(localized: "更多操作"))
            }
        }
        .sheet(item: $shareItem) { target in
            ShareSheet(items: [target.url])
        }
        .sheet(item: $externalLink) { target in
            SFSafariView(url: target.url)
                .ignoresSafeArea()
        }
        .alert(
            String(localized: "打开外部链接"),
            isPresented: Binding(
                get: { showLinkConfirm != nil },
                set: { if !$0 { showLinkConfirm = nil } }
            )
        ) {
            Button(String(localized: "取消"), role: .cancel) {}
            if let url = showLinkConfirm {
                Button(String(localized: "在浏览器打开")) {
                    externalLink = ExternalTarget(url: url)
                }
            }
        } message: {
            if let url = showLinkConfirm {
                Text(url.host ?? url.absoluteString)
            }
        }
        .task {
            if model == nil {
                model = environment.makeReaderViewModel(listTile: listTile)
            }
            await model?.load()
        }
    }

    @ViewBuilder
    private func readerBody(_ model: ReaderViewModel) -> some View {
        switch model.phase {
        case .idle, .loading:
            VStack(spacing: 12) {
                ProgressView()
                Text(String(localized: "加载中…"))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .failed(let message):
            ContentUnavailableView {
                Label(String(localized: "无法加载文章"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
            } actions: {
                Button(String(localized: "重试")) {
                    Task { await model.load() }
                }
                .buttonStyle(.borderedProminent)
            }
        case .loadedOffline, .loadedOnline:
            ScrollView {
                header(model)
                if model.isOfflineBody {
                    Text(String(localized: "离线缓存内容 — 图片与最新状态需要联网"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.bottom, 4)
                }
                ArticleWebView(
                    documentID: "\(model.entryRef)-\(readerFontSize)-\(colorScheme == .dark)",
                    html: articleDocument(model),
                    baseURL: model.originalURL,
                    onLinkTap: { url in
                        // Only http/https survive the web view policy; the
                        // user confirms before leaving the app context.
                        showLinkConfirm = url
                    }
                )
                .frame(minHeight: 320)
                .padding(.horizontal, -16)
            }
        }
    }

    @ViewBuilder
    private func header(_ model: ReaderViewModel) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.detail?.title ?? listTile.title)
                .font(.title3.bold())
            HStack(spacing: 8) {
                Text(model.detail?.feedTitle ?? listTile.feedTitle)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.tint)
                if let author = model.detail?.author ?? listTile.author, !author.isEmpty {
                    Text(author)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if let date = model.detail?.publishedAt ?? listTile.publishedAt {
                    Text(LumiDate.listLabel(date))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.bottom, 8)
    }

    private func articleDocument(_ model: ReaderViewModel) -> String {
        let options = ArticleHTML.Options(
            fontSize: readerFontSize,
            baseURL: model.originalURL,
            darkMode: colorScheme == .dark
        )
        if let html = model.detail?.contentHtml, !html.isEmpty {
            return ArticleHTML.renderDocument(contentHtml: html, options: options)
        }
        return ArticleHTML.fallbackDocument(contentText: model.detail?.contentText, options: options)
    }

    private var starButton: some View {
        Button {
            guard let model else { return }
            Task { await model.toggleStarred() }
        } label: {
            Label(
                model?.starred == true ? String(localized: "取消收藏") : String(localized: "收藏"),
                systemImage: model?.starred == true ? "star.fill" : "star"
            )
            .symbolRenderingMode(.multicolor)
        }
        .disabled(model == nil)
        .accessibilityLabel(model?.starred == true ? String(localized: "取消收藏") : String(localized: "收藏"))
    }

    private var readButton: some View {
        Button {
            guard let model else { return }
            Task { await model.markRead(!model.read) }
        } label: {
            Label(
                model?.read == true ? String(localized: "标为未读") : String(localized: "标为已读"),
                systemImage: model?.read == true ? "envelope.open" : "envelope.badge"
            )
        }
        .disabled(model == nil)
        .accessibilityLabel(model?.read == true ? String(localized: "标为未读") : String(localized: "标为已读"))
    }
}

struct ExternalTarget: Identifiable {
    let id = UUID()
    let url: URL
}

extension ReaderView {
    static func openTarget(_ url: URL) -> ExternalTarget { ExternalTarget(url: url) }
}
