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
from pathlib import Path

import httpx
from fastapi import FastAPI

from lumirss.config import LumiSettings
from lumirss.errors import register_error_handlers
from lumirss.middleware import (
    MAX_REQUEST_BODY_BYTES,  # noqa: F401  (re-exported for tests)
    InternalTokenMiddleware,
    RateLimitMiddleware,
    RequestCorrelationMiddleware,
    RequestSizeLimitMiddleware,
    SessionAuthMiddleware,
)
from lumirss.obsidian import ObsidianService
from lumirss.routers import (
    admin,
    agent,
    ai_settings,
    ai_tasks,
    annotations,
    api_sources,
    auth,
    authors,
    backup,
    clips,
    discovery,
    duplicates,
    entries,
    entry_ai,
    feed_filters,
    feeds,
    glossary,
    gpt_digest,
    graph_views,
    health,
    import_batches,
    inbox,
    knowledge,
    library,
    library_trash,
    library_w5,
    lumi_export,
    lumi_notes,
    mail,
    obsidian,
    operations,
    opml,
    qa_templates,
    quiz,
    rag,
    reading_extras,
    relations,
    rsshub,
    search,
    settings,
    snapshots,
    sources,
    storage,
    subscriptions,
    tags,
    task_records,
    view_feed,
    workspace_w5,
    workspaces,
)
from lumirss.routers import (
    synonyms as search_synonyms,
)
from lumirss.search_index import SearchIndexService

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
    # 0067 邀请制多账户：LUMIRSS_DB_PATH 是控制库（身份/会话/邀请/池/
    # 审计）；每个用户的业务数据在 users/<uid>/lumi.sqlite，由
    # RoutingDatabase 按请求身份路由（app.state.db 保持历史属性名，
    # 所有 store 无感获得用户隔离）。启动时先完成旧单用户库 → owner
    # 账户的幂等迁移（O148）。
    from lumirss.accounts_store import AccountsStore
    from lumirss.owner_migration import ensure_owner_migration
    from lumirss.secrets_store import SecretsStore
    from lumirss.storage import Database as _ControlDatabase
    from lumirss.user_scope import RoutingDatabase, RoutingSecretsStore

    control_settings = LumiSettings()
    app.state.control_db = _ControlDatabase(control_settings.LUMIRSS_DB_PATH)
    _users_root = Path(control_settings.LUMIRSS_DB_PATH).expanduser().parent / "users"
    app.state.users_root = _users_root
    app.state.control_secrets = SecretsStore(
        Path(control_settings.secrets_path).parent / "control-secrets.json"
    )
    app.state.accounts = AccountsStore(app.state.control_db)
    owner_id = await ensure_owner_migration(app.state.control_db, app.state.control_secrets)
    app.state.owner_id = owner_id
    # Legacy attribute names keep their meaning for every store/router:
    app.state.db = RoutingDatabase(control_settings.LUMIRSS_DB_PATH, _users_root)
    app.state.secrets_store = RoutingSecretsStore(_users_root)
    app.state.user_services = {}
    # §13.4：存量明文凭据的一次性哈希回填（幂等；四表 + gpt_digest
    # feed token）。失败不阻塞启动——校验层 verify_token 对旧明文行
    # 永远兼容，回填只是把「静态明文」收敛为「静态哈希」。在 owner
    # 用户上下文中运行：回填作用于各用户库的表。
    try:
        from lumirss.token_backfill import (
          backfill_token_hashes,
          upgrade_digest_feed_token,
        )
        from lumirss.user_scope import user_context

        migrated: dict[str, int] = {}
        upgraded = False
        for uid in await app.state.accounts.active_user_ids():
            with user_context(uid):
                migrated.update(await backfill_token_hashes(app.state.db))
                upgraded = upgrade_digest_feed_token(app.state.secrets_store) or upgraded
        if any(migrated.values()) or upgraded:
            _logger.info(
                "token hash backfill done: %s digest_token_upgraded=%s",
                migrated,
                upgraded,
            )
    except Exception:  # noqa: BLE001 — never block startup on the upgrade
        _logger.exception("token hash backfill failed (legacy verify stays compatible)")
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
    app.state.inbox_store = None
    app.state.favorites_service = None
    app.state.library_search_writer = None
    app.state.rag_service = None
    app.state.agent_store = None
    app.state.agent_loop = None
    app.state.agent_tasks = set()
    app.state.agent_dry_run = None  # F097 写操作预演执行器（惰性构建）。
    app.state.tag_store = None
    app.state.saved_search_store = None
    # W2（F021–F040）新增服务槽位：与上方同一惰性构建约定。
    app.state.item_relation_store = None
    app.state.inbox_rule_store = None
    app.state.author_alias_store = None
    app.state.qa_template_store = None
    app.state.summary_version_store = None
    # P0-06: digest scheduler + IMAP poll loop. Both factories return
    # self-disabling tasks (sleeping no-ops while unconfigured), so the
    # tasks exist unconditionally and settings drive actual behavior.
    from lumirss.mail_digest import build_digest_scheduler_task
    from lumirss.mail_imap import build_mail_imap_task

    app.state.digest_scheduler_task = build_digest_scheduler_task(app.state)
    app.state.mail_imap_task = build_mail_imap_task(app.state)
    # M4: GPT 日报调度（同一工厂接法；未配置时是睡眠 no-op）。
    from lumirss.gpt_digest import build_gpt_digest_scheduler_task

    app.state.gpt_digest_scheduler_task = build_gpt_digest_scheduler_task(
        app.state
    )
    # P0-07d: the RAG idle-unload loop (no-op until the RAG service is
    # first built) keeps the low-memory budget honest in production.
    from lumirss.rag import build_rag_idle_task

    app.state.rag_idle_task = build_rag_idle_task(app.state)

    settings = LumiSettings()
    interval = settings.LUMIRSS_SEARCH_SYNC_INTERVAL
    app.state.search_sync_task = None
    # P0-08f: the obsidian service exists for the whole process lifetime
    # (never request-lazy) so agent tool registration cannot bake in a
    # None based on which page was opened first. The Vault belongs to the
    # OPERATOR (O168): the service is bound to the owner's context.
    app.state.obsidian_service = ObsidianService(
        app.state.db, env_root=settings.LUMIRSS_OBSIDIAN_VAULT_DIR
    )
    app.state.obsidian_scan_task = None
    if interval > 0:
        # Per-user search sync (0067/O163): each active user's projection
        # syncs from THAT user's FreshRSS under their own context.
        async def search_sync_loop() -> None:
            from lumirss.control_resources import user_freshrss_adapter
            from lumirss.user_scope import for_each_active_user

            async def sync_user(uid: str) -> None:
                cache = app.state.user_services
                key = (uid, "bg_search_service")
                service = cache.get(key)
                if service is None:
                    adapter = await user_freshrss_adapter(app.state, uid)
                    if adapter is None:
                        return  # unbound account: honest skip
                    service = SearchIndexService(app.state.db, adapter)
                    cache[key] = service
                await service.maybe_sync()

            while True:
                await asyncio.sleep(interval)
                await for_each_active_user(app.state, sync_user)

        # P0-13: the task exists only when sync is enabled; interval=0 must
        # not create a sleep(0) hot loop.
        app.state.search_sync_task = asyncio.create_task(search_sync_loop())
    obsidian_interval = settings.LUMIRSS_OBSIDIAN_SCAN_INTERVAL
    if obsidian_interval > 0:

        async def obsidian_scan_loop() -> None:
            from lumirss.user_scope import user_context

            while True:
                await asyncio.sleep(obsidian_interval)
                service: ObsidianService | None = app.state.obsidian_service
                if service is None:
                    continue
                owner_id = app.state.owner_id
                if not owner_id:
                    continue
                try:
                    with user_context(owner_id):
                        await service.scan_if_configured()
                except Exception:  # noqa: BLE001 — scan must never kill the app
                    _logger.exception("obsidian scan failed; will retry")

        app.state.obsidian_scan_task = asyncio.create_task(obsidian_scan_loop())
    rag_index_interval = settings.LUMIRSS_RAG_INDEX_INTERVAL
    app.state.rag_index_task = None
    if rag_index_interval > 0:
        # Q-P2-02: converge new projection rows into the semantic index
        # (and sweep deleted ones) without a manual full rebuild.
        from lumirss.rag import build_rag_incremental_task

        app.state.rag_index_task = build_rag_incremental_task(
            app.state, rag_index_interval
        )
    yield
    sync_task = app.state.search_sync_task
    if sync_task is not None:
        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task
    obsidian_task = app.state.obsidian_scan_task
    if obsidian_task is not None:
        obsidian_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await obsidian_task
    for task_name in (
        "digest_scheduler_task",
        "mail_imap_task",
        "rag_idle_task",
        "rag_index_task",
    ):
        task = getattr(app.state, task_name, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    # In-flight agent turns use the shared http_client: give them a short
    # window to finalize (their `finally` marks the turn done) before the
    # client closes underneath them, then cancel whatever is still running.
    agent_tasks = [t for t in app.state.agent_tasks if not t.done()]
    if agent_tasks:
        _, still_running = await asyncio.wait(
            agent_tasks, timeout=5.0
        )
        for task in still_running:
            task.cancel()
        await asyncio.gather(*still_running, return_exceptions=True)
    # 0067: every per-user RAG service holds one raw sqlite-vec connection
    # to its owner's database file — close each built instance (plus the
    # legacy basic-mode handle) so shutdown releases them all.
    for key, service in list(getattr(app.state, "user_services", {}).items()):
        if key[1] == "rag_service":
            with contextlib.suppress(Exception):
                service.close()
    legacy_rag = getattr(app.state, "rag_service", None)
    if legacy_rag is not None:
        with contextlib.suppress(Exception):
            legacy_rag.close()
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
# pool #47: correlation IDs — outermost of all, so every response
# (including 401/413 envelopes) carries X-Request-ID.
app.add_middleware(RequestCorrelationMiddleware)

# Routers are included in the original route-declaration order (matches the
# historical main.py; URL spaces are disjoint but ordering stays explicit).
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(feeds.router)
app.include_router(entries.router)
app.include_router(feed_filters.router)
app.include_router(annotations.router)
app.include_router(reading_extras.router)
app.include_router(import_batches.router)
app.include_router(subscriptions.router)
app.include_router(discovery.router)
app.include_router(duplicates.router)
app.include_router(rsshub.router)
app.include_router(opml.router)
app.include_router(ai_settings.router)
app.include_router(ai_tasks.router)
app.include_router(entry_ai.router)
app.include_router(settings.router)
app.include_router(operations.router)
app.include_router(backup.router)
app.include_router(search.router)
app.include_router(search_synonyms.router)
app.include_router(view_feed.router)
app.include_router(library.router)
app.include_router(library_trash.router)
app.include_router(workspaces.router)
app.include_router(clips.router)
app.include_router(snapshots.router)
app.include_router(api_sources.router)
app.include_router(mail.router)
app.include_router(obsidian.router)
app.include_router(inbox.router)
app.include_router(sources.router)
app.include_router(rag.router)
app.include_router(agent.router)
app.include_router(tags.router)
app.include_router(authors.router)
app.include_router(gpt_digest.router)
app.include_router(graph_views.router)
app.include_router(glossary.router)
app.include_router(knowledge.router)
app.include_router(storage.router)
app.include_router(lumi_export.router)
app.include_router(lumi_notes.router)
app.include_router(relations.router)
app.include_router(qa_templates.router)
app.include_router(quiz.router)
app.include_router(task_records.router)
# W5 (F081–F100)
app.include_router(library_w5.router)
app.include_router(workspace_w5.router)

register_error_handlers(app)
