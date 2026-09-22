"""Per-request dependency accessors.

Lazily build adapters/stores/services once per app.state so a
request handler never constructs upstream clients directly.
"""

import logging
from pathlib import Path

from fastapi import Request
from pydantic import SecretStr, ValidationError

from lumirss.adapters.freshrss import (
    ConfigError,
    FreshRSSAdapter,
)
from lumirss.adapters.freshrss_control import (
    FreshRSSControlAdapter,
)
from lumirss.agent import AgentLoop
from lumirss.agent_store import AgentStore
from lumirss.agent_tools import build_registry
from lumirss.ai_conversation import ConversationService
from lumirss.ai_profiles import (
    AiProfileStore,
    PurposeAiSettings,
)
from lumirss.ai_settings import (
    AiSettingsStore,
)
from lumirss.ai_summary import SummaryService
from lumirss.ai_translation import TranslationService
from lumirss.ai_translation_segments import (
    SegmentTranslationService,
)
from lumirss.api_source_store import ApiSourceStore
from lumirss.app_settings import (
    AppSettingsStore,
)
from lumirss.backup import (
    BackupEngine,
    BackupJobStore,
    WebDavSettingsStore,
)
from lumirss.config import FreshRSSSettings, LumiSettings
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.favorites import FavoritesService
from lumirss.feed_preview import (
    FeedPreviewService,
)
from lumirss.inbox_store import InboxStore
from lumirss.library import LibraryStore
from lumirss.library_assets import AssetStore
from lumirss.library_clips import ClipStore
from lumirss.mail_bridge import MailBridgeStore
from lumirss.obsidian import ObsidianService
from lumirss.operations import OperationsService
from lumirss.rag import RagService
from lumirss.restore import (
    RestoreService,
)
from lumirss.rsshub import (
    RssHubService,
)
from lumirss.rsshub_control import (
    RssHubControlStore,
    RssHubCustomCredentialStore,
)
from lumirss.search_index import SearchIndexService
from lumirss.search_library import LibrarySearchWriter
from lumirss.secrets_store import SecretsStore
from lumirss.snapshots import SnapshotJobRunner
from lumirss.source_discovery import (
    SourceDiscoveryService,
)
from lumirss.tags import TagStore
from lumirss.workspaces import WorkspaceStore


def _cached_on_app_state(request: Request, attr: str, build):
    """Lazily create and cache one service per (user, attr).

    0067 多账户：服务实例按已验证用户缓存（app.state.user_services），
    其中的 Database 句柄本身也是按请求主体路由的——数据与凭据状态都
    不跨用户。显式注入 app.state.<attr> 的实例（测试替身/部署覆盖）
    仍最优先。缺少身份的调用方每次重建（不缓存、不落到共享实例）。

    Single-user legacy mode (basic) mirrors the instance back onto
    ``app.state.<attr>``: one user ⇒ the historical handle semantics
    (tests and operators read it back) hold unchanged. Session mode
    never mirrors — a second user must not inherit the first one's
    identity-bound instances.
    """
    injected = getattr(request.app.state, attr, None)
    if injected is not None:
        return injected
    scope = getattr(request, "scope", None)  # tests may pass a duck-typed client
    principal = scope.get("lumi_principal") if scope else None
    if principal is None:
        # No verified identity (internal/test calls): historical behavior —
        # one process-wide instance, so injected handles stay shared.
        value = build()
        setattr(request.app.state, attr, value)
        return value
    cache = request.app.state.user_services
    key = (principal["user_id"], attr)
    if key not in cache:
        cache[key] = build()
        if LumiSettings().LUMIRSS_AUTH_MODE != "session":
            setattr(request.app.state, attr, cache[key])
    return cache[key]


def user_env(request: Request):
    """Middleware-loaded identity + FreshRSS binding for this request."""
    env = request.scope.get("lumi_user_env")
    if env is None:
        raise ConfigError("Request has no verified user environment.")
    return env


