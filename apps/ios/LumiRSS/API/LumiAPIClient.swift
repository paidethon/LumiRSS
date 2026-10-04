import Foundation
import OpenAPIRuntime
import OpenAPIURLSession

/// The scope a timeline page is filtered to. Values map 1:1 onto the
/// GET /api/v1/entries query; the cursor is opaque and is only ever
/// passed back verbatim.
enum TimelineScope: Equatable, Hashable {
    case all
    case unread
    case starred
    case feed(ref: FeedRef)

    var title: String {
        switch self {
        case .all: return String(localized: "全部")
        case .unread: return String(localized: "未读")
        case .starred: return String(localized: "收藏")
        case .feed(let ref): return ref.title
        }
    }
}

/// A feed or category the timeline can be scoped to. `feedUrl` and
/// `categoryId` are mutually exclusive on the server — this type makes
/// that unrepresentable.
struct FeedRef: Equatable, Hashable {
    enum Kind: Equatable, Hashable {
        case feed(url: String)
        case category(id: String)
    }

    let kind: Kind
    let title: String

    var feedUrl: String? {
        if case .feed(let url) = kind { return url }
        return nil
    }

    var categoryId: String? {
        if case .category(let id) = kind { return id }
        return nil
    }
}

struct TimelinePage {
    var items: [ArticleListItem]
    var nextCursor: String?
    var filteredCount: Int?
}

struct SearchPage {
    var items: [SearchHit]
    var nextCursor: String?
}

/// Thin wrapper over the generated OpenAPI client.
///
/// - The base URL is a bare origin; generated paths (`/api/v1/...`) are
///   appended by the generated client, so a double `/api/v1` cannot
///   happen from this layer.
/// - Errors are always mapped (`APIErrorMapper`) before rethrowing.
/// - The URLSession uses the shared cookie storage: login cookies set
///   by the server flow into `HTTPCookieStorage.shared`, and the
///   `AuthStore` mirrors them into the keychain for restart survival.
final class LumiAPIClient: @unchecked Sendable {
    let serverURL: URL
    let client: Client

    init(serverURL: URL) {
        self.serverURL = serverURL
        self.client = Client(serverURL: serverURL, transport: URLSessionTransport())
    }

    private func mapError(_ error: Error) async -> LumiAPIError {
        let envelope = await APIErrorMapper.envelope(from: error)
        return APIErrorMapper.map(error, envelope: envelope)
    }

    // MARK: - Server / auth

    /// Unauthenticated compatibility probe against /api/v1/version.
    func probeServerVersion() async throws -> ServerVersion {
        do {
            let output = try await client.versionApiV1VersionGet()
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            let payload = try ok.body.json
            return ServerVersion(
                version: payload.version,
                commit: payload.commit,
                apiVersion: payload.apiVersion
            )
        } catch {
            throw await mapError(error)
        }
    }

    func login(username: String, password: String) async throws -> LoginOutcome {
        do {
            let output = try await client.loginApiV1AuthLoginPost(
                body: .json(.init(password: password, username: username))
            )
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            // The union decodes as anyOf optionals (value1 = AuthStatus,
            // value2 = LoginChallenge); decoding order guarantees at
            // most one is non-nil.
            let payload = try ok.body.json
            if let status = payload.value1 {
                return .authenticated(session(from: status))
            }
            if let challenge = payload.value2 {
                return .totpRequired(pendingToken: challenge.pendingToken)
            }
            throw LumiAPIError.decoding("login response matched no union member")
        } catch {
            throw await mapError(error)
        }
    }

    func verifyTOTP(pendingToken: String, code: String) async throws -> AccountSession {
        do {
            let output = try await client.totpVerifyApiV1AuthTotpVerifyPost(
                body: .json(.init(code: code, pendingToken: pendingToken))
            )
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            return session(from: try ok.body.json)
        } catch {
            throw await mapError(error)
        }
    }

    func sessionStatus() async throws -> AccountSession? {
        do {
            let output = try await client.sessionStatusApiV1AuthSessionGet()
            guard case .ok(let ok) = output else { return nil }
            let status = try ok.body.json
            guard status.authenticated else { return nil }
            return session(from: status)
        } catch {
            throw await mapError(error)
        }
    }

    /// Revoke the server-side session. Best effort: a network failure
    /// must not block local logout cleanup.
    func logout() async {
        _ = try? await client.logoutApiV1AuthLogoutPost()
    }

    private func session(from status: Components.Schemas.AuthStatus) -> AccountSession {
        AccountSession(
            userId: status.userId,
            username: status.username,
            role: status.role?.rawValue,
            expiresAt: LumiDate.parse(status.expiresAt)
        )
    }

    // MARK: - Entries

