"""Pure-ASGI request hardening middleware (0021).

Body-size ceiling, fixed-window rate limits, the opt-in internal token
check, and the persistent single-user session layer (LUMIRSS_AUTH_MODE=
session). Registered on the app in main.py.
"""


import contextlib
import hmac
import time
import urllib.parse

from lumirss.config import LumiSettings

MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024


class RequestBodyTooLarge(Exception):
    """Raised by the streamed body guard; mapped to the stable 413
    envelope via the exception-handler table below."""

    def __init__(self) -> None:
        super().__init__("The request body is too large.")


REQUEST_TOO_LARGE_BODY = (
    b'{"error":{"type":"request_too_large",'
    b'"message":"The request body is too large."}}'
)


async def _reject_too_large(send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(REQUEST_TOO_LARGE_BODY)).encode()),
            ],
        }
    )
    await send(
        {"type": "http.response.body", "body": REQUEST_TOO_LARGE_BODY},
    )


class RequestSizeLimitMiddleware:
    """Pure-ASGI body cap (Content-Length fast path + streamed guard)."""

    def __init__(self, app, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await _reject_too_large(send)
                    return
            except ValueError:
                pass  # malformed Content-Length: the streamed guard decides
        received = 0

        async def guarded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge()
            return message

        await self.app(scope, guarded_receive, send)




# 0021 hardening: lightweight fixed-window rate limits for the expensive
# or destructive control-plane routes (AI/MT generation, restore, backup,
# outbound discovery, RSSHub mutations). Single-user thresholds are
# deliberately generous — this only stops runaway loops and abuse after
# an auth-bypass, not normal reading. In-memory per process (restart
# resets); reading endpoints stay unlimited by design.


_RATE_RULES: tuple[tuple[str, str, str, int, int], ...] = (
    # (method, path prefix, bucket, max requests, window seconds)
    ("POST", "/api/v1/restore", "restore", 10, 60),
    ("POST", "/api/v1/backups/webdav", "backup_webdav", 10, 60),
    ("POST", "/api/v1/backups", "backup", 12, 60),
    ("POST", "/api/v1/opml/import", "opml", 6, 60),
    ("POST", "/api/v1/feed-preview", "outbound", 30, 60),
    ("POST", "/api/v1/source-discovery", "outbound", 30, 60),
    ("POST", "/api/v1/entries/", "ai_generate", 120, 60),
    ("POST", "/api/v1/rsshub/", "rsshub_write", 60, 60),
    ("PUT", "/api/v1/rsshub/", "rsshub_write", 60, 60),
    ("PATCH", "/api/v1/rsshub/", "rsshub_write", 60, 60),
    ("DELETE", "/api/v1/rsshub/", "rsshub_write", 60, 60),
)


_rate_windows: dict[str, tuple[int, int]] = {}


class RateLimitMiddleware:
    """Pure-ASGI fixed-window limiter (method+prefix → shared bucket).

    Reads ``_RATE_RULES`` per request (module global), so tests can
    shrink the limits without rebuilding the app stack."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            method = scope.get("method", "")
            path = scope.get("path", "")
            for rule_method, prefix, bucket, maximum, window in _RATE_RULES:
                if method == rule_method and path.startswith(prefix):
                    now = int(time.time())
                    window_start, count = _rate_windows.get(bucket, (now, 0))
                    if window_start != now // window:
                        window_start, count = now // window, 0
                    count += 1
                    _rate_windows[bucket] = (window_start, count)
                    if count > maximum:
                        retry_after = window - (now % window)
                        await _reject_rate_limited(send, retry_after)
                        return
                    break
        await self.app(scope, receive, send)


async def _reject_rate_limited(send, retry_after: int) -> None:
    body = (
        b'{"error":{"type":"rate_limited",'
        b'"message":"Too many requests; slow down."}}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", str(max(1, retry_after)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class InternalTokenMiddleware:
    """Single-user internal protection (0021, opt-in).

    When LUMIRSS_INTERNAL_TOKEN is configured, every /api/* request must
    carry a matching X-Lumi-Token header. /health/* stays open (container
    healthchecks run in-container). In production the token is injected
    upstream by Caddy (docker-entrypoint.sh), so the browser needs
    nothing; anything dialing the BFF directly inside the docker network
    is rejected. Unset (default) = previous behavior, dev friendly.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["method"] != "OPTIONS":
            path = scope.get("path", "")
            if path.startswith("/api/"):
                token = LumiSettings().LUMIRSS_INTERNAL_TOKEN.get_secret_value()
                if token:
                    supplied = ""
                    for key, value in scope.get("headers") or []:
                        if key == b"x-lumi-token":
                            supplied = value.decode("latin-1")
                            break
                    if not hmac.compare_digest(supplied, token):
                        await _reject_unauthorized(send)
                        return
        await self.app(scope, receive, send)


async def _reject_unauthorized(send) -> None:
    body = b'{"error":{"type":"unauthorized",'
    body += b'"message":"Missing or invalid internal token."}}'
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Persistent single-user session auth (LUMIRSS_AUTH_MODE=session).
#
# The browser holds one opaque high-entropy cookie; the BFF verifies its
# SHA-256 against auth_sessions, renews it near expiry (sliding window) and
# rejects every non-public /api route without a valid session. The web
# Caddy layer in session mode does NO Basic Auth (static assets and the
# login screen must load pre-auth); the internal token layer below it
# stays fully intact — a session never replaces the internal token.

SECURE_SESSION_COOKIE_NAME = "__Host-lumirss_session"
PLAIN_SESSION_COOKIE_NAME = "lumirss_session"

# Paths the session layer deliberately leaves open. /health/* keeps
# container healthchecks token-free, /api/v1/version is provenance for
# skew diagnosis, and the auth endpoints themselves must be reachable
# pre-login. Everything else under /api/ requires a session.
SESSION_PUBLIC_PATHS = frozenset(
    {"/api/v1/auth/login", "/api/v1/auth/session", "/api/v1/version"}
)

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def session_cookie_name() -> str:
    if LumiSettings().LUMIRSS_SESSION_SECURE_COOKIES:
        return SECURE_SESSION_COOKIE_NAME
    return PLAIN_SESSION_COOKIE_NAME


def build_session_cookie(raw_token: str, max_age_seconds: int) -> str:
    """Set-Cookie value for a fresh session (Strict, HttpOnly, Path=/)."""
    parts = [
        f"{session_cookie_name()}={raw_token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        f"Max-Age={max_age_seconds}",
    ]
    if LumiSettings().LUMIRSS_SESSION_SECURE_COOKIES:
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie() -> str:
    """Set-Cookie value that expires the session cookie immediately."""
    return f"{session_cookie_name()}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


def parse_session_cookie(headers) -> str | None:
    """Raw session token from ASGI headers, or None."""
    name = session_cookie_name().encode("latin-1")
    for key, value in headers or []:
        if key != b"cookie":
            continue
        for part in value.split(b";"):
            chunk = part.strip()
            if chunk.startswith(name + b"="):
                return chunk[len(name) + 1 :].decode("latin-1")
    return None


def _origin_allowed(scope, headers) -> bool:
    """CSRF gate for unsafe methods: Origin (when present) must be
    same-host. Browsers always send Origin on cross-site unsafe requests;
    its absence means a non-browser caller, which still has to pass the
    internal-token layer in production. An explicitly configured public
    origin (LUMIRSS_PUBLIC_ORIGIN) overrides Host-header comparison for
    deployments behind header-rewriting proxies."""
    expected = LumiSettings().LUMIRSS_PUBLIC_ORIGIN
    if expected:
        for key, value in headers or []:
            if key == b"origin":
                return value.decode("latin-1") == expected
        # A configured public origin with no Origin header: non-browser.
        return True
    host = ""
    for key, value in scope.get("headers") or []:
        if key == b"host":
            host = value.decode("latin-1")
            break
    for key, value in headers or []:
        if key != b"origin":
            continue
        origin = urllib.parse.urlsplit(value.decode("latin-1"))
        return bool(origin.netloc) and origin.netloc.lower() == host.lower()
    return True


class SessionAuthMiddleware:
    """Cookie-session gate for /api/* (opt-in via LUMIRSS_AUTH_MODE)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        if LumiSettings().LUMIRSS_AUTH_MODE != "session":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/") or path in SESSION_PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers") or []
        method = scope.get("method", "")
        if method in _UNSAFE_METHODS and not _origin_allowed(scope, headers):
            await _reject_forbidden(send)
            return
        raw_token = parse_session_cookie(headers)
        state = scope.get("app").state if scope.get("app") else None
        if state is None or raw_token is None:
            await _reject_session_required(send)
            return
        from lumirss.auth_store import AuthStore

        store = AuthStore(state.db)
        if await store.get_valid_session(raw_token) is None:
            await _reject_session_required(send)
            return
        settings = LumiSettings()
        with contextlib.suppress(Exception):  # renewal must never break reading
            await store.touch_session(raw_token, settings.LUMIRSS_SESSION_MAX_AGE_DAYS)
        await self.app(scope, receive, send)


async def _reject_session_required(send) -> None:
    body = b'{"error":{"type":"session_required",'
    body += b'"message":"Login required."}}'
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _reject_forbidden(send) -> None:
    body = b'{"error":{"type":"csrf_rejected",'
    body += b'"message":"Cross-origin request rejected."}}'
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Login brute-force limiter: counts FAILED verifications only, so a clumsy
# but legitimate user is never locked out by their own retries. Sliding
# window, in-memory (restart resets — acceptable for a single-user login).

LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_S = 60

_login_failures: dict[str, list[float]] = {}


def _client_key(scope) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"


def login_attempts_allowed(scope) -> bool:
    """True when the failure budget for this client is not exhausted."""
    now = time.monotonic()
    recent = [
        stamp
        for stamp in _login_failures.get(_client_key(scope), [])
        if now - stamp < LOGIN_FAILURE_WINDOW_S
    ]
    _login_failures[_client_key(scope)] = recent
    return len(recent) < LOGIN_FAILURE_LIMIT


def register_login_failure(scope) -> None:
    _login_failures.setdefault(_client_key(scope), []).append(time.monotonic())


def reset_login_failures(scope) -> None:
    _login_failures.pop(_client_key(scope), None)


def login_retry_after_s(scope) -> int:
    stamps = _login_failures.get(_client_key(scope), [])
    if not stamps:
        return 1
    elapsed = time.monotonic() - max(stamps)
    return max(1, int(LOGIN_FAILURE_WINDOW_S - elapsed))