def _user_secrets(request: Request) -> SecretsStore:
    """Routing secrets store (per-user file under users/<uid>/)."""
    return request.app.state.secrets_store


def _get_adapter(request: Request) -> FreshRSSAdapter:
    """Per-user FreshRSSAdapter from that user's own binding (O154).

    Credentials come from the user's binding row + secrets file — never
    from process env at request time, never from another user's session.
    """
    env = user_env(request)
    return _cached_on_app_state(
        request,
        "freshrss_adapter",
        lambda: _build_user_adapter(request, env),
    )


def _build_user_adapter(request: Request, env):
    """Construct the adapter for one user's binding (sync; binding was
    preloaded by the middleware)."""
    from lumirss.user_scope import require_user_id

    if not (env.freshrss_base_url and env.freshrss_username):
        raise ConfigError(
            "FreshRSS is not bound for this account yet. Finish account "
            "activation (FreshRSS binding) before reading feeds."
        )
    api_password = _user_secrets(request).get("freshrss_api_password") or ""
    if not api_password:
        raise ConfigError("FreshRSS API password is missing for this account.")
    settings = FreshRSSSettings(
        FRESHRSS_BASE_URL=env.freshrss_base_url,
        FRESHRSS_USERNAME=env.freshrss_username,
        FRESHRSS_API_PASSWORD=SecretStr(api_password),
        FRESHRSS_PUBLIC_URL=env.freshrss_public_url,
    )
    require_user_id()  # hard identity gate before any upstream session
    return FreshRSSAdapter(request.app.state.http_client, settings)


def _get_adapter_or_none(request: Request) -> FreshRSSAdapter | None:
    """``_get_adapter`` for optional consumers (search sync, agent tools).

    FreshRSS may be unconfigured (CI, degraded dev); those consumers
    degrade honestly instead of failing. Unconfigured callers reuse the
    SAME cached adapter as the read/control paths — never a second
    session — so login/action-token state stays single-owner."""
    try:
        return _get_adapter(request)
    except ConfigError:
        return None


def _get_control_adapter(request: Request) -> FreshRSSControlAdapter:
    """Control-plane adapter over the SAME session as the read adapter.

    Login / action-token state stays owned by the single FreshRSSAdapter
    instance (which is a FreshRSSSession); the control adapter only borrows
    it, so credentials and tokens are never duplicated.
    """
    return _cached_on_app_state(
        request,
        "freshrss_control_adapter",
        lambda: FreshRSSControlAdapter(_get_adapter(request)),
    )


def _get_preview_service(request: Request) -> FeedPreviewService:
    """Preview service over the SSRF-pinned per-call fetch + control
    adapter.

    Built lazily like the adapters (tests may inject a fake onto
    app.state.feed_preview_service).
    """
    return _cached_on_app_state(
        request,
        "feed_preview_service",
        lambda: FeedPreviewService(_get_control_adapter(request)),
    )


def _preview_json(preview) -> dict[str, object]:
    """One shared preview shape for feed-preview and rsshub/preview."""
    return {
        "title": preview.title,
        "feedUrl": preview.feed_url,
        "siteUrl": preview.site_url,
        "description": preview.description,
        "format": preview.format,
        "alreadySubscribed": preview.already_subscribed,
    }


def _get_discovery_service(request: Request) -> SourceDiscoveryService:
    """SourceDiscoveryService with SSRF-pinned per-call fetch (lazy,
    cached).

    Holds NO FreshRSS reference by design — discovery is read-only against
    the discovered website.
    """
    return _cached_on_app_state(
        request,
        "source_discovery_service",
        lambda: SourceDiscoveryService(),
    )


def _get_rsshub_service(request: Request) -> RssHubService:
    """RssHubService over the shared HTTP client + control adapter.

    Built lazily like the other services; the control adapter is only
    READ (alreadySubscribed) — preview never mutates subscriptions.
    """
    return _cached_on_app_state(
        request,
        "rsshub_service",
        lambda: RssHubService(
            request.app.state.http_client, _get_control_adapter(request)
        ),
    )


