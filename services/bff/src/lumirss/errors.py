"""Stable error envelope: exception-type -> (status, type) mapping.

Every adapter/service error joins one JSON envelope shape via the
table; registration happens once from main.py.
"""



from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from lumirss.adapters.freshrss import (
    AuthenticationError,
    ConfigError,
    EntryNotFound,
    UpstreamConnectionError,
    UpstreamError,
)
from lumirss.adapters.freshrss_control import (
    CategoryLabelConflict,
    CategoryNotFound,
    DefaultCategoryImmutable,
    FeedRejectedError,
    InvalidCategoryLabel,
    InvalidCategoryReference,
    InvalidFeedUrl,
    SubscriptionConflict,
    SubscriptionNotFound,
)
from lumirss.agent import AgentProviderUnavailable
from lumirss.agent_export import ExportInvalid
from lumirss.agent_session import (
    BranchInvalid,
    SearchInvalid,
    ThreadSettingsInvalid,
)
from lumirss.agent_store import (
    ApprovalInvalid,
    NoActiveRun,
    PendingApprovalBlocked,
    ThreadNotFound,
    ToolDenied,
)
from lumirss.agent_tools import DryRunUnsupported
from lumirss.ai_profiles import (
    AiProfileNotFound,
)
from lumirss.ai_provider import (
    AiAuthError,
    AiInvalidResponse,
    AiModelError,
    AiNotConfigured,
    AiRateLimited,
    AiTimeout,
    AiUpstreamError,
)
from lumirss.ai_settings import (
    InvalidAiSettings,
)
from lumirss.ai_summary import AiContentUnavailable
from lumirss.ai_summary_versions import SummaryVersionNotFound
from lumirss.ai_translation_segments import (
    SegmentTranslationUnavailable,
)
from lumirss.api_sources import (
    ApiSourceExpressionError,
    ApiSourceFetchFailed,
    ApiSourceInvalid,
    ApiSourceNotFound,
    ApiSourcePreviewError,
)
from lumirss.app_settings import (
    AppSettingsConflict,
    InvalidAppSettings,
)
from lumirss.auth_store import (
    InvalidCredentials,
    PasswordNotInitialized,
    WeakPassword,
)
from lumirss.author_aggregates import AuthorAliasInvalid, AuthorAliasNotFound
from lumirss.backlog import BacklogConflict
from lumirss.backup import (
    BackupBusy,
    BackupChecksumMismatch,
    BackupFreshrssUnavailable,
    BackupInvalid,
    BackupNotFound,
    BackupUnsupportedVersion,
)
from lumirss.bookmarks_io import NetscapeParseError
from lumirss.clip_fetch import ClipFetchError, ClipForbidden
from lumirss.clip_revision import MustKeepOne, RevisionConflict
from lumirss.cursor import InvalidCursor
from lumirss.entryref import InvalidEntryReference
from lumirss.favorites import FavoriteInvalid
from lumirss.feed_preview import (
    FeedFetchError,
    FeedTooLarge,
    NotAFeedError,
    UnsafeFeedUrl,
)
from lumirss.glossary import GlossaryInvalid, GlossaryNotFound
from lumirss.inbox_rules import InboxRuleInvalid, InboxRuleNotFound
from lumirss.inbox_store import (
    InboxItemNotFound,
    InboxSourceNotFound,
    InvalidInboxPayload,
)
from lumirss.item_relations import (
    RelationDuplicate,
    RelationInvalid,
    RelationNotFound,
)
from lumirss.itemref import InvalidItemRef
from lumirss.library import (
    BookmarkInvalid,
    BookmarkNotFound,
)
from lumirss.library_assets import AssetNotFound, AssetQuotaExceeded, AssetTooLarge
from lumirss.library_batch_edit import BatchEditInvalid
from lumirss.library_clips import ClipInvalid, ClipNotFound
from lumirss.library_merge import MergedAlready, MergeInvalid
from lumirss.lumi_notes_lifecycle import (
    NoteConflict,
    NoteInvalid,
)
from lumirss.lumi_notes_lifecycle import (
    NoteNotFound as LumiNoteNotFound,
)
from lumirss.mail_bridge import (
    MailBridgeInvalid,
    MailBridgeNotFound,
)
from lumirss.mail_digest import (
    SmtpNotConfigured,
    SmtpSendFailed,
)
from lumirss.mail_imap import ImapNotConfigured
from lumirss.middleware import RequestBodyTooLarge
from lumirss.mute_windows import MuteWindowsInvalid
from lumirss.obsidian import (
    NoteNotFound,
    VaultPermissionDenied,
    VaultRootLocked,
    VaultUnreachable,
)
from lumirss.obsidian_devices import (
    DeviceProfileInvalid,
    DeviceProfileNotFound,
)
from lumirss.obsidian_template import TemplateTooLong
from lumirss.obsidian_uri import ObsidianUriInvalid
from lumirss.opml import (
    OpmlInvalid,
    OpmlTooLarge,
    OpmlTooManyFeeds,
)
from lumirss.qa_templates import QaTemplateInvalid, QaTemplateNotFound
from lumirss.rag import RagModelUnavailable, RagRebuildBusy
from lumirss.reading_queue import (
    QueueInvalid,
    QueueItemDone,
    QueueItemNotFound,
    QueueSnapshotLimit,
    QueueSnapshotNotFound,
)
from lumirss.research_pack_zip import ZipInvalid, ZipTooLarge
from lumirss.restore import (
    RestoreConfirmationRequired,
    RestoreFailed,
    RestorePreviewRequired,
)
from lumirss.rsshub import (
    RssHubFavoriteNotFound,
    RssHubFetchError,
    RssHubInvalidParameters,
    RssHubNotConfigured,
    RssHubRefreshRateLimited,
    RssHubRouteNotFound,
)
from lumirss.rsshub_control import (
    RssHubControlError,
    RssHubCustomCredentialError,
    RssHubInvalidValue,
    RssHubUnknownKey,
)
from lumirss.saved_search_store import (
    SavedSearchInvalid,
    SavedSearchLimit,
    SavedSearchNotFound,
)
from lumirss.search_debug import SearchEntryNotFound
from lumirss.search_index import SearchQueryError
from lumirss.secrets_store import SecretsStoreError
from lumirss.snapshots import MonolithUnavailable, SnapshotFailed
from lumirss.source_aliases import SourceAliasInvalid, SourceAliasNotFound
from lumirss.source_discovery import (
    InvalidSourceUrl,
    NoFeedDiscovered,
)
from lumirss.sources import ItemRefUnresolvable
from lumirss.subscriptionref import (
    InvalidSubscriptionReference,
)
from lumirss.tags import TagInvalid, TagNotFound
from lumirss.webdav import WebDavError, WebDavInvalidSettings, WebDavNotConfigured
from lumirss.workspace_archive import (
    ArchivedWorkspace,
    ProtectedWorkspace,
)
from lumirss.workspace_board import BoardInvalid, BoardItemNotFound
from lumirss.workspace_cleanup import CleanupInvalid, CleanupLogNotFound
from lumirss.workspace_goals import GoalInvalid
from lumirss.workspace_sections import (
    SectionInvalid,
    SectionItemNotFound,
    SectionNotFound,
)
from lumirss.workspace_snapshots import WorkspaceSnapshotNotFound
from lumirss.workspace_templates import (
    TemplateExists,
    TemplateInvalid,
    TemplateNotFound,
)
from lumirss.workspaces import (
    ReservedWorkspaceError,
    WorkspaceInvalid,
    WorkspaceItemPinned,
    WorkspaceNotFound,
    WorkspaceRevisionConflict,
)

