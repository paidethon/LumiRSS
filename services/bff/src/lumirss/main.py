"""LumiRSS BFF application entry point.

Assembly only: lifespan (shared clients/stores + the search sync task),
the pure-ASGI hardening middleware stack, route modules and the stable
error envelope. Route handlers live in ``lumirss/routers/*``, request
plumbing in ``lumirss.deps``, error mapping in ``lumirss.errors`` and
request hardening in ``lumirss.middleware``.
"""

import asyncio
import contextlib
import logging
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
    SessionAuthMiddleware,
)
from lumirss.routers import (
    agent,
    ai_settings,
    api_sources,
    auth,
    backup,
    clips,
    discovery,
    entries,
    entry_ai,
    feeds,
    health,
    library,
    mail,
    obsidian,
    operations,
    opml,
    rag,
    rsshub,
    search,
    settings,
    snapshots,
    subscriptions,
    workspaces,
)
from lumirss.search_index import SearchIndexService
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

_logger = logging.getLogger("lumirss.search")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the shared HTTP client; the FreshRSSAdapter is created lazily
    on the first /api/v1/feeds request (so /health/live works even when
    FreshRSS is not configured). The Lumi SQLite Database handle is created
    here too — cheap, no file I/O; migrations run lazily on the first
    storage use (0015). The derived search projection is synced by a
    background task (0022): rebuild when empty, then catch up each
    interval. Its failures are logged, never fatal."""
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
    app.state.search_service = None
    app.state.library_store = None
    app.state.workspace_store = None
    app.state.source_registry = None
    app.state.clip_store = None
    app.state.asset_store = None
    app.state.snapshot_runner = None
    app.state.api_source_store = None
    app.state.mail_bridge_store = None
    app.state.obsidian_service = None
    app.state.favorites_service = None
    app.state.library_search_writer = None
    app.state.rag_service = None
    app.state.agent_store = None
    app.state.agent_loop = None
    app.state.agent_tasks = set()

    settings = LumiSettings()
    interval = settings.LUMIRSS_SEARCH_SYNC_INTERVAL
    if interval > 0:
        # Build the projection service eagerly so the background sync runs
        # even before the first search request. Unconfigured FreshRSS
        # (tests, degraded dev) simply leaves it disabled.
        try:
            from lumirss.adapters.freshrss import FreshRSSAdapter
            from lumirss.config import FreshRSSSettings

            app.state.search_service = SearchIndexService(
                app.state.db,
                FreshRSSAdapter(app.state.http_client, FreshRSSSettings()),
            )
        except Exception:  # noqa: BLE001 — never block startup on search
            _logger.info("search sync disabled (FreshRSS not configured)")

    async def search_sync_loop() -> None:
        while True:
            await asyncio.sleep(interval)
            service: SearchIndexService | None = app.state.search_service
            if service is None:
                continue
            try:
                await service.maybe_sync()
            except Exception:  # noqa: BLE001 — sync must never kill the app
                _logger.exception("search index sync failed; will retry")

    sync_task = asyncio.create_task(search_sync_loop())
    yield
    sync_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await sync_task
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
# body ceiling, rate limits, internal token, cookie session gate.
# SessionAuthMiddleware is outermost on purpose: it owns the browser-facing
# 401 (session_required) and the unsafe-method Origin check, while the
# internal-token layer still gates every non-Caddy caller beneath it.
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(InternalTokenMiddleware)
app.add_middleware(SessionAuthMiddleware)

# Routers are included in the original route-declaration order (matches the
# historical main.py; URL spaces are disjoint but ordering stays explicit).
app.include_router(health.router)
app.include_router(auth.router)
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
app.include_router(search.router)
app.include_router(library.router)
app.include_router(workspaces.router)
app.include_router(clips.router)
app.include_router(snapshots.router)
app.include_router(api_sources.router)
app.include_router(mail.router)
app.include_router(obsidian.router)
app.include_router(rag.router)
app.include_router(agent.router)

register_error_handlers(app)
