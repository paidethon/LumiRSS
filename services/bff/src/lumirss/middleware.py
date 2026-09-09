"""Pure-ASGI request hardening middleware (0021).

Body-size ceiling, fixed-window rate limits and the opt-in
internal token check. Registered on the app in main.py.
"""


import hmac
import time

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


