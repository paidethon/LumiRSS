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
    NoStoreCacheMiddleware,
    RateLimitMiddleware,
    RequestCorrelationMiddleware,
    RequestLogMiddleware,
    RequestSizeLimitMiddleware,
    SessionAuthMiddleware,
)
from lumirss.obsidian import ObsidianService
from lumirss.routers import (
    admin,
    agent,
    ai_settings,
    ai_tasks,
    annotation_baskets,
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
    new201_takeover,
    new202_observation,
    new203_views,
    new204_mirror,
    new205_retention,
    new206_calendar,
    new207_rsshub_form,
    new208_credential,
    new209_recycle,
    new210_pause,
    new211_merge_wizard,
    new212_rename_impact,
    new213_tag_groups,
    new214_tag_synonyms,
    new215_tag_cleanup,
    new216_collection_snapshots,
    new217_sort_recipes,
    new218_reference_check,
    new219_archive_batches,
    new220_triage_journal,
    new221_time_slots,
    new222_queue_prereqs,
    new223_workload,
    new224_reading_reminders,
    new225_backlog_wizard,
    new226_queue_capacity,
    new227_section_plans,
    new228_interruption_notes,
    new229_reading_pacts,
    new230_queue_topics,
    new231_note_versions,
    new232_reanchor,
    new233_summary,
    new234_layers,
    new235_templates,
    new236_replies,
    new237_quote_cards,
    new238_layer_migration,
    new239_conflicts,
    new240_attachments,
    new241_article_versions,
    new242_source_timeline,
    new243_raw_fields,
    new244_link_recheck,
    new245_citation_fields,
    new246_citation_chain,
    new247_content_watch,
    new248_detrack,
    new249_licenses,
    new250_evidence,
    new251_research,
    new252_hypotheses,
    new253_counterexamples,
    new254_project_glossary,
    new255_timeline,
    new256_decisions,
    new257_gaps,
    new258_outline,
    new259_conclusion_history,
    new260_share_preview,
    new261_glossary_choices,
    new262_revision_decisions,
    new263_quality_feedback,
    new264_capability_probes,
    new265_budget,
    new266_priority_queue,
    new267_protect_exceptions,
    new268_quote_exports,
    new269_language_overrides,
    new270_completeness_reports,
    new271_input_preview,
    new272_ai_drafts,
    new273_template_trials,
    new274_citation_checks,
    new275_batch_approvals,
    new276_task_replays,
    new277_purpose_constraints,
    new278_privacy_filters,
    new279_answer_adoptions,
    new280_quota_buckets,
    obsidian,
    operations,
    opml,
    passkeys,
    privacy,
    qa,
    qa_templates,
    quick_actions,
    quiz,
    rag,
    reading_extras,
    reading_questions,
    reading_queue,
    relations,
    rsshub,
    search,
    settings,
    snapshots,
    source_lifecycle,
    sources,
    storage,
    subscriptions,
    tags,
    task_records,
    totp,
    tts,
    view_feed,
    whats_new,
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
    interval. Its failures are logged, never fatal.

    ARCH-08 ordering contract (pinned by tests/test_arch08_runtime.py):

    1. http_client + control-db handle (no I/O);
    2. migrations + legacy owner migration — ``ensure_owner_migration``
       awaits the control ``migrate()`` BEFORE anything else runs;
    3. token hash backfill (best-effort, never blocks startup);
    4. ONLY THEN the background schedulers start, through the process
       single-owner registry (a repeated startup re-uses live tasks);
    5. the app becomes ready (``yield``) strictly after 1-4;
    6. shutdown: background tasks cancel → bounded await → stragglers
       reported, then agent drain (5s), RAG connections close, http
       client closes — deterministic, no unbounded awaits.
    """
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
    # N011/N016/N017: source lifecycle tools (staging pool + bundle).
    app.state.staged_source_store = None
    app.state.source_bundle_service = None
    app.state.favorites_service = None
    app.state.library_search_writer = None
    app.state.rag_service = None
    app.state.agent_store = None
    app.state.agent_loop = None
    app.state.agent_tasks = set()
    app.state.agent_dry_run = None  # F097 写操作预演执行器（惰性构建）。
    app.state.agent_undo = None  # N169 写工具差异撤销执行器（惰性构建）。
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
    # ARCH-08: every slot goes through the process-level registry — a
    # repeated startup in one process returns the ALREADY-RUNNING task
    # instead of orphaning a duplicate loop behind the app.state slot.
    from lumirss.mail_digest import build_digest_scheduler_task
    from lumirss.mail_imap import build_mail_imap_task
    from lumirss.runtime import SCHEDULERS

    app.state.digest_scheduler_task = SCHEDULERS.start(
        "digest_scheduler",
        lambda: build_digest_scheduler_task(app.state),
    )
    app.state.mail_imap_task = SCHEDULERS.start(
        "mail_imap",
        lambda: build_mail_imap_task(app.state),
    )
    # M4: GPT 日报调度（同一工厂接法；未配置时是睡眠 no-op）。
    from lumirss.gpt_digest import build_gpt_digest_scheduler_task

    app.state.gpt_digest_scheduler_task = SCHEDULERS.start(
        "gpt_digest_scheduler",
        lambda: build_gpt_digest_scheduler_task(app.state),
    )
    # P0-07d: the RAG idle-unload loop (no-op until the RAG service is
    # first built) keeps the low-memory budget honest in production.
    from lumirss.rag import build_rag_idle_task

    app.state.rag_idle_task = SCHEDULERS.start(
        "rag_idle",
        lambda: build_rag_idle_task(app.state),
    )

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
        app.state.search_sync_task = SCHEDULERS.start(
            "search_sync", lambda: asyncio.create_task(search_sync_loop())
        )
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

        app.state.obsidian_scan_task = SCHEDULERS.start(
            "obsidian_scan", lambda: asyncio.create_task(obsidian_scan_loop())
        )
    rag_index_interval = settings.LUMIRSS_RAG_INDEX_INTERVAL
    app.state.rag_index_task = None
    if rag_index_interval > 0:
        # Q-P2-02: converge new projection rows into the semantic index
        # (and sweep deleted ones) without a manual full rebuild.
        from lumirss.rag import build_rag_incremental_task

        app.state.rag_index_task = SCHEDULERS.start(
            "rag_index",
            lambda: build_rag_incremental_task(app.state, rag_index_interval),
        )
    yield
    # ARCH-08 shutdown contract: cancel → bounded await → report. The
    # registry owns every lifespan slot, so one bounded stop covers the
    # conditional loops (search sync / obsidian / rag index) and the
    # always-on schedulers; a task that refuses to die within the window
    # is reported (logged) instead of hanging process shutdown forever.
    await SCHEDULERS.stop_all(timeout=10.0)
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
# E01 structured access log — registered before the correlation layer,
# so it runs INSIDE it and the request-id contextvar is readable when
# the record is emitted.
app.add_middleware(RequestLogMiddleware)
# pool #47: correlation IDs — outermost of all, so every response
# (including 401/413 envelopes) carries X-Request-ID. FIX-368 no-store
# stamping sits one layer beneath it so its envelopes are covered too.
app.add_middleware(NoStoreCacheMiddleware)
app.add_middleware(RequestCorrelationMiddleware)

# Routers are included in the original route-declaration order (matches the
# historical main.py; URL spaces are disjoint but ordering stays explicit).
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(passkeys.router)
app.include_router(totp.router)
app.include_router(admin.router)
app.include_router(feeds.router)
app.include_router(entries.router)
app.include_router(feed_filters.router)
app.include_router(annotations.router)
# N072 批注精选篮 / N098 服务端 TTS 缓存 / N199 多步快捷操作
app.include_router(annotation_baskets.router)
app.include_router(tts.router)
app.include_router(quick_actions.router)
app.include_router(reading_extras.router)
app.include_router(reading_questions.router)
app.include_router(reading_queue.router)
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
app.include_router(privacy.router)
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
# N011/N016/N017: bundle / staging pool / cleanup suggestions
app.include_router(source_lifecycle.router)
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
app.include_router(qa.router)
app.include_router(qa_templates.router)
app.include_router(quiz.router)
app.include_router(task_records.router)
# W5 (F081–F100)
app.include_router(library_w5.router)
app.include_router(workspace_w5.router)
# N198 版本功能导览（成员可读；adminOnly 条目服务端角色过滤）
app.include_router(whats_new.router)
# NEW-201..210 来源运维工作台（订阅的组织、维护与可控接入）
app.include_router(new201_takeover.router)
app.include_router(new202_observation.router)
app.include_router(new203_views.router)
app.include_router(new204_mirror.router)
app.include_router(new205_retention.router)
app.include_router(new206_calendar.router)
app.include_router(new207_rsshub_form.router)
app.include_router(new208_credential.router)
app.include_router(new209_recycle.router)
app.include_router(new210_pause.router)
# NEW-211..220 标签、集合与内容整理（全部本地表，无 AI / 无上游网络）
app.include_router(new211_merge_wizard.router)
app.include_router(new212_rename_impact.router)
app.include_router(new213_tag_groups.router)
app.include_router(new214_tag_synonyms.router)
app.include_router(new215_tag_cleanup.router)
app.include_router(new216_collection_snapshots.router)
app.include_router(new217_sort_recipes.router)
app.include_router(new218_reference_check.router)
app.include_router(new219_archive_batches.router)
app.include_router(new220_triage_journal.router)
# NEW-221..230 队列和阅读计划的用户决策（r3 阅读队列家族延伸）
app.include_router(new221_time_slots.router)
app.include_router(new222_queue_prereqs.router)
app.include_router(new223_workload.router)
app.include_router(new224_reading_reminders.router)
app.include_router(new225_backlog_wizard.router)
app.include_router(new226_queue_capacity.router)
app.include_router(new227_section_plans.router)
app.include_router(new228_interruption_notes.router)
app.include_router(new229_reading_pacts.router)
app.include_router(new230_queue_topics.router)
# NEW-231..240 笔记、标注与原文锚定（r2 N231 组；路由各自独立成文件）
app.include_router(new231_note_versions.router)
app.include_router(new232_reanchor.router)
app.include_router(new233_summary.router)
app.include_router(new234_layers.router)
app.include_router(new235_templates.router)
app.include_router(new236_replies.router)
app.include_router(new237_quote_cards.router)
app.include_router(new238_layer_migration.router)
app.include_router(new239_conflicts.router)
app.include_router(new240_attachments.router)
# NEW-241..250 原文版本、溯源与证据（r2 N241 组；路由各自独立成文件）
app.include_router(new241_article_versions.router)
app.include_router(new242_source_timeline.router)
app.include_router(new243_raw_fields.router)
app.include_router(new244_link_recheck.router)
app.include_router(new245_citation_fields.router)
app.include_router(new246_citation_chain.router)
app.include_router(new247_content_watch.router)
app.include_router(new248_detrack.router)
app.include_router(new249_licenses.router)
app.include_router(new250_evidence.router)
# NEW-251..260 研究项目组：问题拆分/假设/反例/术语/时间线/决策/缺口/
# 大纲/结论历史/分享脱敏预览（全部 per-user 本地表，无 AI / 无上游网络）
app.include_router(new251_research.router)
app.include_router(new252_hypotheses.router)
app.include_router(new253_counterexamples.router)
app.include_router(new254_project_glossary.router)
app.include_router(new255_timeline.router)
app.include_router(new256_decisions.router)
app.include_router(new257_gaps.router)
app.include_router(new258_outline.router)
app.include_router(new259_conclusion_history.router)
app.include_router(new260_share_preview.router)
app.include_router(new261_glossary_choices.router)
app.include_router(new262_revision_decisions.router)
app.include_router(new263_quality_feedback.router)
app.include_router(new264_capability_probes.router)
app.include_router(new265_budget.router)
app.include_router(new266_priority_queue.router)
app.include_router(new267_protect_exceptions.router)
app.include_router(new268_quote_exports.router)
app.include_router(new269_language_overrides.router)
app.include_router(new270_completeness_reports.router)
app.include_router(new271_input_preview.router)
app.include_router(new272_ai_drafts.router)
app.include_router(new273_template_trials.router)
app.include_router(new274_citation_checks.router)
app.include_router(new275_batch_approvals.router)
app.include_router(new276_task_replays.router)
app.include_router(new277_purpose_constraints.router)
app.include_router(new278_privacy_filters.router)
app.include_router(new279_answer_adoptions.router)
app.include_router(new280_quota_buckets.router)

register_error_handlers(app)