def _get_ai_settings_store(request: Request) -> AiSettingsStore:
    """Persistent AI settings store over the Lumi SQLite database (lazy)."""
    return _cached_on_app_state(
        request,
        "ai_settings_store",
        lambda: AiSettingsStore(request.app.state.db),
    )


def _get_ai_profile_store(request: Request) -> AiProfileStore:
    """AI profiles + purpose mapping (lazy)."""
    return _cached_on_app_state(
        request,
        "ai_profile_store",
        lambda: AiProfileStore(
            request.app.state.db, request.app.state.secrets_store
        ),
    )


def _get_secrets_store(request: Request) -> SecretsStore:
    return request.app.state.secrets_store


def _get_segment_service(request: Request) -> SegmentTranslationService:
    """Block-aligned translation (bilingual views); purpose='translation'."""
    return _cached_on_app_state(
        request,
        "segment_translation_service",
        lambda: SegmentTranslationService(
            db=request.app.state.db,
            settings_store=_get_ai_settings_store(request),
            provider_factory=_provider_factory_for(request, "translation"),
            secrets=request.app.state.secrets_store,
        ),
    )


def _get_app_settings_store(request: Request) -> AppSettingsStore:
    """Persistent portable settings store over the Lumi SQLite database."""
    return _cached_on_app_state(
        request,
        "app_settings_store",
        lambda: AppSettingsStore(request.app.state.db),
    )


def _ai_service(request: Request, service_cls, attr: str, purpose: str):
    """Shared wiring for the three AI cached-artifact services."""
    return _cached_on_app_state(
        request,
        attr,
        lambda: service_cls(
            db=request.app.state.db,
            adapter=_get_adapter(request),
            settings_store=_purpose_settings(request, purpose),
            provider_factory=_provider_factory_for(request, purpose),
        ),
    )


def _get_summary_service(request: Request) -> SummaryService:
    """Cached summary service over the shared DB / adapter / settings.

    The purpose-aware settings view + async provider factory resolve the
    mapped profile at generation time (server-side only); reading cache
    state never builds a provider.
    """
    return _ai_service(request, SummaryService, "summary_service", "summary")


def _purpose_settings(request: Request, purpose: str) -> PurposeAiSettings:
    """Purpose-aware view over the global AI settings (profile mapping)."""
    return PurposeAiSettings(
        _get_ai_settings_store(request), _get_ai_profile_store(request), purpose
    )


def _provider_factory_for(request: Request, purpose: str):
    """Async provider factory shared by all AI services (0015 + 0016).

    Resolves the purpose → profile mapping at call time and injects the
    matching API key from the SecretsStore (env ``AI_API_KEY`` stays the
    fallback for the default resolution) — server-side only, never built
    for read-only cache lookups.
    """

    async def factory(base_url: str, model: str):
        effective = await _get_ai_profile_store(request).effective_config(
            purpose,
            await _get_ai_settings_store(request).load(),
            LumiSettings().AI_API_KEY.get_secret_value(),
        )
        from lumirss.ai_provider import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            request.app.state.http_client,
            base_url=effective.base_url or base_url,
            model=effective.model or model,
            api_key=effective.api_key or "",
        )

    return factory


def _get_translation_service(request: Request) -> TranslationService:
    """Cached translation service (0016) — same wiring as summaries."""
    return _ai_service(
        request, TranslationService, "translation_service", "translation"
    )


def _get_conversation_service(request: Request) -> ConversationService:
    """Article-scoped conversation service (0016) — same wiring."""
    return _ai_service(
        request, ConversationService, "conversation_service", "chat"
    )


def _get_operations_service(request: Request) -> OperationsService:
    return _cached_on_app_state(
        request,
        "operations_service",
        lambda: OperationsService(request.app.state.http_client, request.app.state.db),
    )


def _get_rsshub_credentials_store(request: Request) -> RssHubCustomCredentialStore:
    return _cached_on_app_state(
        request,
        "rsshub_credentials_store",
        lambda: RssHubCustomCredentialStore(
            request.app.state.db, request.app.state.secrets_store
        ),
    )


