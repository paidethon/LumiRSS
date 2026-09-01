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

/** 导入结果摘要：全部来自 server-confirmed 响应，无推测。 */
export function OpmlResultCard({ result }: { result: OpmlImportResult }) {
  const categoryNotApplied = result.added.filter((a) => !a.categoryApplied).length
  return (
    <div
      role="status"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)]/30 bg-[var(--lumi-accent)]/10 p-3.5"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-[var(--lumi-text-primary)]">
        <CheckCircle2 aria-hidden className="size-4 shrink-0 text-[var(--lumi-accent)]" />
        已导入 {result.added.length} 个订阅源
        {result.duplicates.length > 0 && `，跳过重复 ${result.duplicates.length} 个`}
        {result.failed.length > 0 && `，失败 ${result.failed.length} 个`}
      </p>
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
