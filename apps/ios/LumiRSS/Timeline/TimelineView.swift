import SwiftUI

/// One timeline row: title, feed, time, snippet; swipe actions for
/// read/star; flags rendered from the shared state store.
struct EntryRowView: View {
    let item: ArticleListItem
    let readFlag: Bool
    let starredFlag: Bool
    let syncing: Bool
    let onToggleRead: () -> Void
    let onToggleStarred: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(item.title)
                        .font(readFlag ? .subheadline : .subheadline.weight(.semibold))
                        .foregroundStyle(readFlag ? Color.secondary : Color.primary)
                        .lineLimit(3)
                    if syncing {
                        ProgressView()
                            .controlSize(.mini)
                            .accessibilityLabel(String(localized: "正在同步"))
                    } else if starredFlag {
                        Image(systemName: "star.fill")
                            .font(.caption2)
                            .foregroundStyle(.yellow)
                            .accessibilityLabel(String(localized: "已收藏"))
                    }
                }
                if let snippet = item.snippet, !snippet.isEmpty {
                    Text(snippet)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                HStack(spacing: 6) {
                    Text(item.feedTitle)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.tint)
                        .lineLimit(1)
                    if let author = item.author, !author.isEmpty {
                        Text(author)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Text(LumiDate.listLabel(item.publishedAt))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            if !readFlag {
                Circle()
                    .fill(Color("LumiAccent"))
                    .frame(width: 8, height: 8)
                    .accessibilityLabel(String(localized: "未读"))
            }
        }
        .contentShape(Rectangle())
        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
            Button(role: .destructive) {
                onToggleRead()
            } label: {
                Label(readFlag ? String(localized: "未读") : String(localized: "已读"),
                      systemImage: readFlag ? "envelope.badge" : "envelope.open")
            }
            Button {
                onToggleStarred()
            } label: {
                Label(starredFlag ? String(localized: "取消收藏") : String(localized: "收藏"),
                      systemImage: starredFlag ? "star.slash" : "star")
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilitySummary)
    }

    private var accessibilitySummary: String {
        var parts: [String] = [item.title]
        if !readFlag { parts.append(String(localized: "未读")) }
        if starredFlag { parts.append(String(localized: "已收藏")) }
        parts.append(item.feedTitle)
        if let published = item.publishedAt {
            parts.append(LumiDate.fullFormatter.string(from: published))
        }
        return parts.joined(separator: "，")
    }
}

/// The timeline list for a scope, with pull-to-refresh, paged loading
/// and honest empty/error states.
struct TimelineView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var model: TimelineViewModel?

    let scope: TimelineScope

    var body: some View {
        Group {
            if let model {
                list(model)
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(scope.title)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if model == nil {
                model = environment.makeTimelineViewModel(scope: scope)
            }
            await model?.loadInitialIfNeeded()
        }
    }

    @ViewBuilder
    private func list(_ model: TimelineViewModel) -> some View {
        switch model.phase {
        case .idle, .loadingInitial:
            VStack(spacing: 10) {
                ProgressView()
                if model.items.isEmpty {
                    Text(String(localized: "加载中…"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .failed(let message):
            if model.items.isEmpty {
                ContentUnavailableView {
                    Label(String(localized: "无法加载时间线"), systemImage: "exclamationmark.triangle")
                } description: {
                    Text(message)
                } actions: {
                    Button(String(localized: "重试")) {
                        Task { await model.loadInitial() }
                    }
                    .buttonStyle(.borderedProminent)
                }
            } else {
                listBody(model)
            }
        case .showingOfflineCache, .loaded, .loadingMore:
            if model.items.isEmpty {
                ContentUnavailableView(
                    String(localized: "这里还是空的"),
                    systemImage: scope.emptyIcon,
                    description: Text(model.phase == .showingOfflineCache
                        ? String(localized: "离线中 — 此范围没有缓存内容")
                        : String(localized: "换个筛选条件，或稍后再来看看"))
                )
            } else {
                listBody(model)
            }
        }
    }

    private func listBody(_ model: TimelineViewModel) -> some View {
        List {
            if model.phase == .showingOfflineCache {
                Label(String(localized: "离线 — 显示缓存内容"), systemImage: "wifi.slash")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .listRowSeparator(.hidden)
            }
            ForEach(model.items) { item in
                NavigationLink(value: item) {
                    EntryRowView(
                        item: item,
                        readFlag: model.readFlag(item.entryRef),
                        starredFlag: model.starredFlag(item.entryRef),
                        syncing: model.isSyncing(item.entryRef),
                        onToggleRead: { Task { await model.toggleRead(item) } },
                        onToggleStarred: { Task { await model.toggleStarred(item) } }
                    )
                }
                .task {
                    await model.loadMoreIfNeeded(currentItem: item)
                }
            }
            if case .loadingMore = model.phase {
                HStack {
                    Spacer()
                    ProgressView()
                    Spacer()
                }
                .listRowSeparator(.hidden)
            }
        }
        .listStyle(.plain)
        .refreshable {
            await model.refresh()
        }
    }
}

extension TimelineScope {
    var emptyIcon: String {
        switch self {
        case .all: return "tray"
        case .unread: return "envelope.badge"
        case .starred: return "star"
        case .feed: return "rss"
        }
    }
}
