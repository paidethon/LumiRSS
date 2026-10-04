import SwiftUI

/// Root gate: first-run server setup → login → main tabs. A persisted
/// session starts in `.restoring` and is verified against the server.
struct RootView: View {
    @Environment(AppEnvironment.self) private var environment

    var body: some View {
        switch environment.session.phase {
        case .unconfigured:
            ServerSetupView()
        case .loggedOut:
            LoginView()
        case .restoring:
            VStack(spacing: 14) {
                ProgressView()
                Text(String(localized: "正在恢复会话…"))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .task {
                await environment.session.restore()
            }
        case .loggedIn:
            MainTabView()
        }
    }
}

/// 首页/订阅/搜索/收藏 四个原生入口。
struct MainTabView: View {
    @Environment(AppEnvironment.self) private var environment

    var body: some View {
        TabView {
            Tab(String(localized: "首页"), systemImage: "house") {
                HomeView()
            }
            Tab(String(localized: "订阅"), systemImage: "rss") {
                NavigationStack {
                    SubscriptionsView()
                        .articleDestinations()
                }
            }
            Tab(String(localized: "搜索"), systemImage: "magnifyingglass") {
                NavigationStack {
                    SearchView()
                        .articleDestinations()
                }
            }
            Tab(String(localized: "收藏"), systemImage: "star") {
                NavigationStack {
                    FavoritesView()
                        .articleDestinations()
                }
            }
        }
    }
}

/// Shared navigation destinations: any list can push an article or a
/// feed-scoped timeline.
extension View {
    func articleDestinations() -> some View {
        navigationDestination(for: ArticleListItem.self) { item in
            ReaderView(listTile: item)
        }
        .navigationDestination(for: FeedRef.self) { ref in
            TimelineView(scope: .feed(ref: ref))
        }
    }
}

/// 首页: the main timeline with an all/unread segmented filter.
struct HomeView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var filter: HomeFilter = .all

    enum HomeFilter: String, CaseIterable, Identifiable {
        case all
        case unread

        var id: String { rawValue }

        var title: String {
            switch self {
            case .all: return String(localized: "全部")
            case .unread: return String(localized: "未读")
            }
        }

        var scope: TimelineScope {
            switch self {
            case .all: return .all
            case .unread: return .unread
            }
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker(String(localized: "筛选"), selection: $filter) {
                    ForEach(HomeFilter.allCases) { option in
                        Text(option.title).tag(option)
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.bottom, 6)

                // Scope change swaps the timeline; the view model's
                // generation counter cancels stale page responses.
                TimelineView(scope: filter.scope)
                    .id(filter)
            }
            .navigationTitle("LumiRSS")
            .articleDestinations()
        }
    }
}
