/** Web API 类型 —— 全部派生自 BFF OpenAPI 契约（单一真源）。
 *
 * 契约真源：services/bff 的 Pydantic 模型（app.openapi() →
 * generated/openapi.json → generated/schema.ts）。本文件只提供稳定的
 * 领域命名别名，不再手工维护字段列表/枚举；改契约 = 改 BFF 模型，
 * 然后 `pnpm api:generate`（CI 有 drift 检查）。
 *
 * 例外（尚未进入 OpenAPI 的稳定信封）：
 * - ApiErrorResponse：BFF 异常处理器返回的错误信封；
 * - EntryView / AiPurposeKey：客户端自身的取值联合。
 */

import type { components } from './generated/schema'

type Schemas = components['schemas']

// ---- entries（0003/0004） ----

export type EntryView = 'all' | 'unread' | 'starred'

export type FeedCategory = Schemas['FeedCategory']
export type Category = Schemas['Category']
export type Subscription = Schemas['Subscription']
export type Feed = Schemas['Feed']
export type EntryListItem = Schemas['EntryListItem']
export type EntryListResponse = Schemas['EntryListResponse']
/** contentHtml 是不可信的上游 RSS HTML：BFF 只搬运，sanitize 在渲染前
 * 由 DOMPurify 完成（见 lib/sanitize-article-html.ts）。 */
export type EntryDetail = Schemas['EntryDetail']

export interface ApiErrorResponse {
  error: { type: string; message: string }
}

// ---- 0013 订阅管理 / 预览 / OPML ----

export type FeedPreviewMetadata = Schemas['FeedPreviewResult']
export type OpmlImportPreview = Schemas['OpmlImportPreview']
export type OpmlImportAdded = Schemas['OpmlImportAdded']
export type OpmlImportResult = Schemas['OpmlImportResult']
export type FreshRssUiInfo = Schemas['FreshRssUiInfo']

// ---- 0014 source discovery / RSSHub 目录 ----

export type DiscoveryCandidate = Schemas['DiscoveryCandidate']
export type SourceDiscoveryResponse = Schemas['SourceDiscoveryResponse']
export type RssHubParameter = Schemas['RssHubParameter']
export type RssHubRoute = Schemas['RssHubRoute']
export type RssHubRoutesResponse = Schemas['RssHubCatalog']

// ---- 0015/0016 AI ----

export type AiSettings = Schemas['AiSettingsView']
export type AiPurposeKey = 'summary' | 'translation' | 'chat'
export type AiPurposes = Schemas['AiSettingsView']['purposes']
export type AiPurposeStatus = Schemas['AiPurposeStatus']
export type AiProfile = Schemas['AiProfile']
export type AiSettingsUpdate = Schemas['AiSettingsUpdate']
export type SummaryStatus = Schemas['EntrySummary']['status']
export type EntrySummary = Schemas['EntrySummary']
export type TranslationStatus = Schemas['EntryTranslation']['status']
export type EntryTranslation = Schemas['EntryTranslation']
export type ConversationRole = Schemas['ConversationMessage']['role']
export type ConversationMessage = Schemas['ConversationMessage']
export type EntryConversation = Schemas['EntryConversation']

// ---- 0017 portable 设置 ----

export type ServerSettings = Schemas['AppSettingsView']

/** GET /api/v1/version —— BFF 构建溯源。 */
export type ApiVersion = Schemas['ApiVersionInfo']

// ---- 0018 Operations ----

export type DependencyStatus = Schemas['OperationsComponentStatus']['status']
export type OperationsComponentStatus = Schemas['OperationsComponentStatus']
export type OperationsStatus = Schemas['OperationsStatus']

// ---- 0018 RSSHub Control Center ----

export type RssHubItemType = Schemas['RssHubConfigItem']['type']
export type RssHubConfigItem = Schemas['RssHubConfigItem']
export type RssHubConfigGroup = Schemas['RssHubConfigGroup']
export type RssHubConfig = Schemas['RssHubConfigView']

// ---- 0018 WebDAV / Backup / Restore ----

export type WebDavSettings = Schemas['WebDavSettingsView']
export type WebDavTestResult = Schemas['WebDavTestResult']
export type BackupJobStatus = Schemas['BackupJob']['status']
export type BackupJobType = Schemas['BackupJob']['type']
export type BackupJob = Schemas['BackupJob']
export type RemoteBackup = Schemas['RemoteBackup']
export type RemoteBackupsResponse = Schemas['RemoteBackupsResponse']
export type RestorePreview = Schemas['RestorePreview']
export type RestoreResult = Schemas['RestoreResult']