def _get_rsshub_control_store(request: Request) -> RssHubControlStore:
    return _cached_on_app_state(
        request,
        "rsshub_control_store",
        lambda: RssHubControlStore(request.app.state.db, request.app.state.secrets_store),
    )


def _get_backup_jobs(request: Request) -> BackupJobStore:
    return _cached_on_app_state(
        request,
        "backup_jobs",
        lambda: BackupJobStore(request.app.state.db),
    )


def _get_webdav_settings(request: Request) -> WebDavSettingsStore:
    return _cached_on_app_state(
        request,
        "webdav_settings",
        lambda: WebDavSettingsStore(request.app.state.db, request.app.state.secrets_store),
    )


def _get_backup_engine(request: Request) -> BackupEngine:
    def build():
        jobs = _get_backup_jobs(request)
        webdav = _get_webdav_settings(request)

        async def webdav_factory():
            doc = await webdav.load()
            return await webdav.build_client(doc)

        return BackupEngine(request.app.state.db, jobs, webdav, webdav_factory)

    return _cached_on_app_state(request, "backup_engine", build)


def _get_restore_service(request: Request) -> RestoreService:
    def build():
        engine = _get_backup_engine(request)
        return RestoreService(
            request.app.state.db,
            LumiSettings(),
            engine.create_safety_backup,
        )

    return _cached_on_app_state(request, "restore_service", build)


def _get_search_service(request: Request) -> SearchIndexService:
    """Derived search projection over the shared FreshRSS session.

    Built lazily like the other services. FreshRSS may be unconfigured
    (CI, degraded dev): search over an already-built projection still
    works, while sync/rebuild report the missing dependency honestly.
    """

    def build():
        adapter = _get_adapter_or_none(request)
        return SearchIndexService(request.app.state.db, adapter)

    return _cached_on_app_state(request, "search_service", build)


def _get_library_store(request: Request) -> LibraryStore:
    """Library domain store (phase2 M1) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "library_store",
        lambda: LibraryStore(request.app.state.db),
    )


def _get_clip_store(request: Request) -> ClipStore:
    """Web clip store (phase2 M2) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "clip_store",
        lambda: ClipStore(request.app.state.db),
    )


def _get_inbox_store(request: Request) -> InboxStore:
    """Inbox push-source store (0021) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "inbox_store",
        lambda: InboxStore(request.app.state.db),
    )


def _get_snapshot_store(request: Request) -> AssetStore:
    """Snapshot asset store under the per-user data directory (0067)."""

    def build() -> AssetStore:
        principal = request.scope["lumi_principal"]
        root = request.app.state.users_root / principal["user_id"] / "library" / "assets"
        return AssetStore(request.app.state.db, Path(root))

    return _cached_on_app_state(request, "asset_store", build)


def _get_api_source_store(request: Request) -> ApiSourceStore:
    """API source config store (phase2 M3) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "api_source_store",
        lambda: ApiSourceStore(request.app.state.db),
    )


def _get_library_search_writer(request: Request) -> LibrarySearchWriter:
    """Library search projection writer (phase2 G6 unified view)."""
    return _cached_on_app_state(
        request,
        "library_search_writer",
        lambda: LibrarySearchWriter(request.app.state.db),
    )


def _get_obsidian_service(request: Request) -> ObsidianService:
    """Read-only vault projection service (phase2 G6, Gate 4 wiring).

    The env-configured container root (production bind-mount contract)
    is fixed at construction; the DB path is the dev-mode fallback.
    """
    return _cached_on_app_state(
        request,
        "obsidian_service",
        lambda: ObsidianService(
            request.app.state.db,
            env_root=LumiSettings().LUMIRSS_OBSIDIAN_VAULT_DIR,
        ),
    )


