"""LumiRSS BFF application entry point.

Assembly only: lifespan (shared clients/stores), the pure-ASGI hardening
middleware stack, route modules and the stable error envelope. Route
handlers live in ``lumirss/routers/*``, request plumbing in
``lumirss.deps``, error mapping in ``lumirss.errors`` and request
hardening in ``lumirss.middleware``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from lumirss.config import LumiSettings
from lumirss.errors import register_error_handlers
from lumirss.middleware import (
    MAX_REQUEST_BODY_BYTES,  # noqa: F401  (re-exported for tests)
    InternalTokenMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)
from lumirss.routers import (
    ai_settings,
    backup,
    discovery,
    entries,
    entry_ai,
    feeds,
    health,
    operations,
    opml,
    rsshub,
    settings,
    subscriptions,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the shared HTTP client; the FreshRSSAdapter is created lazily
    on the first /api/v1/feeds request (so /health/live works even when
    FreshRSS is not configured). The Lumi SQLite Database handle is created
    here too — cheap, no file I/O; migrations run lazily on the first
    storage use (0015)."""
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        trust_env=False,
    )
    app.state.db = Database(LumiSettings().LUMIRSS_DB_PATH)
    app.state.secrets_store = SecretsStore(LumiSettings().secrets_path)
    app.state.ai_settings_store = None
    app.state.ai_profile_store = None
    app.state.app_settings_store = None
    app.state.summary_service = None
    app.state.translation_service = None
    app.state.conversation_service = None
    app.state.freshrss_adapter = None
    app.state.freshrss_control_adapter = None
    app.state.feed_preview_service = None
    app.state.source_discovery_service = None
    app.state.rsshub_service = None
    app.state.rsshub_credentials_store = None
    app.state.segment_translation_service = None
    app.state.operations_service = None
    app.state.rsshub_control_store = None
    app.state.backup_jobs = None
    app.state.webdav_settings = None
    app.state.backup_engine = None
    app.state.restore_service = None
    yield
    await app.state.http_client.aclose()


# response_model_exclude_none keeps model-validated responses byte-compatible
# with the historical dict payloads for the routes that omit empty keys; the
# routes whose wire format carries explicit nulls override it per-route.
app = FastAPI(
    title="LumiRSS BFF",
    lifespan=lifespan,
    response_model_exclude_none=True,
)

# 0021 hardening stack (order = onion: last added runs first):
# body ceiling, rate limits, internal token.
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(InternalTokenMiddleware)

# Routers are included in the original route-declaration order (matches the
# historical main.py; URL spaces are disjoint but ordering stays explicit).
app.include_router(health.router)
app.include_router(feeds.router)
app.include_router(entries.router)
app.include_router(subscriptions.router)
app.include_router(discovery.router)
app.include_router(rsshub.router)
app.include_router(opml.router)
app.include_router(ai_settings.router)
app.include_router(entry_ai.router)
app.include_router(settings.router)
app.include_router(operations.router)
app.include_router(backup.router)

register_error_handlers(app)
