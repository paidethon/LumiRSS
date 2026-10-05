import Foundation

/// Hand-written domain view models over the generated DTOs. The wire
/// contract stays owned by the generated client; these are the shapes
/// SwiftUI binds to (dates parsed, optionals narrowed, no wire names).
struct ArticleListItem: Identifiable, Equatable, Hashable, Codable {
    let entryRef: String
    var title: String
    var feedTitle: String
    var author: String?
    var url: String?
    var publishedAt: Date?
    var read: Bool
    var starred: Bool
    var feedUrl: String?
    var snippet: String?

    var id: String { entryRef }

    init(
        entryRef: String,
        title: String,
        feedTitle: String,
        author: String? = nil,
        url: String? = nil,
        publishedAt: Date? = nil,
        read: Bool,
        starred: Bool,
        feedUrl: String? = nil,
        snippet: String? = nil
    ) {
        self.entryRef = entryRef
        self.title = title
        self.feedTitle = feedTitle
        self.author = author
        self.url = url
        self.publishedAt = publishedAt
        self.read = read
        self.starred = starred
        self.feedUrl = feedUrl
        self.snippet = snippet
    }
}

struct ArticleDetail: Codable {
    let entryRef: String
    var title: String
    var feedTitle: String
    var author: String?
    var url: String?
    var publishedAt: Date?
    var crawledAt: Date?
    var read: Bool
    var starred: Bool
    var contentHtml: String?
    var contentText: String?
    var feedUrl: String?
}

struct FeedSummary: Identifiable, Hashable {
    let subscriptionRef: String
    var title: String
    var feedUrl: String
    var categoryId: String?
    var categoryLabel: String?

    var id: String { subscriptionRef }
}

struct CategorySummary: Identifiable, Hashable {
    let categoryId: String
    var label: String

    var id: String { categoryId }
}

struct SearchHit {
    let entryRef: String
    var title: String
    var feedTitle: String
    var snippet: String?
    var publishedAt: Date?
    var feedUrl: String?

    var listTile: ArticleListItem {
        ArticleListItem(
            entryRef: entryRef,
            title: title,
            feedTitle: feedTitle,
            url: nil,
            publishedAt: publishedAt,
            read: true,
            starred: false,
            feedUrl: feedUrl,
            snippet: snippet
        )
    }
}

struct ServerVersion {
    let version: String
    let commit: String
    let apiVersion: Int

    /// The app's first native release consumes the 3.x API surface
    /// (entries + state + search + subscriptions as of 3.0.0).
    var isCompatible: Bool {
        majorVersion >= 3
    }

    var majorVersion: Int {
        Int(version.split(separator: ".").first ?? "0") ?? 0
    }
}

struct AccountSession: Equatable, Codable {
    var userId: String?
    var username: String?
    var role: String?
    var expiresAt: Date?
}

enum LoginOutcome {
    case authenticated(AccountSession)
    case totpRequired(pendingToken: String)
}