def _get_favorites_service(request: Request) -> FavoritesService:
    """Federated favorites (rss star + library favorite) service."""
    return _cached_on_app_state(
        request,
        "favorites_service",
        lambda: FavoritesService(
            request.app.state.db,
            _get_library_search_writer(request),
            # Late-bound Source Registry: resolves favorite refs for the
            # merged view without a wiring cycle.
            lambda: _get_source_registry(request),
        ),
    )


def _get_mail_bridge_store(request: Request) -> MailBridgeStore:
    """Newsletter bridge store (phase2 G5) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "mail_bridge_store",
        lambda: MailBridgeStore(request.app.state.db),
    )


def _get_tag_store(request: Request) -> TagStore:
    """Unified tag store (phase2 G8) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "tag_store",
        lambda: TagStore(request.app.state.db),
    )


def _get_rag_service(request: Request) -> RagService:
    """RAG projection service (phase2 G7) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "rag_service",
        lambda: RagService(request.app.state.db),
    )


async def _rag_mark_stale(request: Request, refs: list[str]) -> None:
    """Best-effort RAG index invalidation after owned-content deletes
    (P0-07e). Only acts when a RAG service instance already exists —
    users who never touch RAG never pay for it; failures never mask the
    delete that triggered them, but they ARE logged (a silently skipped
    invalidation leaves deleted content searchable until the next
    rebuild)."""
    rag: RagService | None = getattr(request.app.state, "rag_service", None)
    if rag is None:
        return
    try:
        # wait=False: a running rebuild must not block deletes for its
        # remaining duration — the orphan sweep converges instead.
        await rag.mark_stale(refs, wait=False)
    except Exception:  # noqa: BLE001 — invalidation is best-effort
        logging.getLogger("lumirss.rag").warning(
            "rag mark_stale failed for %d refs", len(refs), exc_info=True
        )


def _is_owner(request: Request) -> bool:
    """Server-verified owner check (basic mode ⇒ owner by definition)."""
    from lumirss.config import LumiSettings as _LS

    if _LS().LUMIRSS_AUTH_MODE != "session":
        return True
    principal = request.scope.get("lumi_principal")
    return bool(principal and principal.get("role") == "owner")


def _get_agent_store(request: Request) -> AgentStore:
    """Agent threads/messages/approvals store (phase2 G7)."""
    return _cached_on_app_state(
        request,
        "agent_store",
        lambda: AgentStore(request.app.state.db),
    )


def _get_agent_loop(request: Request) -> AgentLoop:
    """Agent loop with the hardcoded tool whitelist on real services."""

    def build() -> AgentLoop:
        adapter = _get_adapter_or_none(request)
        from lumirss.search_library import rss_keyword_search

        async def rss_search(query: str, limit: int = 5):
            return await rss_keyword_search(request.app.state.db, query, limit)

        registry = build_registry(
            db=request.app.state.db,
            rss_search=rss_search,
            library_search=_get_library_search_writer(request),
            rag=_get_rag_service(request),
            adapter=adapter,
            library=_get_library_store(request),
            workspaces=_get_workspace_store(request),
            tags=_get_tag_store(request),
            # O168：Vault 属 owner——member 的 Agent 工具表不注册任何
            # Obsidian 工具（服务端收口，UI 隐藏入口不算权限边界）。
            obsidian=_get_obsidian_service(request)
            if request.app.state.obsidian_service is not None and _is_owner(request)
            else None,
        )

        async def _session_loader(thread_id: str) -> dict:
            from lumirss.agent_session import AgentSessionStore

            settings = await AgentSessionStore(
                request.app.state.db, _get_agent_store(request)
            ).get_settings(thread_id)
            return settings or {}

        return AgentLoop(
            _get_agent_store(request),
            registry,
            lambda: _provider_or_none(request),
            session_loader=_session_loader,
        )

    return _cached_on_app_state(request, "agent_loop", build)


def _get_agent_dry_run(request: Request):
    """F097 写操作预演执行器（与工具注册表同一服务装配；零写入）。"""

    def build():
        from lumirss.agent_tools import build_dry_run

        adapter = _get_adapter_or_none(request)
        return build_dry_run(
            db=request.app.state.db,
            library=_get_library_store(request),
            workspaces=_get_workspace_store(request),
            tags=_get_tag_store(request),
            adapter=adapter,
        )

    return _cached_on_app_state(request, "agent_dry_run", build)


async def _provider_or_none(request: Request):
    """Agent provider factory: None when AI is unconfigured (honest).

    Only the "not configured / not usable config" data states map to
    None. Infrastructure failures (settings DB, secrets store) are
    logged — an outage must not masquerade as a settings gap."""
    try:
        effective = await _get_ai_profile_store(request).effective_config(
            "chat", await _get_ai_settings_store(request).load(), ""
        )
    except Exception:  # noqa: BLE001 — degrade, but leave evidence
        logging.getLogger("lumirss.agent").exception(
            "agent provider lookup failed; treating as unconfigured"
        )
        return None
    if not effective.base_url or not effective.model:
        return None
    from lumirss.ai_provider import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        request.app.state.http_client,
        base_url=effective.base_url,
        model=effective.model,
        api_key=effective.api_key or "",
    )


def _get_snapshot_runner(request: Request) -> SnapshotJobRunner:
    """Serial monolith job runner over the snapshot asset store."""
    return _cached_on_app_state(
        request,
        "snapshot_runner",
        lambda: SnapshotJobRunner(_get_snapshot_store(request)),
    )


def _get_workspace_store(request: Request) -> WorkspaceStore:
    """Workspace store (phase2 M1) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "workspace_store",
        lambda: WorkspaceStore(request.app.state.db),
    )


