import Foundation
import Observation

/// Owns the login lifecycle: server configuration, login, restart
/// restore, logout, and session-expiry handling.
///
/// Security posture (v1):
/// - The session cookie is the only long-lived secret; it lives in the
///   keychain (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), never
///   in UserDefaults. The username/password typed at login are used once
///   and dropped — nothing is retained to simulate permanent login.
/// - No refresh-token flow exists in the BFF contract; the session has a
///   server-side expiry and can be revoked from any device (logout /
///   logout-all / admin). The app reacts to an explicit 401 by clearing
///   state; network timeouts and 5xx never touch the login state.
/// - Identity always comes from `GET /auth/session` — the app never
///   decides locally who is logged in.
@MainActor
@Observable
final class SessionController {
    enum Phase: Equatable {
        /// No server configured yet — first launch.
        case unconfigured
        /// A server origin is stored, no live session.
        case loggedOut(URL)
        /// Restoring/verifying a persisted session at launch.
        case restoring(URL)
        /// Signed in.
        case loggedIn(server: URL, account: AccountSession)
    }

    private(set) var phase: Phase
    private(set) var lastError: String?

    /// Set when a server was probed and rejected as incompatible.
    private(set) var serverVersion: ServerVersion?

    private let store: SessionStore
    private var activeAPI: LumiAPIClient?

    var api: LumiAPIClient? {
        if let activeAPI { return activeAPI }
        guard let origin = storedOrigin() else { return nil }
        let client = LumiAPIClient(serverURL: origin)
        activeAPI = client
        return client
    }

    var account: AccountSession? {
        if case .loggedIn(_, let account) = phase { return account }
        return nil
    }

    var serverOrigin: URL? {
        switch phase {
        case .unconfigured: return storedOrigin()
        case .loggedOut(let url), .restoring(let url): return url
        case .loggedIn(let server, _): return server
        }
    }

    init(store: SessionStore = SystemKeychain()) {
        self.store = store
        if let origin = Self.readStoredOrigin(from: store) {
            // Session validity is verified asynchronously by `restore()`
            // — the cookie alone is never proof of a live login.
            Self.rehydrateCookie(into: .shared, from: store, server: origin)
            self.phase = .restoring(origin)
        } else {
            self.phase = .unconfigured
        }
    }

    // MARK: - Server configuration

    /// Normalize + probe a user-entered address. Success stores the
    /// origin and moves to `.loggedOut`. Throws user-presentable errors.
    func configureServer(_ rawInput: String) async {
        lastError = nil
        let origin: URL
        do {
            origin = try ServerURL.normalize(rawInput)
        } catch {
            lastError = (error as? LocalizedError)?.errorDescription ?? String(localized: "无法解析这个地址")
            return
        }
        let probe = LumiAPIClient(serverURL: origin)
        do {
            let version = try await probe.probeServerVersion()
            guard version.isCompatible else {
                serverVersion = version
                lastError = LumiAPIError.incompatibleServer(version: version.version).userMessage
                return
            }
            serverVersion = version
        } catch let error as LumiAPIError {
            lastError = error.userMessage
            return
        } catch {
            lastError = LumiAPIError.network(error.localizedDescription).userMessage
            return
        }
        store.writeJSON(origin, forKey: Self.originKey)
        activeAPI = probe
        clearCookieStorage()
        phase = .loggedOut(origin)
    }

    // MARK: - Login

    func login(username: String, password: String, totpCode: String? = nil) async -> Bool {
        guard let api else {
            lastError = String(localized: "未配置服务器")
            return false
        }
        lastError = nil
        do {
            if let totpCode, let pending = pendingTOTP {
                let account = try await api.verifyTOTP(pendingToken: pending, code: totpCode)
                pendingTOTP = nil
                return finishLogin(account: account, server: api.serverURL)
            }
            switch try await api.login(username: username, password: password) {
            case .authenticated(let account):
                return finishLogin(account: account, server: api.serverURL)
            case .totpRequired(let pendingToken):
                pendingTOTP = pendingToken
                return false
            }
        } catch let error as LumiAPIError {
            if error.isSessionExpired {
                lastError = String(localized: "登录被服务器拒绝")
            } else {
                lastError = error.userMessage
            }
            return false
        } catch {
            lastError = LumiAPIError.network(error.localizedDescription).userMessage
            return false
        }
    }

    private var pendingTOTP: String?

    var awaitingTOTP: Bool { pendingTOTP != nil }

    /// Called by feature code when a request came back explicitly
    /// unauthenticated: the session was revoked server-side.
    func handleSessionExpired() {
        guard case .loggedIn = phase else { return }
        clearStoredSession()
        if let origin = serverOrigin {
            phase = .loggedOut(origin)
        }
        lastError = LumiAPIError.sessionExpired.userMessage
    }