_ERROR_RESPONSES = {
    ConfigError: (503, "configuration_error"),
    AuthenticationError: (502, "authentication_error"),
    UpstreamConnectionError: (502, "connection_error"),
    UpstreamError: (502, "upstream_error"),
    InvalidEntryReference: (400, "invalid_entry_reference"),
    # F21 个人术语本
    GlossaryInvalid: (400, "invalid_glossary"),
    GlossaryNotFound: (404, "glossary_not_found"),
    EntryNotFound: (404, "entry_not_found"),
    InvalidCursor: (400, "invalid_cursor"),
    # 0013 control plane
    InvalidSubscriptionReference: (400, "invalid_subscription_reference"),
    InvalidFeedUrl: (400, "invalid_feed_url"),
    FeedRejectedError: (400, "feed_rejected"),
    SubscriptionConflict: (409, "subscription_conflict"),
    SubscriptionNotFound: (404, "subscription_not_found"),
    InvalidCategoryReference: (400, "invalid_category_reference"),
    InvalidCategoryLabel: (400, "invalid_category_label"),
    CategoryNotFound: (404, "category_not_found"),
    CategoryLabelConflict: (409, "category_label_conflict"),
    DefaultCategoryImmutable: (409, "default_category_immutable"),
    # 0013 Gate 2 preview
    UnsafeFeedUrl: (400, "unsafe_feed_url"),
    FeedFetchError: (502, "feed_fetch_error"),
    FeedTooLarge: (413, "feed_too_large"),
    NotAFeedError: (400, "not_a_feed"),
    # 0013 Gate 4 OPML
    OpmlInvalid: (400, "opml_invalid"),
    OpmlTooLarge: (413, "opml_too_large"),
    OpmlTooManyFeeds: (400, "opml_too_many_feeds"),
    # 0014 source discovery
    InvalidSourceUrl: (400, "invalid_source_url"),
    NoFeedDiscovered: (404, "no_feed_discovered"),
    # 0014 RSSHub
    RssHubNotConfigured: (503, "rsshub_not_configured"),
    RssHubRouteNotFound: (404, "rsshub_route_not_found"),
    RssHubInvalidParameters: (400, "rsshub_invalid_parameters"),
    RssHubFetchError: (502, "rsshub_fetch_error"),
    # N021 route favorites
    RssHubFavoriteNotFound: (404, "rsshub_favorite_not_found"),
    # 0015 AI settings
    InvalidAiSettings: (400, "invalid_ai_settings"),
    AiProfileNotFound: (404, "ai_profile_not_found"),
    # 0017 portable app settings
    InvalidAppSettings: (400, "invalid_app_settings"),
    # 0021 multi-device settings conflicts
    AppSettingsConflict: (409, "app_settings_conflict"),
    # 0015 AI summary
    AiNotConfigured: (503, "ai_not_configured"),
    SegmentTranslationUnavailable: (400, "translation_unavailable"),
    RssHubCustomCredentialError: (400, "rsshub_invalid_value"),
    AiAuthError: (502, "ai_auth_error"),
    AiModelError: (502, "ai_model_error"),
    AiRateLimited: (429, "ai_rate_limited"),
    AiTimeout: (504, "ai_timeout"),
    AiInvalidResponse: (502, "ai_invalid_response"),
    AiUpstreamError: (502, "ai_upstream_error"),
    AiContentUnavailable: (422, "ai_content_unavailable"),
    # 0018 RSSHub control（spec 稳定错误类型：unknown_key / invalid_value）
    RssHubControlError: (400, "rsshub_invalid_value"),
    RssHubUnknownKey: (400, "rsshub_unknown_key"),
    RssHubInvalidValue: (400, "rsshub_invalid_value"),
    # 0018 backup / WebDAV / restore
    BackupBusy: (409, "backup_busy"),
    BackupNotFound: (404, "backup_not_found"),
    BackupInvalid: (400, "backup_invalid"),
    BackupChecksumMismatch: (400, "backup_checksum_mismatch"),
    BackupUnsupportedVersion: (409, "backup_unsupported_version"),
    BackupFreshrssUnavailable: (503, "backup_freshrss_unavailable"),
    WebDavNotConfigured: (503, "webdav_not_configured"),
    WebDavInvalidSettings: (400, "webdav_invalid_settings"),
    WebDavError: (502, "webdav_error"),
    RestoreConfirmationRequired: (400, "backup_restore_confirmation_required"),
    RestorePreviewRequired: (400, "backup_restore_preview_required"),
    RestoreFailed: (500, "restore_failed"),
    SecretsStoreError: (500, "secret_store_error"),
    # 0021 global body cap
    RequestBodyTooLarge: (413, "request_too_large"),
    # 0022 global search
    SearchQueryError: (400, "invalid_search_query"),
    # N143 why-missed：ref 不在本用户作用域（含他人条目 → 不泄露存在性）
    SearchEntryNotFound: (404, "search_entry_not_found"),
    # session authentication (LUMIRSS_AUTH_MODE=session)
    InvalidCredentials: (401, "invalid_credentials"),
    PasswordNotInitialized: (503, "auth_not_initialized"),
    WeakPassword: (400, "weak_password"),
    # phase2 M1 library domain
    NetscapeParseError: (400, "bookmarks_import_invalid"),
    BookmarkInvalid: (400, "invalid_bookmark"),
    BookmarkNotFound: (404, "bookmark_not_found"),
    InvalidItemRef: (400, "invalid_item_ref"),
    ItemRefUnresolvable: (422, "item_ref_unresolvable"),
    FavoriteInvalid: (400, "invalid_favorite"),
    WorkspaceInvalid: (400, "invalid_workspace"),
    WorkspaceNotFound: (404, "workspace_not_found"),
    ReservedWorkspaceError: (409, "reserved_workspace"),
    # P15（响应体额外带 currentRevision —— 见专用 handler）
    WorkspaceRevisionConflict: (409, "workspace_revision_conflict"),
    # N102：固定条目拒绝静默移除（force=1 才放行）
    WorkspaceItemPinned: (409, "workspace_item_pinned"),
    # N105：快照不存在（不跨工作区取快照）
    WorkspaceSnapshotNotFound: (404, "workspace_snapshot_not_found"),
    # N113 分节大纲
    SectionInvalid: (422, "invalid_workspace_section"),
    SectionNotFound: (404, "workspace_section_not_found"),
    SectionItemNotFound: (404, "workspace_section_item_not_found"),
    # N120 清理预演
    CleanupInvalid: (422, "invalid_workspace_cleanup"),
    CleanupLogNotFound: (404, "workspace_cleanup_log_not_found"),
    # N041/N042/N043：今日必读队列（稳定错误信封）
    QueueInvalid: (400, "invalid_queue"),
    QueueItemNotFound: (404, "queue_item_not_found"),
    QueueItemDone: (409, "queue_item_done"),
    QueueSnapshotNotFound: (404, "queue_snapshot_not_found"),
    QueueSnapshotLimit: (400, "queue_snapshot_limit"),
    # phase2 M2 clips + snapshots
    ClipFetchError: (502, "clip_fetch_failed"),
    ClipForbidden: (400, "clip_fetch_forbidden"),
    ClipInvalid: (400, "invalid_clip"),
    ClipNotFound: (404, "clip_not_found"),
    AssetNotFound: (404, "asset_not_found"),
    AssetQuotaExceeded: (413, "quota_exceeded"),
    AssetTooLarge: (413, "snapshot_too_large"),
    MonolithUnavailable: (503, "monolith_unavailable"),
    SnapshotFailed: (502, "snapshot_failed"),
    # phase2 M3 api sources
    ApiSourceInvalid: (400, "invalid_api_source"),
    ApiSourceNotFound: (404, "api_source_not_found"),
    ApiSourceExpressionError: (400, "invalid_expression"),
    ApiSourcePreviewError: (422, "preview_expression_failed"),
    ApiSourceFetchFailed: (502, "fetch_failed"),
    # phase2 G5 mail
    MailBridgeInvalid: (400, "invalid_mail_payload"),
    MailBridgeNotFound: (404, "mail_list_not_found"),
    SmtpNotConfigured: (503, "smtp_not_configured"),
    SmtpSendFailed: (502, "smtp_send_failed"),
    ImapNotConfigured: (503, "imap_not_configured"),
    # phase2 G6 obsidian
    VaultUnreachable: (503, "vault_unreachable"),
    VaultPermissionDenied: (403, "vault_permission_denied"),
    NoteNotFound: (404, "note_not_found"),
    VaultRootLocked: (409, "vault_root_locked"),
    # P16 obsidian devices / export handoff
    DeviceProfileInvalid: (422, "invalid_device_profile"),
    DeviceProfileNotFound: (404, "device_profile_not_found"),
    ObsidianUriInvalid: (422, "invalid_obsidian_uri"),
    TemplateTooLong: (422, "template_too_long"),
    # phase2 G7 rag + agent
    RagModelUnavailable: (503, "model_unavailable"),
    RagRebuildBusy: (409, "rebuild_in_progress"),
    AgentProviderUnavailable: (503, "provider_unavailable"),
    ToolDenied: (403, "tool_denied"),
    ApprovalInvalid: (409, "approval_invalid"),
    # phase2 G8 tags
    TagInvalid: (400, "invalid_tag"),
    TagNotFound: (404, "tag_not_found"),
    # pool #09 saved search views
    SavedSearchInvalid: (400, "invalid_saved_search"),
    SavedSearchNotFound: (404, "saved_search_not_found"),
    SavedSearchLimit: (409, "saved_search_limit"),
    # phase2 recovery P0-08 (agent run lifecycle)
    ThreadNotFound: (404, "thread_not_found"),
    PendingApprovalBlocked: (409, "pending_approval"),
    NoActiveRun: (409, "no_active_run"),
    # 0021 inbox push sources
    InvalidInboxPayload: (400, "invalid_inbox_payload"),
    InboxSourceNotFound: (404, "inbox_source_not_found"),
    InboxItemNotFound: (404, "inbox_item_not_found"),
    # F021 手工关联内容
    RelationInvalid: (422, "invalid_relation"),
    RelationDuplicate: (409, "relation_duplicate"),
    RelationNotFound: (404, "relation_not_found"),
    # F022 收件箱归类规则
    InboxRuleNotFound: (404, "inbox_rule_not_found"),
    InboxRuleInvalid: (422, "invalid_inbox_rule"),
    # F023 作者聚合别名
    AuthorAliasInvalid: (422, "invalid_author_alias"),
    AuthorAliasNotFound: (404, "author_alias_not_found"),
    # F024 积压整理助手
    BacklogConflict: (409, "backlog_conflict"),
    # F027 摘要版本
    SummaryVersionNotFound: (404, "summary_version_not_found"),
    # F030 问答模板
    QaTemplateNotFound: (404, "qa_template_not_found"),
    QaTemplateInvalid: (422, "invalid_qa_template"),
    # N013 来源别名 + 改名历史
    SourceAliasInvalid: (422, "invalid_source_alias"),
    SourceAliasNotFound: (404, "source_alias_not_found"),
    # N015 来源分时静音窗口
    MuteWindowsInvalid: (422, "invalid_mute_windows"),
    # W5: F081–F100
    BatchEditInvalid: (422, "invalid_batch_edit"),
    MergeInvalid: (422, "invalid_merge"),
    MergedAlready: (409, "merged_already"),
    TemplateInvalid: (422, "invalid_template"),
    TemplateExists: (409, "template_exists"),
    TemplateNotFound: (404, "template_not_found"),
    ProtectedWorkspace: (409, "protected_workspace"),
    ArchivedWorkspace: (409, "archived_workspace"),
    BoardInvalid: (422, "invalid_board_status"),
    BoardItemNotFound: (404, "board_item_not_found"),
    GoalInvalid: (422, "invalid_goal"),
    RevisionConflict: (409, "base_mismatch"),
    MustKeepOne: (422, "must_keep_one"),
    NoteInvalid: (422, "invalid_note"),
    NoteConflict: (409, "note_conflict"),
    LumiNoteNotFound: (404, "note_not_found"),
    SearchInvalid: (422, "invalid_search_query"),
    ThreadSettingsInvalid: (422, "invalid_thread_settings"),
    BranchInvalid: (422, "invalid_branch_request"),
    ExportInvalid: (422, "invalid_export_request"),
    DryRunUnsupported: (422, "dry_run_unsupported"),
    ZipInvalid: (422, "invalid_research_pack_request"),
    ZipTooLarge: (413, "research_pack_too_large"),
}


