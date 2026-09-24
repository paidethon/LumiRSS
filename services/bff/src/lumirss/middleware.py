"""Pure-ASGI request hardening middleware (0021).

Body-size ceiling, fixed-window rate limits, request correlation IDs,
the opt-in internal token check, and the persistent single-user session
layer (LUMIRSS_AUTH_MODE=session). Registered on the app in main.py.
"""


import asyncio
import contextlib
import json
import logging
import re
import time
import urllib.parse
import uuid
from contextvars import ContextVar
from pathlib import Path

from lumirss.config import LumiSettings
from lumirss.util import constant_time_equals

MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024

# -- Correlation IDs (pool #47) ---------------------------------------------
#
# Every request gets an X-Request-ID: echoed from the client when it is a
# safe bounded token, otherwise generated. The id rides back on EVERY
# response (including error envelopes) so a failing front-end action can
# be joined with the server log line that carries the same id. The
# contextvar makes it readable anywhere in-process for future structured
# logging / diagnostics export.

_request_id_var: ContextVar[str | None] = ContextVar(
    "lumirss_request_id", default=None
)
_REQUEST_ID_HEADER = b"x-request-id"
# Inbound ids must already be safe log/header tokens; anything else is
# replaced (never reflected back unbounded — header/log injection guard).
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

_logger = logging.getLogger("lumirss.request")
_access_logger = logging.getLogger("lumirss.access")


def current_request_id() -> str | None:
    return _request_id_var.get()


