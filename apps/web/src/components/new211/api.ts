/** NEW-211..220 组内 API 访问（自包含；不进共享 client.ts）。
 *
 * 与 client.ts 同契约：只打相对 /api/v1/*，稳定错误信封
 * {error: {type, message, ...}} 转为 ApiError 形状的 Error（带 type）。 */

const API_BASE = '/api/v1'

export class ApiError extends Error {
  readonly type: string
  readonly status: number
  readonly extra: Record<string, unknown>

  constructor(status: number, type: string, message: string, extra: Record<string, unknown> = {}) {
    super(message)
    this.type = type
    this.status = status
    this.extra = extra
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body != null ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!response.ok) {
    let type = 'unknown_error'
    let message = `请求失败（${response.status}）`
    let extra: Record<string, unknown> = {}
    try {
      const body = (await response.json()) as { error?: { type?: string; message?: string } & Record<string, unknown> }
      if (body.error) {
        type = body.error.type ?? type
        message = body.error.message ?? message
        extra = body.error
      }
    } catch {
      // 非 JSON 错误体：保留状态码信息
    }
    throw new ApiError(response.status, type, message, extra)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const del = (path: string) => request<void>(path, { method: 'DELETE' })

// ---- NEW-211 合并向导 -------------------------------------------------------

export interface TagSummary {
  id: number
  name: string
  count: number
}
export interface MergeWizardSourcePreview {
  tagId: number
  name: string
  bindings: number
  overlaps: number
  willMove: number
}
export interface MergeWizardPreview {
  target: { tagId: number; name: string }
  sources: MergeWizardSourcePreview[]
  affectedArticles: number
  references: { synonyms: number; groupMemberships: number }
}
export interface MergeWizardApplyResult {
  logId: string
  targetName: string
  mergedSources: { tagId: number; name: string; bindings: number }[]
  synonymsSynced: number
  groupMembershipsReleased: number
}
export interface MergeWizardLog {
  logId: string
  targetName: string
  sources: { tagId: number; name: string; bindings: number }[]
  createdAt: string
}

export const listTags = () => request<{ items: TagSummary[] }>('/tags')
export const mergeWizardPreview = (sourceIds: number[], targetId: number) =>
  post<MergeWizardPreview>('/tags/merge-wizard/preview', { sourceIds, targetId })
export const mergeWizardApply = (sourceIds: number[], targetId: number) =>
  post<MergeWizardApplyResult>('/tags/merge-wizard/apply', { sourceIds, targetId })
export const mergeWizardLogs = () => request<{ items: MergeWizardLog[] }>('/tags/merge-wizard/logs')
export const mergeWizardUndo = (logId: string) =>
  post<{ undoneLogId: string }>(`/tags/merge-wizard/logs/${encodeURIComponent(logId)}/undo`)

// ---- NEW-212 改名影响图 -----------------------------------------------------

export interface RenameImpact {
  tagId: number
  oldName: string
  newName: string
  willRewrite: { kind: string; id: number; alias: string; canonicalFrom: string; canonicalTo: string }[]
  autoFollow: { kind: string; id: number | string; name?: string }[]
  bindings: number
}
export interface RenameSyncResult {
  tagId: number
  oldName: string
  newName: string
  synonymsRewritten: number
  bindingsFollowed: number
}
export const renameImpact = (tagId: number, newName: string) =>
  post<RenameImpact>('/tags/rename-impact', { tagId, newName })
export const renameWithSync = (tagId: number, newName: string) =>
  post<RenameSyncResult>('/tags/rename-with-sync', { tagId, newName })

// ---- NEW-213 互斥组 ----------------------------------------------------------

export interface TagGroup {
  id: number
  name: string
  members: { tagId: number; name: string }[]
}
export interface TagGroupConflicts {
  groupId: number
  items: { ref: string; tags: { tagId: number; name: string }[] }[]
  truncated: boolean
}
export const listTagGroups = () => request<{ items: TagGroup[] }>('/tag-groups')
export const createTagGroup = (name: string, members: string[]) =>
  post<TagGroup>('/tag-groups', { name, members })
export const deleteTagGroup = (groupId: number) => del(`/tag-groups/${groupId}`)
export const tagGroupConflicts = (groupId: number) =>
  request<TagGroupConflicts>(`/tag-groups/${groupId}/conflicts`)
export const resolveTagGroup = (
  groupId: number,
  resolutions: { ref: string; keep: string }[],
) => post<{ groupId: number; resolved: { ref: string; kept: string; removed: string[] }[] }>(
  `/tag-groups/${groupId}/resolve`,
  { resolutions },
)

// ---- NEW-214 同义词 ----------------------------------------------------------

export interface TagSynonym {
  id: number
  alias: string
  canonical: string
}
export interface TagSynonymResolve {
  input: string
  exact: boolean
  canonical: string | null
  suggestions: string[]
}
export const listTagSynonyms = () => request<{ items: TagSynonym[] }>('/tag-synonyms')
export const createTagSynonym = (alias: string, canonical: string) =>
  post<TagSynonym>('/tag-synonyms', { alias, canonical })
export const deleteTagSynonym = (id: number) => del(`/tag-synonyms/${id}`)
export const resolveTagSynonym = (q: string) =>
  request<TagSynonymResolve>(`/tag-synonyms/resolve?q=${encodeURIComponent(q)}`)

// ---- NEW-215 清理台 ----------------------------------------------------------

export interface TagCleanupEntry {
  tagId: number
  name: string
  bindings: number
  references: { synonyms: number; groupMemberships: number; mergeLogs: number }
}
export interface TagCleanupReport {
  buckets: { unused: TagCleanupEntry[]; referencedOnly: TagCleanupEntry[]; inUse: TagCleanupEntry[] }
}
export interface TagCleanupDeleteResult {
  deleted: { tagId: number; name: string; deletedBindings: number }[]
}
export const tagCleanupReport = () => request<TagCleanupReport>('/tags/cleanup/report')
export const tagCleanupDelete = (tagIds: number[], acknowledgeReferences = false) =>
  post<TagCleanupDeleteResult>('/tags/cleanup/delete', { tagIds, acknowledgeReferences })

// ---- NEW-216 集合快照 --------------------------------------------------------

export interface WorkspaceSummary {
  id: string
  name: string
}
export interface MemberSnapshot {
  id: string
  name: string
  refCount: number
  createdAt: string
}
export interface SnapshotDiff {
  added: string[]
  removed: string[]
  addedTotal: number
  removedTotal: number
}
export interface RestoreResult {
  restored: string[]
  skippedExisting: number
  invalidRefs: number
}
export const listWorkspaces = () => request<{ items: WorkspaceSummary[] }>('/workspaces')
export const listMemberSnapshots = (workspaceId: string) =>
  request<{ items: MemberSnapshot[] }>(
    `/workspaces/${encodeURIComponent(workspaceId)}/member-snapshots`,
  )
export const captureMemberSnapshot = (workspaceId: string, name: string) =>
  post<MemberSnapshot>(`/workspaces/${encodeURIComponent(workspaceId)}/member-snapshots`, { name })
export const diffMemberSnapshots = (workspaceId: string, a: string, b: string) =>
  post<SnapshotDiff>(`/workspaces/${encodeURIComponent(workspaceId)}/member-snapshots/diff`, { a, b })
export const restoreMemberSnapshot = (workspaceId: string, snapshotId: string, refs: string[]) =>
  post<RestoreResult>(`/workspaces/${encodeURIComponent(workspaceId)}/member-snapshots/restore`, {
    snapshotId,
    refs,
  })

// ---- NEW-217 排序配方 --------------------------------------------------------

export interface SortRecipe {
  id: string
  name: string
  fields: { key: string; dir: string }[]
  exceptions: string[]
  explain: string
}
export interface SortPreviewEntry {
  ref: string
  position: number
  fixed: boolean
}
export const listSortRecipes = (workspaceId: string) =>
  request<{ items: SortRecipe[] }>(`/workspaces/${encodeURIComponent(workspaceId)}/sort-recipes`)
export const createSortRecipe = (
  workspaceId: string,
  name: string,
  fields: { key: string; dir: string }[],
  exceptions: string[],
) =>
  post<SortRecipe>(`/workspaces/${encodeURIComponent(workspaceId)}/sort-recipes`, {
    name,
    fields,
    exceptions,
  })
export const previewSortRecipe = (workspaceId: string, recipeId: string) =>
  post<{ explain: string; ordering: SortPreviewEntry[]; memberCount: number }>(
    `/workspaces/${encodeURIComponent(workspaceId)}/sort-recipes/${encodeURIComponent(recipeId)}/preview`,
  )
export const applySortRecipe = (workspaceId: string, recipeId: string) =>
  post<{ explain: string; moved: number }>(
    `/workspaces/${encodeURIComponent(workspaceId)}/sort-recipes/${encodeURIComponent(recipeId)}/apply`,
  )
export const deleteSortRecipe = (workspaceId: string, recipeId: string) =>
  del(`/workspaces/${encodeURIComponent(workspaceId)}/sort-recipes/${encodeURIComponent(recipeId)}`)

// ---- NEW-218 引用检查 --------------------------------------------------------

export interface ReferenceIssue {
  surface: string
  locator: string
  ref: string
}
export interface ReferenceCheckResult {
  checked: number
  issues: ReferenceIssue[]
  keptStale: ReferenceIssue[]
  truncated: boolean
}
export const checkReferences = () => post<ReferenceCheckResult>('/references/check', {})
export const relinkReference = (surface: string, locator: string, oldRef: string, newRef: string) =>
  post<{ relinked: boolean }>('/references/relink', { surface, locator, oldRef, newRef })
export const keepStaleReference = (surface: string, locator: string, ref: string) =>
  post<{ kept: boolean }>('/references/keep-stale', { surface, locator, ref })

// ---- NEW-219 批量归档 --------------------------------------------------------

export interface ArchivePreviewItem {
  ref: string
  title: string
  feedTitle: string
  publishedAt: string
  read: boolean
  starred: boolean
}
export interface ArchivePreview {
  count: number
  sample: ArchivePreviewItem[]
  effectiveExclusions: string[]
}
export interface ArchiveReceipt {
  batchId: string
  archived: string[]
  failed: { ref: string; reason: string }[]
  createdAt: string
}
export const archivePreview = (olderThanDays: number) =>
  post<ArchivePreview>('/archive-batches/preview', { olderThanDays })
export const archiveApply = (refs: string[]) => post<ArchiveReceipt>('/archive-batches', { refs })
export const archiveUndo = (batchId: string) =>
  post<{ restored: string[]; skipped: { ref: string; reason: string }[] }>(
    `/archive-batches/${encodeURIComponent(batchId)}/undo`,
  )

// ---- NEW-220 处理记录 --------------------------------------------------------

export interface TriageEntry {
  id: string
  fromLocation: string
  toLocation: string
  refs: string[]
  reason: string
  createdAt: string
}
export interface TriageTrail {
  days: { date: string; entries: TriageEntry[] }[]
  count: number
}
export const listTriageJournal = () => request<TriageTrail>('/triage-journal')
export const createTriageEntry = (input: {
  fromLocation: string
  toLocation: string
  refs: string[]
  reason: string
}) => post<TriageEntry>('/triage-journal', input)