def _get_source_registry(request: Request) -> dict:
    """Source Registry (phase2 M1): domain → async resolver.

    The rss resolver wraps the shared FreshRSSAdapter read path; the
    library resolver reads Lumi-owned rows. A missing FreshRSS config
    degrades rss resolves to stale views instead of failing workspaces.
    """

    def build() -> dict:
        from lumirss.sources import ResolvedItem, excerpt_of, register_resolver

        registry: dict = {}

        async def resolve_rss(entry_ref: str) -> ResolvedItem | None:
            from lumirss.adapters.freshrss import EntryNotFound

            # Projection-first (quality closure): the derived search
            # projection already holds title/feed/excerpt, so a listing
            # page of rss: refs costs N local point lookups instead of N
            # upstream FreshRSS entry fetches (the read-later timeline's
            # pattern, now shared).
            from lumirss.search_store import SearchStore

            row = await SearchStore(request.app.state.db).entry_row_by_ref(
                entry_ref
            )
            if row is not None:
                return ResolvedItem(
                    ref=f"rss:{entry_ref}",
                    domain="rss",
                    kind="rss",
                    title=str(row["title"]),
                    source=str(row["feed_title"]),
                    datetime=str(row["published_at"]),
                    excerpt=excerpt_of(str(row["content_text"] or "")),
                    url=str(row["url"] or ""),
                    payload={"entryRef": entry_ref},
                )
            adapter = request.app.state.freshrss_adapter
            if adapter is None:
                try:
                    adapter = FreshRSSAdapter(
                        request.app.state.http_client, FreshRSSSettings()
                    )
                    request.app.state.freshrss_adapter = adapter
                except (ConfigError, ValidationError):
                    adapter = None
            if adapter is None:
                # 投影与上游都不可解析（FreshRSS 未配置）→ 确定性 stale
                # 语义：not_found（与适配器 404 路径同因；环境差异不再
                # 让 staleReason 在 None/'unsupported' 间漂移）。
                return ResolvedItem(
                    ref=f"rss:{entry_ref}",
                    domain="rss",
                    kind="rss",
                    title="RSS 未配置",
                    source="rss",
                    stale=True,
                    staleReason="not_found",
                )
            try:
                # The adapter speaks upstream item ids; refs arrive as
                # entryRef envelopes (same contract as GET /entries/{ref}).
                item_id = decode_entry_ref(entry_ref)
                detail = await adapter.get_entry(item_id)
            except (EntryNotFound, InvalidEntryReference):
                return None
            return ResolvedItem(
                ref=f"rss:{entry_ref}",
                domain="rss",
                kind="rss",
                title=detail.title,
                source=detail.feedTitle,
                datetime=detail.publishedAt,
                excerpt=excerpt_of(detail.contentText),
                url=detail.url,
                payload={"entryRef": entry_ref},
            )

        async def resolve_library(item_uuid: str) -> ResolvedItem | None:
            # P0-02: dispatch by the library_items kind to the owning
            # store (ADR 0004 — one registry, kind-aware resolution).
            library = _get_library_store(request)
            kind = await library.get_kind(item_uuid)
            if kind == "bookmark":
                view = await library.get_bookmark(item_uuid)
                if view is None:
                    return None
                return ResolvedItem(
                    ref=view.ref,
                    domain="library",
                    kind="bookmark",
                    title=view.title,
                    source="库",
                    datetime=view.created_at,
                    excerpt=excerpt_of(view.note or view.url),
                    url=view.url,
                    payload=(
                        {"itemType": view.item_type, "rssItemRef": view.rss_item_ref}
                        if view.item_type == "rss"
                        else {"itemType": view.item_type}
                    ),
                )
            if kind == "clip":
                clip = await _get_clip_store(request).get_clip(item_uuid)
                if clip is None:
                    return None
                return ResolvedItem(
                    ref=clip.ref,
                    domain="library",
                    kind="clip",
                    title=clip.title,
                    source="剪藏",
                    datetime=clip.created_at,
                    excerpt=excerpt_of(clip.content_text),
                    url=clip.url,
                    payload={"clipUuid": item_uuid},
                )
            if kind == "snapshot":
                row = await request.app.state.db.fetch_one(
                    "SELECT uuid, mime, bytes, created_at FROM library_assets WHERE item_uuid = ?",
                    (item_uuid,),
                )
                if row is None:
                    return None
                asset_uuid = str(row["uuid"])
                return ResolvedItem(
                    ref=f"library:{item_uuid}",
                    domain="library",
                    kind="snapshot",
                    title=f"快照 · {row['mime']}",
                    source="快照",
                    datetime=str(row["created_at"]),
                    url=None,
                    payload={
                        "assetUuid": asset_uuid,
                        "pageUrl": f"/api/v1/library/assets/{asset_uuid}/page.html",
                    },
                )
            if kind == "obsidian_note":
                note = await _get_obsidian_service(request).get_note(item_uuid)
                if note is None:
                    return None
                return ResolvedItem(
                    ref=f"library:{item_uuid}",
                    domain="library",
                    kind="obsidian_note",
                    title=str(note["title"]),
                    source="Obsidian",
                    datetime=str(note["indexed_at"]),
                    excerpt=excerpt_of(str(note["body_text"] or "")),
                    url=None,
                    payload={"relPath": str(note["rel_path"])},
                )
            if kind == "api_item":
                # 0021: pushed inbox items are Lumi-owned api_item content
                # (ADR 0004) — resolve from the inbox store like any other
                # library kind.
                inbox = await _get_inbox_store(request).get_item(item_uuid)
                if inbox is None:
                    return None
                return ResolvedItem(
                    ref=f"library:{item_uuid}",
                    domain="library",
                    kind="api_item",
                    title=inbox["title"],
                    source=f"Inbox · {inbox['sourceName']}",
                    datetime=inbox["publishedAt"] or inbox["createdAt"],
                    excerpt=excerpt_of(inbox["contentText"]),
                    url=inbox["url"],
                    payload={
                        "inboxUuid": item_uuid,
                        "url": inbox["url"],
                    },
                )
            # newsletter_item has no library-side content: its readable
            # entries live in FreshRSS (ADR 0004), so a dangling ref
            # resolves honestly as missing.
            return None

        register_resolver(registry, "rss", resolve_rss)
        register_resolver(registry, "library", resolve_library)
        return registry

    return _cached_on_app_state(request, "source_registry", build)