class RequestCorrelationMiddleware:
    """Attach a correlation id to every request/response pair."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw = headers.get(_REQUEST_ID_HEADER)
        inbound = raw.decode("ascii", "ignore") if raw else ""
        request_id = inbound if _SAFE_REQUEST_ID.match(inbound) else uuid.uuid4().hex
        token = _request_id_var.set(request_id)

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": list(message.get("headers") or [])
                    + [(_REQUEST_ID_HEADER, request_id.encode("ascii"))],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # Unhandled errors only print a bare traceback otherwise —
            # the correlation id is what ties the user-visible failure
            # to this exact log record.
            _logger.exception("request failed [request_id=%s]", request_id)
            raise
        finally:
            _request_id_var.reset(token)

# phase2 recovery (P0-06g): the mail ingest webhook accepts raw MIME up
# to 10MB (routers/mail.py enforces the same cap). The global 4MB
# ceiling would otherwise reject large mails before the route sees them.
MAIL_INGEST_BODY_LIMIT = 10 * 1024 * 1024
_MAIL_INGEST_PREFIX = "/api/mail/ingest/"
_INBOX_INGEST_PREFIX = "/api/v1/inbox/ingest/"


def _bearer_machine_path(path: str, headers) -> bool:
    """True for machine-to-machine ingest endpoints carrying a bearer
    secret (validated constant-time by the route, never logged): the
    token/session layers defer these requests to the route boundary."""
    if not any(key == b"authorization" for key, _ in headers or []):
        return False
    return path.startswith(_MAIL_INGEST_PREFIX) or path.startswith(
        _INBOX_INGEST_PREFIX
    )


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
        path = scope.get("path", "")
        limit = (
            MAIL_INGEST_BODY_LIMIT
            if path.startswith(_MAIL_INGEST_PREFIX)
            else self.max_bytes
        )
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
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
                if received > limit:
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
    ("POST", "/api/v1/auth/register", "register", 10, 60),
    ("POST", "/api/v1/restore", "restore", 10, 60),
    ("POST", "/api/v1/backups/webdav", "backup_webdav", 10, 60),
    ("POST", "/api/v1/backups", "backup", 12, 60),
    ("POST", "/api/v1/opml/import", "opml", 6, 60),
    ("POST", "/api/v1/feed-preview", "outbound", 30, 60),
    ("POST", "/api/v1/source-discovery", "outbound", 30, 60),
    ("POST", "/api/v1/inbox/sources", "inbox_write", 12, 60),
    ("POST", "/api/v1/inbox/ingest/", "inbox_ingest", 120, 60),
    ("DELETE", "/api/v1/inbox/", "inbox_write", 60, 60),
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
                # phase2 recovery (P0-06d): the mail ingest webhook is
                # machine-to-machine — external relays carry the per-list
                # bearer secret (validated constant-time by the route),
                # never the internal token. Defer only bearer-bearing
                # requests; everything else stays token-gated. 0021 adds
                # the inbox push ingest to the same treatment.
                if _bearer_machine_path(path, scope.get("headers") or []):
                    await self.app(scope, receive, send)
                    return
                token = LumiSettings().LUMIRSS_INTERNAL_TOKEN.get_secret_value()
                if token:
                    supplied = ""
                    for key, value in scope.get("headers") or []:
                        if key == b"x-lumi-token":
                            supplied = value.decode("latin-1")
                            break
                    if not constant_time_equals(supplied, token):
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
# pre-login (login / invite activation / recovery / setup probes, plus
# the N006 passkey-login and N007 TOTP two-step completion — all of
# which mint sessions only after cryptographic/second-factor checks).
# Everything else under /api/ requires a session. Unsafe methods on
# these paths STILL pass the Origin check below (CSRF, O170).
SESSION_PUBLIC_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/session",
        "/api/v1/auth/activate",
        "/api/v1/auth/activation-preview",
        "/api/v1/auth/recover",
        "/api/v1/auth/first-run",
        "/api/v1/auth/passkeys/login/options",
        "/api/v1/auth/passkeys/login",
        "/api/v1/auth/totp/verify",
        "/api/v1/version",
    }
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
    """Cookie-session gate for /api/* (opt-in via LUMIRSS_AUTH_MODE).

    Multi-account (0067): a valid session resolves to its verified user,
    the user must still be active, and the identity is published for the
    request via ``scope["lumi_principal"]`` plus the user-scope ContextVar
    that routes every private database access (user_scope.RoutingDatabase).
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        auth_mode = LumiSettings().LUMIRSS_AUTH_MODE
        if auth_mode != "session":
            # Legacy single-user mode (dev / basic reverse-proxy auth):
            # every request implicitly addresses the owner account.
            owner_id = await _implicit_owner_id(scope)
            if owner_id is None:
                await _reject_session_required(send)
                return
            from lumirss.user_scope import load_user_env, user_context

            scope["lumi_principal"] = {"user_id": owner_id, "role": "owner", "username": "owner"}
            scope["lumi_user_env"] = await load_user_env(scope.get("app").state, owner_id, "owner", "owner")
            with user_context(owner_id):
                await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers") or []
        method = scope.get("method", "")
        # CSRF gate FIRST (O170): unsafe methods — including on public
        # auth paths (activation / recovery writes) — need a same-origin
        # context. Browsers always send Origin on cross-site unsafe
        # requests; its absence means a non-browser caller, which still
        # has to pass the internal-token layer in production.
        if method in _UNSAFE_METHODS and not _origin_allowed(scope, headers):
            await _reject_forbidden(send)
            return
        if path in SESSION_PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        # phase2 recovery (P0-06d): bearer-authenticated machine ingest —
        # defer to the route (constant-time secret check; the secret is
        # never logged). The route resolves the owning user from the
        # token_owner_index and enters that user's scope itself. 0021
        # adds the inbox push ingest.
        if _bearer_machine_path(path, headers):
            await self.app(scope, receive, send)
            return
        raw_token = parse_session_cookie(headers)
        state = scope.get("app").state if scope.get("app") else None
        if state is None or raw_token is None:
            await _reject_session_required(send)
            return
        from lumirss.auth_store import AuthStore

        store = AuthStore(state.control_db)
        resolved = await store.get_valid_session_user(raw_token)
        if resolved is None:
            await _reject_session_required(send)
            return
        user_id, _expires_at = resolved
        principal = await _principal_for_user(state, user_id)
        if principal is None:
            await _reject_session_required(send)
            return
        settings = LumiSettings()
        with contextlib.suppress(Exception):  # renewal must never break reading
            await store.touch_session(raw_token, settings.LUMIRSS_SESSION_MAX_AGE_DAYS)
        from lumirss.user_scope import load_user_env, user_context

        scope["lumi_principal"] = principal
        scope["lumi_user_env"] = await load_user_env(
            state, user_id, principal["role"], principal["username"]
        )
        with user_context(user_id):
            await self.app(scope, receive, send)


async def _principal_for_user(state, user_id: str) -> dict[str, str] | None:
    """User row → principal dict; None when the user vanished/paused."""
    from lumirss.accounts_store import AccountsStore

    user = await AccountsStore(state.control_db).get_user(user_id)
    if user is None or user.get("status") != "active":
        return None
    return {
        "user_id": str(user["id"]),
        "role": str(user["role"]),
        "username": str(user["username"]),
    }


_implicit_owner_lock = asyncio.Lock()
_implicit_owner_cache: dict[str, str] = {}


async def _implicit_owner_id(scope) -> str | None:
    """Owner user id for legacy single-user mode (cached per process).

    The owner row is created by the startup migration; until it exists
    there is no user database to address and /api business routes must
    fail closed (session_required) instead of guessing an identity.
    Cache key = control database path (NOT id(state)): a replaced or
    re-created control database must not inherit the previous owner id.
    """
    app = scope.get("app")
    state = getattr(app, "state", None) if app else None
    if state is None:
        return None
    from lumirss.config import LumiSettings as _Settings

    key = str(Path(_Settings().LUMIRSS_DB_PATH))
    cached = _implicit_owner_cache.get(key)
    if cached:
        return cached
    async with _implicit_owner_lock:
        cached = _implicit_owner_cache.get(key)
        if cached:
            return cached
        from lumirss.accounts_store import AccountsStore

        try:
            users = AccountsStore(state.control_db)
            owner = None
            for row in await users.list_users(limit=500):
                if row.get("role") == "owner":
                    owner = row
                    break
            if owner is not None:
                _implicit_owner_cache[key] = str(owner["id"])
                return str(owner["id"])
        except Exception:  # noqa: BLE001 — fail closed below
            return None
    return None


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

# 2026-09-20 安全整改（ROADMAP 遗留 P2）：反代后 socket peer 恒为代理，
# 单桶会被第三方锁死登录。仅当直连 peer 落在可信代理网段时才采纳
# X-Forwarded-For 的**最后一跳**（由可信代理追加的真实客户端）；不可信
# peer 的 XFF 一律忽略（防伪造）。默认信任 loopback + 私网 + 链路本地
# ——单用户自托管拓扑（Caddy 同机/同 compose 网）；可用
# LUMIRSS_TRUSTED_PROXY_NETWORKS 覆盖（逗号分隔 CIDR）。
_DEFAULT_TRUSTED_PROXY_NETWORKS = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "fc00::/7",
)


def _trusted_proxy_networks() -> tuple:
    import ipaddress

    from lumirss.config import LumiSettings

    raw = LumiSettings().LUMIRSS_TRUSTED_PROXY_NETWORKS
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            nets.append(ipaddress.ip_network(part, strict=False))
    if nets:
        return tuple(nets)
    return tuple(ipaddress.ip_network(n) for n in _DEFAULT_TRUSTED_PROXY_NETWORKS)


def _is_trusted_proxy(peer: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in _trusted_proxy_networks())


def _client_key(scope) -> str:
    client = scope.get("client")
    peer = client[0] if client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer
    raw_xff = dict(scope.get("headers") or []).get(b"x-forwarded-for")
    if raw_xff:
        # 最后一跳：由本方可信代理追加的客户端地址（第一跳可被客户端伪造）。
        last_hop = raw_xff.decode("latin-1").split(",")[-1].strip()
        if last_hop:
            return last_hop
    return peer


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


# ---------------------------------------------------------------------------
# E01 structured access log: one JSON line per request on
# "lumirss.access". Fields are exactly what an operator needs to
# reconstruct a request (correlation id, matched route template, status,
# duration, server-derived actor, exception class) — and nothing else:
# query strings (activation/reset tokens ride there), bodies, headers and
# credentials are never logged. LUMIRSS_ACCESS_LOG=off silences it.
# Registered INSIDE the correlation layer, so the request-id contextvar
# is still set when the record is emitted.


class RequestLogMiddleware:
    """Structured request log (E01)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if LumiSettings().LUMIRSS_ACCESS_LOG == "off":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status: list[int] = [0]

        async def send_with_capture(message) -> None:
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)

        error_class: str | None = None
        try:
            await self.app(scope, receive, send_with_capture)
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
            error_class = type(exc).__name__
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            principal = scope.get("lumi_principal") or {}
            # Matched route template after routing; raw path only when
            # unrouted (404) — query strings are deliberately excluded.
            route = getattr(scope.get("route"), "path", None) or scope.get("path", "")
            record = {
                "event": "access",
                "component": "http",
                "request_id": current_request_id(),
                "method": scope.get("method", ""),
                "route": route,
                "status": status[0],
                "duration_ms": duration_ms,
                "user_id": principal.get("user_id"),
                "role": principal.get("role"),
                "error": error_class,
            }
            if status[0] >= 500 or error_class:
                level = logging.ERROR
            elif status[0] >= 400:
                level = logging.WARNING
            else:
                level = logging.INFO
            _access_logger.log(level, json.dumps(record, ensure_ascii=False))


