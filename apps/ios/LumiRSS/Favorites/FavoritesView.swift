import SwiftUI

/// 收藏 tab — the starred timeline; state changes in the reader are
/// reflected here through the shared EntryStateStore.
struct FavoritesView: View {
    var body: some View {
        TimelineView(scope: .starred)
    }
}
