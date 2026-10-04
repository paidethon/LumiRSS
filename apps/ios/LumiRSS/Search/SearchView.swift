import SwiftUI

/// 搜索 tab — live search over the derived projection.
struct SearchView: View {
    @Environment(AppEnvironment.self) private var environment
    @State private var model: SearchViewModel?
    @State private var query = ""

    var body: some View {
        Group {
            if let model {
                content(model)
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(String(localized: "搜索"))
        .searchable(text: $query, prompt: String(localized: "搜索文章"))
        .onChange(of: query) { _, newValue in
            model?.search(newValue)
        }
        .task {
            if model == nil {
                model = environment.makeSearchViewModel()
            }
        }
    }

    @ViewBuilder
    private func content(_ model: SearchViewModel) -> some View {
        switch model.phase {
        case .idle:
            ContentUnavailableView.search
        case .searching:
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .empty:
            ContentUnavailableView(
                String(localized: "没有找到"),
                systemImage: "magnifyingglass",
                description: Text(String(localized: "换个关键词试试（支持最多 4 个词）"))
            )
        case .failed(let message):
            ContentUnavailableView {
                Label(String(localized: "搜索失败"), systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
            }
        case .results:
            List(model.results) { item in
                NavigationLink(value: item) {
                    EntryRowView(
                        item: item,
                        readFlag: true,
                        starredFlag: false,
                        syncing: false,
                        onToggleRead: {},
                        onToggleStarred: {}
                    )
                }
                .task {
                    await model.loadMore()
                }
            }
            .listStyle(.plain)
        }
    }
}
