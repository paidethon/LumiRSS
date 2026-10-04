import SwiftUI

/// 订阅 tab: categories with their feeds, uncategorized feeds, and a
/// plain "all sources" fallback section; tapping opens the feed's
/// timeline.
struct SubscriptionsView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var model: SubscriptionsViewModel?

    var body: some View {
        Group {
            if let model {
                content(model)
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(String(localized: "订阅"))
        .task {
            if model == nil {
                model = environment.makeSubscriptionsViewModel()
            }
            await model?.loadIfNeeded()
        }
    }

    @ViewBuilder
    private func content(_ model: SubscriptionsViewModel) -> some View {
        switch model.phase {
        case .idle, .loading:
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .failed(let message):
            ContentUnavailableView {
                Label(String(localized: "无法加载订阅"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
            } actions: {
                Button(String(localized: "重试")) {
                    Task { await model.load() }
                }
                .buttonStyle(.borderedProminent)
            }
        case .loaded:
            if model.feeds.isEmpty {
                ContentUnavailableView(
                    String(localized: "还没有订阅"),
                    systemImage: "rss",
                    description: Text(String(localized: "在 Web 端添加来源后，这里会同步显示"))
                )
            } else {
                list(model)
            }
        }
    }

    private func list(_ model: SubscriptionsViewModel) -> some View {
        List {
            if !model.categories.isEmpty {
                ForEach(model.categories) { category in
                    Section(category.label) {
                        ForEach(model.feeds(in: category)) { feed in
                            feedRow(feed)
                        }
                    }
                }
            }
            if !model.uncategorized.isEmpty {
                Section(String(localized: "未分类")) {
                    ForEach(model.uncategorized) { feed in
                        feedRow(feed)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .refreshable {
            await model.load()
        }
    }

    @ViewBuilder
    private func feedRow(_ feed: FeedSummary) -> some View {
        if let url = feed.feedUrl, let feedURL = URL(string: url) {
            NavigationLink(value: FeedRef(kind: .feed(url: url), title: feed.title)) {
                Label(feed.title, systemImage: "rss")
                    .lineLimit(2)
            }
            .accessibilityHint(String(localized: "打开该来源的文章"))
        } else {
            Label(feed.title, systemImage: "rss")
                .lineLimit(2)
        }
    }
}
