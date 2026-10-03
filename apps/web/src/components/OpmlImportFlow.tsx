/** OpmlImportFlow — 0013 Gate 4：OPML 导入的共享摘要卡片（组件）。
 *
 * 流程逻辑（hook / 纯函数）在 lib/opml-import.ts；同一组卡片被两个外壳
 * 复用：订阅页的 OpmlImportDialog（移动端）与设置 → 订阅与来源 的内联
 * 区块（全断点，桌面无嵌套 Dialog 问题）。
 *
 * 展示边界：只渲染 server-confirmed 数据；merge-only 文案如实说明
 * （不删除、不覆盖现有订阅）。 */

import { AlertCircle, CheckCircle2 } from 'lucide-react'
import type {
  RsshubImportApplyResult,
  RsshubImportPlan,
} from '../api/client'
import type { OpmlImportPreview, OpmlImportResult } from '../api/types'
import { opmlFailureLabel } from '../lib/opml-import'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

/** 预览摘要：数量 / 分类 / 重复（只显示可靠判定项）。 */
export function OpmlPreviewCard({ preview }: { preview: OpmlImportPreview }) {
  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <div>
          <dt className="text-xs text-[var(--lumi-text-tertiary)]">订阅源</dt>
          <dd className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            {preview.totalFeeds}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--lumi-text-tertiary)]">新增</dt>
          <dd className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            {preview.newFeeds}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--lumi-text-tertiary)]">已订阅 / 重复</dt>
          <dd className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            {preview.duplicates}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--lumi-text-tertiary)]">无效条目</dt>
          <dd className="text-sm font-semibold text-[var(--lumi-text-primary)]">
            {preview.invalidEntries}
          </dd>
        </div>
      </dl>
      {preview.categories.length > 0 && (
        <p className="mt-2.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          分类（{preview.categories.length}）：
          {preview.categories.map((c) => `${c.label}（${c.feedCount}）`).join('、')}
        </p>
      )}
      <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        重复判定仅基于订阅地址精确匹配；导入为合并（只新增，不删除、不覆盖现有订阅）。
      </p>
    </div>
  )
}

/** F002：逐项预览表（复选框；全选/反选；默认勾选由流程 hook 决定）。
 * status → 中文标签：new=新增 / duplicate=重复 / invalid=无效 /
 * category_conflict=分类冲突（note 说明冲突原因）。 */