    /// Verify the persisted session at launch. Offline: keep `.restoring`
    /// as an offline-logged-in state (cached content stays available);
    /// the next successful API call either works or reports 401.
    func restore() async {
        guard case .restoring(let origin) = phase, let api else { return }
        do {
            if let account = try await api.sessionStatus() {
                phase = .loggedIn(server: origin, account: account)
            } else {
                // Server answered: definitely signed out.
                clearStoredSession()
                phase = .loggedOut(origin)
            }
        } catch let error as LumiAPIError where error.isSessionExpired {
            clearStoredSession()
            phase = .loggedOut(origin)
        } catch {
            // Offline / server unreachable — keep restoring state so the
            // app opens with cached data; `lastError` stays unset (this
            // is not a user action failing).
        }
    }

    /// "更换服务器": forget the stored origin entirely (back to setup).
    /// Session data was already cleared by `logout()`.
    func forgetServer() {
        store.removeValue(forKey: Self.originKey)
        clearCookieStorage()
        serverVersion = nil
        lastError = nil
        phase = .unconfigured
    }

    func logout() async {
        await api?.logout()
        clearStoredSession()
        clearCookieStorage()
        if let origin = serverOrigin {
            phase = .loggedOut(origin)
        }
    }

    private func finishLogin(account: AccountSession, server: URL) -> Bool {
        persistCookie(from: .shared, to: store, server: server)
        if let accountData = try? JSONEncoder().encode(account) {
            store.writeData(accountData, forKey: Self.accountKey)
        }
        phase = .loggedIn(server: server, account: account)
        return true
    }

    // MARK: - Persistence

    private static let originKey = "server.origin"
    private static let cookieKey = "session.cookie"
    private static let accountKey = "session.account"

    private struct StoredCookie: Codable {
        var name: String
        var value: String
        var domain: String
        var path: String
        var expires: Date?
        var secure: Bool
    }

    private func storedOrigin() -> URL? { Self.readStoredOrigin(from: store) }

    private static func readStoredOrigin(from store: SessionStore) -> URL? {
        guard let data = store.readData(forKey: originKey) else { return nil }
        return try? JSONDecoder().decode(URL.self, from: data)
    }

    /// Mirror the live session cookie (set by the login response) into
    /// the keychain so a plain relaunch stays signed in.
    private func persistCookie(from storage: HTTPCookieStorage, to store: SessionStore, server: URL) {
        guard let cookies = storage.cookies(for: server) else { return }
        // The BFF session cookie is the only cookie we care about; take
        // the longest-lived cookie for the server origin.
        guard let cookie = cookies.max(by: { lhs, rhs in
            (lhs.expiresDate ?? .distantPast) < (rhs.expiresDate ?? .distantPast)
        }) else { return }
        let stored = StoredCookie(
            name: cookie.name,
            value: cookie.value,
            domain: cookie.domain,
            path: cookie.path,
            expires: cookie.expiresDate,
            secure: cookie.isSecure
        )
        if let data = try? JSONEncoder().encode(stored) {
            store.writeData(data, forKey: cookieKey)
        }
    }

    /// Put the keychain cookie back into the shared cookie storage so
    /// URLSession attaches it to every request.
    private static func rehydrateCookie(into storage: HTTPCookieStorage, from store: SessionStore, server: URL) {
        guard let data = store.readData(forKey: cookieKey),
              let stored = try? JSONDecoder().decode(StoredCookie.self, from: data) else { return }
        if let expires = stored.expires, expires < Date() { return }
        let properties: [HTTPCookiePropertyKey: Any] = [
            .name: stored.name,
            .value: stored.value,
            .domain: stored.domain,
            .path: stored.path,
            .secure: stored.secure ? "TRUE" : "FALSE",
        ]
        if let cookie = HTTPCookie(properties: properties) {
            storage.setCookie(cookie)
        }
    }

    private func clearStoredSession() {
        store.removeValue(forKey: Self.cookieKey)
        store.removeValue(forKey: Self.accountKey)
        pendingTOTP = nil
        activeAPI = nil
    }

    private func clearCookieStorage() {
        if let cookies = HTTPCookieStorage.shared.cookies, !cookies.isEmpty {
            for cookie in cookies {
                HTTPCookieStorage.shared.deleteCookie(cookie)
            }
        }
    }
}

private extension SessionStore {
    func writeJSON<T: Encodable>(_ value: T, forKey key: String) {
        if let data = try? JSONEncoder().encode(value) {
            writeData(data, forKey: key)
        }
    }
}
