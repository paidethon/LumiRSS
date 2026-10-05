import Foundation
import Observation

/// Normalization of the user-entered server address.
///
/// The stored value is ALWAYS a bare origin (scheme + host + optional
/// port) — no path, no query, no fragment, and never a doubled
/// `/api/v1` (the API layer appends the base path exactly once).
enum ServerURL {
    enum NormalizationError: LocalizedError, Equatable {
        case empty
        case missingHost
        case unsupportedScheme
        case userinfoNotAllowed
        case invalidURL

        var errorDescription: String? {
            switch self {
            case .empty: return String(localized: "请输入服务器地址")
            case .missingHost: return String(localized: "地址缺少主机名，例如 https://rss.example.com")
            case .unsupportedScheme: return String(localized: "只支持 http 和 https 地址")
            case .userinfoNotAllowed: return String(localized: "地址中不能包含用户名密码")
            case .invalidURL: return String(localized: "无法解析这个地址")
            }
        }
    }

    /// Canonicalize free-text input into an origin URL.
    ///
    /// - Bare hosts get `https://` prefixed (self-hosted LumiRSS is TLS
    ///   first; a LAN user can still type `http://` explicitly).
    /// - Any path/query/fragment is dropped — trailing `/api/v1` from
    ///   copy-pasted docs is the classic double-prefix bug.
    static func normalize(_ rawInput: String) throws -> URL {
        let raw = rawInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { throw NormalizationError.empty }
        let withScheme = raw.contains("://") ? raw : "https://\(raw)"
        guard let parsed = URL(string: withScheme),
              let scheme = parsed.scheme?.lowercased(),
              let host = parsed.host, !host.isEmpty else {
            throw NormalizationError.invalidURL
        }
        guard scheme == "http" || scheme == "https" else {
            throw NormalizationError.unsupportedScheme
        }
        guard parsed.user == nil, parsed.password == nil else {
            throw NormalizationError.userinfoNotAllowed
        }
        var components = URLComponents()
        components.scheme = scheme
        components.host = host
        components.port = parsed.port
        guard let origin = components.url else { throw NormalizationError.invalidURL }
        return origin
    }

    /// `origin` if it is already a bare origin, otherwise re-normalized.
    static func ensureOrigin(_ url: URL) -> URL? {
        try? normalize(url.absoluteString)
    }
}
