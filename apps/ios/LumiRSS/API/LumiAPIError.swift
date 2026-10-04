import Foundation
import OpenAPIRuntime

/// The BFF's uniform error envelope: `{"error":{"type","message"}}`.
struct ServerErrorEnvelope: Decodable {
    struct Inner: Decodable {
        let type: String
        let message: String?
    }

    let error: Inner
}

/// Everything the app-level call sites need from a failed API call.
enum LumiAPIError: Error {
    /// The server explicitly answered "not authenticated" (401) — the
    /// session is gone; clear login state. NOT used for network errors.
    case sessionExpired
    /// Server said no (403 csrf/forbidden, 404, 400 invalid input...).
    case server(status: Int, type: String?, message: String?)
    /// Rate limited — UI offers a retry after a pause.
    case rateLimited
    /// Transport-level failure: offline, timeout, DNS, TLS.
    case network(String)
    /// Response could not be decoded / unexpected shape.
    case decoding(String)
    /// The server is reachable but its version predates the API the
    /// app needs (probe gate).
    case incompatibleServer(version: String)

    var isSessionExpired: Bool {
        if case .sessionExpired = self { return true }
        return false
    }

    var userMessage: String {
        switch self {
        case .sessionExpired:
            return String(localized: "登录已过期，请重新登录")
        case .server(_, let type, let message):
            if let message, !message.isEmpty { return message }
            if let type { return String(localized: "服务器拒绝了请求（\(type)）") }
            return String(localized: "服务器拒绝了请求")
        case .rateLimited:
            return String(localized: "请求过于频繁，请稍后再试")
        case .network:
            return String(localized: "网络不可用或服务器无法连接")
        case .decoding:
            return String(localized: "服务器响应无法解析")
        case .incompatibleServer(let version):
            return String(localized: "服务器版本过低（\(version)），需要 3.0.0 或更高")
        }
    }
}

enum APIErrorMapper {
    /// Map any thrown error from the generated client into LumiAPIError.
    ///
    /// Only an explicit 401 (or the envelope's `session_required`) is a
    /// session expiry — timeouts, connection loss and 5xx keep the
    /// login state untouched.
    static func map(_ error: Error) -> LumiAPIError {
        if let lumiError = error as? LumiAPIError { return lumiError }

        if let clientError = error as? ClientError {
            let status = clientError.response?.status.code
            switch status {
            case 401:
                return .sessionExpired
            case 429:
                return .rateLimited
            case let code? where (400...599).contains(code):
                return .server(status: code, type: nil, message: nil)
            default:
                break
            }
            // Thrown before/after the HTTP roundtrip (encoding, decoding,
            // transport) with no usable status code.
            if let urlError = clientError.underlyingError as? URLError {
                return .network(urlError.localizedDescription)
            }
            if let nsError = clientError.underlyingError as? NSError,
               nsError.domain == NSURLErrorDomain {
                return .network(nsError.localizedDescription)
            }
            return .decoding(clientError.causeDescription)
        }

        if let urlError = error as? URLError {
            return .network(urlError.localizedDescription)
        }
        if let decodingError = error as? DecodingError {
            return .decoding(decodingError.localizedDescription)
        }
        return .network(error.localizedDescription)
    }

    /// Enrich a mapped `.server` error with the envelope body the BFF
    /// actually sent (`{"error":{"type","message"}}`), when one exists.
    static func map(_ error: Error, envelope: ServerErrorEnvelope?) -> LumiAPIError {
        let mapped = map(error)
        guard case .server(let status, _, _) = mapped, let envelope else { return mapped }
        if envelope.error.type == "session_required" {
            return .sessionExpired
        }
        return .server(status: status, type: envelope.error.type, message: envelope.error.message)
    }

    /// Read the error envelope out of a ClientError's response body.
    static func envelope(from error: Error) async -> ServerErrorEnvelope? {
        guard let clientError = error as? ClientError, let body = clientError.responseBody else {
            return nil
        }
        guard let chunk = try? await HTTPBody.ByteChunk(collecting: body, upTo: 64 * 1024) else {
            return nil
        }
        return try? JSONDecoder().decode(ServerErrorEnvelope.self, from: Data(chunk))
    }
}