def register_error_handlers(app) -> None:
    """Attach the stable-envelope handlers to the app (called once from main.py)."""
    @app.exception_handler(ConfigError)
    @app.exception_handler(AuthenticationError)
    @app.exception_handler(UpstreamConnectionError)
    @app.exception_handler(UpstreamError)
    @app.exception_handler(InvalidEntryReference)
    @app.exception_handler(EntryNotFound)
    @app.exception_handler(InvalidCursor)
    @app.exception_handler(GlossaryInvalid)
    @app.exception_handler(GlossaryNotFound)
    @app.exception_handler(InvalidSubscriptionReference)
    @app.exception_handler(InvalidFeedUrl)
    @app.exception_handler(FeedRejectedError)
    @app.exception_handler(SubscriptionConflict)
    @app.exception_handler(SubscriptionNotFound)
    @app.exception_handler(InvalidCategoryReference)
    @app.exception_handler(InvalidCategoryLabel)
    @app.exception_handler(CategoryNotFound)
    @app.exception_handler(CategoryLabelConflict)
    @app.exception_handler(DefaultCategoryImmutable)
    @app.exception_handler(UnsafeFeedUrl)
    @app.exception_handler(FeedFetchError)
    @app.exception_handler(FeedTooLarge)
    @app.exception_handler(NotAFeedError)
    @app.exception_handler(OpmlInvalid)
    @app.exception_handler(OpmlTooLarge)
    @app.exception_handler(OpmlTooManyFeeds)
    @app.exception_handler(InvalidSourceUrl)
    @app.exception_handler(NoFeedDiscovered)
    @app.exception_handler(RssHubNotConfigured)
    @app.exception_handler(RssHubRouteNotFound)
    @app.exception_handler(RssHubInvalidParameters)
    @app.exception_handler(RssHubFavoriteNotFound)
    @app.exception_handler(InvalidAppSettings)
    @app.exception_handler(AppSettingsConflict)
    @app.exception_handler(InvalidAiSettings)
    @app.exception_handler(AiProfileNotFound)
    @app.exception_handler(AiNotConfigured)
    @app.exception_handler(AiAuthError)
    @app.exception_handler(AiModelError)
    @app.exception_handler(AiRateLimited)
    @app.exception_handler(AiTimeout)
    @app.exception_handler(AiInvalidResponse)
    @app.exception_handler(AiUpstreamError)
    @app.exception_handler(AiContentUnavailable)
    @app.exception_handler(RssHubControlError)
    @app.exception_handler(RssHubUnknownKey)
    @app.exception_handler(RssHubInvalidValue)
    @app.exception_handler(BackupBusy)
    @app.exception_handler(BackupNotFound)
    @app.exception_handler(BackupInvalid)
    @app.exception_handler(BackupChecksumMismatch)
    @app.exception_handler(BackupUnsupportedVersion)
    @app.exception_handler(BackupFreshrssUnavailable)
    @app.exception_handler(WebDavNotConfigured)
    @app.exception_handler(WebDavInvalidSettings)
    @app.exception_handler(WebDavError)
    @app.exception_handler(RestoreConfirmationRequired)
    @app.exception_handler(RestorePreviewRequired)
    @app.exception_handler(RestoreFailed)
    @app.exception_handler(SecretsStoreError)
    @app.exception_handler(RequestBodyTooLarge)
    @app.exception_handler(SearchQueryError)
    @app.exception_handler(SearchEntryNotFound)
    @app.exception_handler(InvalidCredentials)
    @app.exception_handler(PasswordNotInitialized)
    @app.exception_handler(WeakPassword)
    @app.exception_handler(NetscapeParseError)
    @app.exception_handler(BookmarkInvalid)
    @app.exception_handler(BookmarkNotFound)
    @app.exception_handler(InvalidItemRef)
    @app.exception_handler(ItemRefUnresolvable)
    @app.exception_handler(FavoriteInvalid)
    @app.exception_handler(WorkspaceInvalid)
    @app.exception_handler(WorkspaceNotFound)
    @app.exception_handler(ReservedWorkspaceError)
    @app.exception_handler(ClipFetchError)
    @app.exception_handler(ClipForbidden)
    @app.exception_handler(ClipInvalid)
    @app.exception_handler(ClipNotFound)
    @app.exception_handler(AssetNotFound)
    @app.exception_handler(AssetQuotaExceeded)
    @app.exception_handler(AssetTooLarge)
    @app.exception_handler(MonolithUnavailable)
    @app.exception_handler(SnapshotFailed)
    @app.exception_handler(ApiSourceInvalid)
    @app.exception_handler(ApiSourceNotFound)
    @app.exception_handler(ApiSourceExpressionError)
    @app.exception_handler(ApiSourceFetchFailed)
    @app.exception_handler(MailBridgeInvalid)
    @app.exception_handler(MailBridgeNotFound)
    @app.exception_handler(SmtpNotConfigured)
    @app.exception_handler(SmtpSendFailed)
    @app.exception_handler(ImapNotConfigured)
    @app.exception_handler(VaultUnreachable)
    @app.exception_handler(VaultPermissionDenied)
    @app.exception_handler(NoteNotFound)
    @app.exception_handler(VaultRootLocked)
    @app.exception_handler(DeviceProfileInvalid)
    @app.exception_handler(DeviceProfileNotFound)
    @app.exception_handler(ObsidianUriInvalid)
    @app.exception_handler(TemplateTooLong)
    @app.exception_handler(RagModelUnavailable)
    @app.exception_handler(RagRebuildBusy)
    @app.exception_handler(AgentProviderUnavailable)
    @app.exception_handler(ToolDenied)
    @app.exception_handler(ApprovalInvalid)
    @app.exception_handler(TagInvalid)
    @app.exception_handler(TagNotFound)
    @app.exception_handler(SavedSearchInvalid)
    @app.exception_handler(SavedSearchNotFound)
    @app.exception_handler(SavedSearchLimit)
    @app.exception_handler(ThreadNotFound)
    @app.exception_handler(PendingApprovalBlocked)
    @app.exception_handler(NoActiveRun)
    @app.exception_handler(InvalidInboxPayload)
    @app.exception_handler(InboxSourceNotFound)
    @app.exception_handler(InboxItemNotFound)
    @app.exception_handler(RelationInvalid)
    @app.exception_handler(RelationDuplicate)
    @app.exception_handler(RelationNotFound)
    @app.exception_handler(InboxRuleNotFound)
    @app.exception_handler(InboxRuleInvalid)
    @app.exception_handler(AuthorAliasInvalid)
    @app.exception_handler(AuthorAliasNotFound)
    @app.exception_handler(BacklogConflict)
    @app.exception_handler(SummaryVersionNotFound)
    @app.exception_handler(QaTemplateNotFound)
    @app.exception_handler(QaTemplateInvalid)
    @app.exception_handler(SourceAliasInvalid)
    @app.exception_handler(SourceAliasNotFound)
    @app.exception_handler(MuteWindowsInvalid)
    # W5: F081–F100
    @app.exception_handler(BatchEditInvalid)
    @app.exception_handler(MergeInvalid)
    @app.exception_handler(MergedAlready)
    @app.exception_handler(TemplateInvalid)
    @app.exception_handler(TemplateExists)
    @app.exception_handler(TemplateNotFound)
    @app.exception_handler(ProtectedWorkspace)
    @app.exception_handler(ArchivedWorkspace)
    @app.exception_handler(BoardInvalid)
    @app.exception_handler(BoardItemNotFound)
    @app.exception_handler(GoalInvalid)
    @app.exception_handler(RevisionConflict)
    @app.exception_handler(MustKeepOne)
    @app.exception_handler(NoteInvalid)
    @app.exception_handler(NoteConflict)
    @app.exception_handler(LumiNoteNotFound)
    @app.exception_handler(SearchInvalid)
    @app.exception_handler(ThreadSettingsInvalid)
    @app.exception_handler(BranchInvalid)
    @app.exception_handler(ExportInvalid)
    @app.exception_handler(DryRunUnsupported)
    @app.exception_handler(ZipInvalid)
    @app.exception_handler(ZipTooLarge)
    @app.exception_handler(WorkspaceItemPinned)
    @app.exception_handler(WorkspaceSnapshotNotFound)
    @app.exception_handler(SectionInvalid)
    @app.exception_handler(SectionNotFound)
    @app.exception_handler(SectionItemNotFound)
    @app.exception_handler(CleanupInvalid)
    @app.exception_handler(CleanupLogNotFound)
    @app.exception_handler(QueueInvalid)
    @app.exception_handler(QueueItemNotFound)
    @app.exception_handler(QueueItemDone)
    @app.exception_handler(QueueSnapshotNotFound)
    @app.exception_handler(QueueSnapshotLimit)
    async def adapter_error_handler(request: Request, exc: Exception) -> JSONResponse:
        status, error_type = _ERROR_RESPONSES[type(exc)]
        return JSONResponse(
            status_code=status,
            content={"error": {"type": error_type, "message": str(exc)}},
        )

    @app.exception_handler(WorkspaceRevisionConflict)
    async def workspace_revision_conflict_handler(
        request: Request, exc: WorkspaceRevisionConflict
    ) -> JSONResponse:
        """P15：409 冲突体额外携带 currentRevision——客户端不解析也能
        重取；解析后可直接用它重试（省一次 detail 往返）。"""
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "workspace_revision_conflict",
                    "message": str(exc),
                    "currentRevision": exc.current_revision,
                }
            },
        )

    @app.exception_handler(RssHubFetchError)
    async def rsshub_fetch_error_handler(
        request: Request, exc: RssHubFetchError
    ) -> JSONResponse:
        """N026：502 rsshub_fetch_error 稳定类型不变，额外携带
        failureClass（rsshub_unreachable / upstream_reject / auth_failure
        / not_found / rate_limited / network_error）——路由健康时间线与
        Web 文案据此分辨故障，不再全部坍缩成网络错误。"""
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "type": "rsshub_fetch_error",
                    "message": str(exc),
                    "failureClass": exc.failure_class,
                }
            },
        )

    @app.exception_handler(RssHubRefreshRateLimited)
    async def rsshub_refresh_rate_limited_handler(
        request: Request, exc: RssHubRefreshRateLimited
    ) -> JSONResponse:
        """N027：刷新限速 → 429 + Retry-After 秒（稳定错误类型
        rsshub_refresh_rate_limited；响应体同时带 retryAfterSeconds）。"""
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after_s)},
            content={
                "error": {
                    "type": "rsshub_refresh_rate_limited",
                    "message": str(exc),
                    "retryAfterSeconds": exc.retry_after_s,
                }
            },
        )


    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Pydantic validation failures join the stable error envelope.

        Keeps the 422 status (existing contract) but never echoes request
        details back — the message is a static string."""
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_request",
                    "message": "The request body failed validation.",
                }
            },
        )