export function OpmlPreviewItemsCard({
  preview,
  selected,
  onToggleItem,
  onToggleAll,
  onInvert,
}: {
  preview: OpmlImportPreview
  selected: Set<number>
  onToggleItem: (index: number) => void
  onToggleAll: () => void
  onInvert: () => void
}) {
  const items = preview.items ?? []
  if (items.length === 0) return null
  const allSelected = items.every((i) => selected.has(i.index))
  const statusLabel: Record<string, string> = {
    new: '新增',
    duplicate: '重复',
    invalid: '无效',
    category_conflict: '分类冲突',
  }
  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--lumi-separator)] px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
          逐项导入（已选 {selected.size}/{items.length}）
        </span>
        <span className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={onToggleAll} disabled={items.length === 0}>
            {allSelected ? '全不选' : '全选'}
          </Button>
          <Button size="sm" variant="ghost" onClick={onInvert} disabled={items.length === 0}>
            反选
          </Button>
        </span>
      </div>
      <ul className="max-h-56 divide-y divide-[var(--lumi-separator)] overflow-y-auto">
        {items.map((item) => (
          <li key={item.index}>
            <label
              htmlFor={`opml-item-${item.index}`}
              className="flex min-h-11 cursor-pointer items-center gap-2.5 px-3 py-1.5 hover:bg-[var(--lumi-surface-hover)]"
            >
              <input
                id={`opml-item-${item.index}`}
                type="checkbox"
                aria-label={`选择 ${item.title || item.xmlUrl}`}
                checked={selected.has(item.index)}
                onChange={() => onToggleItem(item.index)}
                className="size-4 shrink-0 accent-[var(--lumi-accent)]"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-[var(--lumi-text-primary)]">
                  {item.title || item.xmlUrl}
                  <span
                    className={cx(
                      'ml-2 inline-block rounded-full px-1.5 py-0.5 text-[10px] leading-tight',
                      item.status === 'new' &&
                        'bg-[var(--lumi-accent)]/15 text-[var(--lumi-accent-text)]',
                      item.status === 'duplicate' && 'bg-[var(--lumi-text-tertiary)]/15 text-[var(--lumi-text-tertiary)]',
                      item.status === 'invalid' && 'bg-[var(--lumi-danger)]/15 text-[var(--lumi-danger)]',
                      item.status === 'category_conflict' && 'bg-[var(--lumi-warning)]/20 text-[var(--lumi-text-primary)]',
                    )}
                  >
                    {statusLabel[item.status] ?? item.status}
                  </span>
                </span>
                <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]" title={item.xmlUrl}>
                  {item.xmlUrl}
                  {item.category !== null && item.category !== undefined && ` · ${item.category}`}
                </span>
                {item.note !== null && item.note !== undefined && (
                  <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                    {item.note}
                  </span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** 导入结果摘要：全部来自 server-confirmed 响应，无推测。 */
export function OpmlResultCard({ result }: { result: OpmlImportResult }) {
  const categoryNotApplied = result.added.filter((a) => !a.categoryApplied).length
  return (
    <div
      role="status"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)]/30 bg-[var(--lumi-accent)]/10 p-3.5"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-[var(--lumi-text-primary)]">
        <CheckCircle2 aria-hidden className="size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        已导入 {result.added.length} 个订阅源
        {result.duplicates.length > 0 && `，跳过重复 ${result.duplicates.length} 个`}
        {(result.skipped?.length ?? 0) > 0 && `，未导入 ${result.skipped.length} 个`}
        {result.failed.length > 0 && `，失败 ${result.failed.length} 个`}
      </p>
      {(result.skipped?.length ?? 0) > 0 && (
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          未导入：{result.skipped.map((s) => `${s.title || s.feedUrl}（${s.reason === 'invalid' ? '无效' : '未勾选'}）`).join('、')}
        </p>
      )}
      {result.categoriesCreated.length > 0 && (
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          新建分类：{result.categoriesCreated.join('、')}
        </p>
      )}
      {categoryNotApplied > 0 && (
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          其中 {categoryNotApplied} 个源已添加但未能移入指定分类（保留在默认分类）。
        </p>
      )}
      {result.failed.length > 0 && (
        <ul className="mt-2 divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]">
          {result.failed.map((f) => (
            <li key={f.feedUrl} className="flex items-start gap-2 py-1.5 text-xs">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--lumi-danger)]" />
              <span className="min-w-0">
                <span className="block truncate text-[var(--lumi-text-primary)]" title={f.feedUrl}>
                  {f.title}
                </span>
                <span className="block text-[var(--lumi-text-tertiary)]">
                  {opmlFailureLabel(f.error)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 错误提示卡（预览 / 导入失败共用）。 */
export function OpmlErrorCard({ title, detail }: { title: string; detail: string | null }) {
  return (
    <div
      role="alert"
      className={cx(
        'flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30',
        'bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]',
      )}
    >
      <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0">
        <span className="block font-medium">{title}</span>
        {detail !== null && (
          <span className="mt-0.5 block text-xs opacity-80">{detail}</span>
        )}
      </span>
    </div>
  )
}

// ---- R18 RSSHub 优化导入（计划 / 结果卡片，与 flat 卡片同风格） ----------------

const RSSHUB_DECISION_LABEL: Record<string, string> = {
  autoReplace: '自动替换',
  manualChoice: '请选择',
  needsCredentials: '需授权',
  needsParams: '缺参数',
  alreadyRsshub: '已在本站',
  keepNative: '保持原生',
  unsupported: '不支持',
}

const RSSHUB_SKIP_REASON_LABEL: Record<string, string> = {
  duplicate: '已订阅',
  invalid: '无效',
  not_selected: '未勾选',
  no_candidate: '无可替换候选',
  route_not_constructable: '路由参数不足',
  route_not_in_plan: '候选不在计划内',
  rsshub_already_subscribed: 'RSSHub 地址已订阅',
  validation_budget_exhausted: '验证次数用尽',
  rsshub_not_found: 'RSSHub 路由不可用',
  rsshub_not_a_feed: 'RSSHub 未返回有效 feed',
  rsshub_rsshub_unreachable: 'RSSHub 实例不可达',
  rsshub_auth_failure: 'RSSHub 访问被拒（鉴权）',
  rsshub_rate_limited: 'RSSHub 限流',
  rsshub_upstream_reject: 'RSSHub 上游拒绝',
}

function rsshubReasonLabel(reason: string): string {
  return RSSHUB_SKIP_REASON_LABEL[reason] ?? reason
}

/** R18：匹配计划卡（严格只读结果；决策与候选依据逐项可见）。 */
export function RsshubPlanCard({
  plan,
  manualSelected,
  onToggleManual,
  strategy,
}: {
  plan: RsshubImportPlan
  manualSelected: Set<number>
  onToggleManual: (index: number) => void
  strategy: 'prefer_rsshub' | 'prefer_native' | 'manual'
}) {
  const counts = plan.counts
  const summary = [
    `自动替换 ${counts['autoReplace'] ?? 0}`,
    `请选择 ${counts['manualChoice'] ?? 0}`,
    `需授权 ${counts['needsCredentials'] ?? 0}`,
    `缺参数 ${counts['needsParams'] ?? 0}`,
    `已在本站 ${counts['alreadyRsshub'] ?? 0}`,
    `保持原生 ${counts['keepNative'] ?? 0}`,
  ].join(' · ')
  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]">
      <div className="border-b border-[var(--lumi-separator)] px-3 py-2">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]" data-testid="rsshub-plan-summary">
          RSSHub 匹配计划（{plan.totalFeeds} 项）
        </p>
        <p className="mt-0.5 text-xs text-[var(--lumi-text-secondary)]">{summary}</p>
        {!plan.rsshubConfigured && (
          <p role="alert" className="mt-1 text-xs text-[var(--lumi-warning)]">
            RSSHub 未配置：只能按原生导入（服务端设置 RSSHUB_BASE_URL 后可用替换）。
          </p>
        )}
      </div>
      <ul className="max-h-64 divide-y divide-[var(--lumi-separator)] overflow-y-auto">
        {plan.items.map((item) => {
          const selectable = strategy === 'manual' && item.decision === 'manualChoice'
          const checked = manualSelected.has(item.index)
          return (
            <li key={item.index}>
              <div className="flex min-h-11 items-start gap-2.5 px-3 py-1.5">
                {selectable && (
                  <input
                    id={`rsshub-item-${item.index}`}
                    type="checkbox"
                    aria-label={`替换 ${item.title || item.xmlUrl}`}
                    checked={checked}
                    onChange={() => onToggleManual(item.index)}
                    className="mt-0.5 size-4 shrink-0 accent-[var(--lumi-accent)]"
                  />
                )}
                <label
                  htmlFor={selectable ? `rsshub-item-${item.index}` : undefined}
                  className="min-w-0 flex-1 cursor-pointer"
                >
                  <span className="block truncate text-sm text-[var(--lumi-text-primary)]">
                    {item.title || item.xmlUrl}
                    <span
                      className={cx(
                        'ml-2 inline-block rounded-full px-1.5 py-0.5 text-[10px] leading-tight',
                        item.decision === 'autoReplace' &&
                          'bg-[var(--lumi-accent)]/15 text-[var(--lumi-accent-text)]',
                        (item.decision === 'manualChoice' || item.decision === 'needsParams') &&
                          'bg-[var(--lumi-warning)]/20 text-[var(--lumi-text-primary)]',
                        item.decision === 'needsCredentials' &&
                          'bg-[var(--lumi-warning)]/20 text-[var(--lumi-text-primary)]',
                        (item.decision === 'keepNative' || item.decision === 'unsupported') &&
                          'bg-[var(--lumi-text-tertiary)]/15 text-[var(--lumi-text-tertiary)]',
                        item.decision === 'alreadyRsshub' &&
                          'bg-[var(--lumi-text-tertiary)]/15 text-[var(--lumi-text-tertiary)]',
                      )}
                    >
                      {RSSHUB_DECISION_LABEL[item.decision] ?? item.decision}
                    </span>
                  </span>
                  <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]" title={item.xmlUrl}>
                    {item.xmlUrl}
                  </span>
                  {item.match.candidates.length > 0 && (
                    <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                      候选：{item.match.candidates[0].routePath}（{item.match.candidates[0].basis}）
                    </span>
                  )}
                  {item.note !== null && (
                    <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">{item.note}</span>
                  )}
                </label>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** R18：应用结果卡（全部来自 server-confirmed 响应；跳过原因逐条可读）。 */
export function RsshubResultCard({ result }: { result: RsshubImportApplyResult }) {
  const counts = result.counts
  return (
    <div
      role="status"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)]/30 bg-[var(--lumi-accent)]/10 p-3.5"
      data-testid="rsshub-result"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-[var(--lumi-text-primary)]">
        <CheckCircle2 aria-hidden className="size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        替换 {counts.replaced} · 原生导入 {counts.addedNative} · 跳过 {counts.skipped} · 失败{' '}
        {counts.failed}
      </p>
      <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        {result.entryStateNote}
      </p>
      {result.replaced.some((r) => r.keptOldSource) && (
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          其中 {result.keptOldSource.length} 个原地址本就已在订阅中：旧源保留、新源并存（绝不自动退订）。
        </p>
      )}
      {result.skipped.length > 0 && (
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          跳过：
          {result.skipped
            .map((s) => `${s.title || s.feedUrl}（${rsshubReasonLabel(s.reason)}）`)
            .join('、')}
        </p>
      )}
      {result.failed.length > 0 && (
        <ul className="mt-2 divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]">
          {result.failed.map((f) => (
            <li key={f.feedUrl} className="flex items-start gap-2 py-1.5 text-xs">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--lumi-danger)]" />
              <span className="min-w-0">
                <span className="block truncate text-[var(--lumi-text-primary)]" title={f.feedUrl}>
                  {f.title}
                </span>
                <span className="block text-[var(--lumi-text-tertiary)]">
                  {rsshubReasonLabel(f.error)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
