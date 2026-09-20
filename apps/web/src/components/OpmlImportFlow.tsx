/** OpmlImportFlow — 0013 Gate 4：OPML 导入的共享摘要卡片（组件）。
 *
 * 流程逻辑（hook / 纯函数）在 lib/opml-import.ts；同一组卡片被两个外壳
 * 复用：订阅页的 OpmlImportDialog（移动端）与设置 → 订阅与来源 的内联
 * 区块（全断点，桌面无嵌套 Dialog 问题）。
 *
 * 展示边界：只渲染 server-confirmed 数据；merge-only 文案如实说明
 * （不删除、不覆盖现有订阅）。 */

import { AlertCircle, CheckCircle2 } from 'lucide-react'
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
                      'ml-2 inline-block rounded-full px-1.5 py-0.5 text-[10px] leading-none',
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