    func timeline(scope: TimelineScope, cursor: String?) async throws -> TimelinePage {
        var feedUrl: String? = nil
        var categoryId: String? = nil
        var output: Operations.EntriesApiV1EntriesGet.Output
        do {
            switch scope {
            case .all:
                output = try await client.entriesApiV1EntriesGet(query: .init(view: .all, cursor: cursor))
            case .unread:
                output = try await client.entriesApiV1EntriesGet(query: .init(view: .unread, cursor: cursor))
            case .starred:
                output = try await client.entriesApiV1EntriesGet(query: .init(view: .starred, cursor: cursor))
            case .feed(let ref):
                // Feed/category scoping has no separate view union on the
                // server — a scoped listing is "all entries of that scope".
                feedUrl = ref.feedUrl
                categoryId = ref.categoryId
                output = try await client.entriesApiV1EntriesGet(
                    query: .init(view: .all, feedUrl: feedUrl, categoryId: categoryId, cursor: cursor)
                )
            }
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            let payload = try ok.body.json
            return TimelinePage(
                items: payload.items.map(Self.listItem),
                nextCursor: payload.nextCursor,
                filteredCount: payload.filteredCount
            )
        } catch {
            throw await mapError(error)
        }
    }

    func entry(entryRef: String) async throws -> ArticleDetail {
        do {
            let output = try await client.entryDetailApiV1EntriesEntryRefGet(
                path: .init(entryRef: entryRef)
            )
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            let detail = try ok.body.json
            return ArticleDetail(
                entryRef: detail.entryRef,
                title: detail.title,
                feedTitle: detail.feedTitle,
                author: detail.author,
                url: detail.url,
                publishedAt: LumiDate.parse(detail.publishedAt),
                crawledAt: LumiDate.parse(detail.crawledAt),
                read: detail.read,
                starred: detail.starred,
                contentHtml: detail.contentHtml,
                contentText: detail.contentText,
                feedUrl: detail.feedUrl
            )
        } catch {
            throw await mapError(error)
        }
    }

    /// Set semantics write (never a toggle): `nil` leaves the flag
    /// untouched on the server.
    func setEntryState(entryRef: String, read: Bool?, starred: Bool?) async throws -> Bool {
        precondition(read != nil || starred != nil, "setEntryState needs at least one flag")
        do {
            let output = try await client.entryStateApiV1EntriesEntryRefStatePatch(
                path: .init(entryRef: entryRef),
                body: .json(.init(read: read, starred: starred))
            )
            guard case .noContent = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            return true
        } catch {
            throw await mapError(error)
        }
    }

    // MARK: - Subscriptions

    func subscriptions() async throws -> [FeedSummary] {
        do {
            let output = try await client.subscriptionsApiV1SubscriptionsGet()
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            return try ok.body.json.map { sub in
                FeedSummary(
                    subscriptionRef: sub.subscriptionRef,
                    title: sub.title,
                    feedUrl: sub.feedUrl,
                    categoryId: sub.category?.id,
                    categoryLabel: sub.category?.label
                )
            }
        } catch {
            throw await mapError(error)
        }
    }

    func categories() async throws -> [CategorySummary] {
        do {
            let output = try await client.categoriesApiV1CategoriesGet()
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            return try ok.body.json.map { category in
                CategorySummary(categoryId: category.id, label: category.label)
            }
        } catch {
            throw await mapError(error)
        }
    }

    // MARK: - Search

    func search(query: String, cursor: String?) async throws -> SearchPage {
        do {
            let output = try await client.searchApiV1SearchGet(
                query: .init(q: query, cursor: cursor)
            )
            guard case .ok(let ok) = output else {
                throw LumiAPIError.server(status: 0, type: nil, message: nil)
            }
            let payload = try ok.body.json
            return SearchPage(
                items: payload.items.map { hit in
                    SearchHit(
                        entryRef: hit.entryRef,
                        title: hit.title,
                        feedTitle: hit.feedTitle,
                        snippet: hit.snippet,
                        publishedAt: LumiDate.parse(hit.publishedAt),
                        feedUrl: hit.feedUrl
                    )
                },
                nextCursor: payload.nextCursor
            )
        } catch {
            throw await mapError(error)
        }
    }

    // MARK: - Mapping helpers

    static func listItem(from dto: Components.Schemas.EntryListItem) -> ArticleListItem {
        ArticleListItem(
            entryRef: dto.entryRef,
            title: dto.title,
            feedTitle: dto.feedTitle,
            author: dto.author,
            url: dto.url,
            publishedAt: LumiDate.parse(dto.publishedAt),
            read: dto.read,
            starred: dto.starred,
            feedUrl: dto.feedUrl,
            snippet: dto.snippet
        )
    }
}
