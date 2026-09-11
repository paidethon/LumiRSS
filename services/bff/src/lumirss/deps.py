"""Per-request dependency accessors.

Lazily build adapters/stores/services once per app.state so a
request handler never constructs upstream clients directly.
"""



from pathlib import Path

from fastapi import Request
from pydantic import ValidationError

from lumirss.adapters.freshrss import (
    ConfigError,
    FreshRSSAdapter,
)
from lumirss.adapters.freshrss_control import (
    FreshRSSControlAdapter,
)
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
from lumirss.library import LibraryStore
from lumirss.library_assets import AssetStore
from lumirss.library_clips import ClipStore
from lumirss.mail_bridge import MailBridgeStore
from lumirss.obsidian import ObsidianService
from lumirss.operations import OperationsService
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
from lumirss.workspaces import WorkspaceStore


def _cached_on_app_state(request: Request, attr: str, build):
    """Lazily create and cache one service on app.state (single process).

    The app.state attribute starts as None (lifespan); the first request
    builds the service via ``build`` and every later request reuses the
    same instance for the process lifetime. Individual ``_get_*`` accessors
    keep the service wiring visible at their definition site.
    """
    value = getattr(request.app.state, attr)
    if value is None:
        value = build()
        setattr(request.app.state, attr, value)
    return value


def _get_adapter(request: Request) -> FreshRSSAdapter:
    """Lazily create and cache the FreshRSSAdapter on app.state."""
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        try:
            settings = FreshRSSSettings()
        except ValidationError as exc:
            raise ConfigError(
                "FreshRSS settings are missing or invalid. "
                "Set FRESHRSS_BASE_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD."
            ) from exc
        adapter = FreshRSSAdapter(request.app.state.http_client, settings)
        request.app.state.freshrss_adapter = adapter
    return adapter


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
    """Preview service over the shared HTTP client + control adapter.

    Built lazily like the adapters (tests may inject a fake onto
    app.state.feed_preview_service).
    """
    return _cached_on_app_state(
        request,
        "feed_preview_service",
        lambda: FeedPreviewService(
            request.app.state.http_client, _get_control_adapter(request)
        ),
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
    """SourceDiscoveryService over the shared HTTP client (lazy, cached).

    Holds NO FreshRSS reference by design — discovery is read-only against
    the discovered website.
    """
    return _cached_on_app_state(
        request,
        "source_discovery_service",
        lambda: SourceDiscoveryService(request.app.state.http_client),
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
        try:
            adapter = FreshRSSAdapter(
                request.app.state.http_client, FreshRSSSettings()
            )
        except (ConfigError, ValidationError):
            adapter = None
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


def _get_snapshot_store(request: Request) -> AssetStore:
    """Snapshot asset store (phase2 M2) under the Lumi data directory."""

    def build() -> AssetStore:
        settings = LumiSettings()
        return AssetStore(
            request.app.state.db,
            Path(settings.data_dir) / "library" / "assets",
        )

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
    """Read-only vault projection service (phase2 G6)."""
    return _cached_on_app_state(
        request,
        "obsidian_service",
        lambda: ObsidianService(request.app.state.db),
    )


def _get_favorites_service(request: Request) -> FavoritesService:
    """Federated favorites (rss star + library favorite) service."""
    return _cached_on_app_state(
        request,
        "favorites_service",
        lambda: FavoritesService(
            request.app.state.db, _get_library_search_writer(request)
        ),
    )


def _get_mail_bridge_store(request: Request) -> MailBridgeStore:
    """Newsletter bridge store (phase2 G5) over the shared Lumi database."""
    return _cached_on_app_state(
        request,
        "mail_bridge_store",
        lambda: MailBridgeStore(request.app.state.db),
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
                return ResolvedItem(
                    ref=f"rss:{entry_ref}",
                    domain="rss",
                    kind="rss",
                    title="RSS 未配置",
                    source="rss",
                    stale=True,
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
            view = await _get_library_store(request).get_library_item(item_uuid)
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

        register_resolver(registry, "rss", resolve_rss)
        register_resolver(registry, "library", resolve_library)
        return registry

    return _cached_on_app_state(request, "source_registry", build)


