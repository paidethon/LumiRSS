/** EntryRevisionsPanel — N031 文章修订差异面板（阅读页局部，按需加载）。
 *
 * 数据：GET /api/v1/entries/{ref}/revisions（BFF 纯投影查询，有界元
 * 数据，绝无全文副本）。无修订 → 不渲染入口（不占空间）。
 *
 * 展示：每条修订 = 捕获时间 + 标题变化 + 结构差异摘要（标题/段落/链接
 * 数变化）+ 首个差异段摘录（两侧 ≤200 字，纯文本——BFF 保证）。摘要
 * basis=hash_only 时如实标注「无保留版本可比」——不臆造差异。
 *
 * 阅读进度不受影响：面板只在正文上方渲染一个可折叠区域，不触碰滚动
 * 容器与阅读位置逻辑。
 */

import { useQuery } from '@tanstack/react-query'
import { History } from 'lucide-react'

import { getEntryRevisions } from '../api/client'
import { cx } from './ui/cx'

const STRUCT_LABELS: Record<string, string> = {
  headingsChanged: '标题',
  paragraphsChanged: '段落',
  linksChanged: '链接',
}

function signed(n: number | undefined): string {
  if (typeof n !== 'number' || Number.isNaN(n)) return '—'
  return n > 0 ? `+${n}` : `${n}`
}

function Excerpt({ label, text }: { label: string; text: string }) {
  // 刻意不用 <p>/<li>：正文语块选择器（朗读/朗读进度）只收集
  // .lumi-reader-article 内的内容语义标签，工具面板不得混入。
  return (
    <div className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-tertiary)]">
      <span className="me-1 text-[var(--lumi-text-secondary)]">{label}</span>
      <span>{text === '' ? '（无）' : text}</span>
    </div>
  )
}

export default function EntryRevisionsPanel({ entryRef }: { entryRef: string }) {
  const revisions = useQuery({
    queryKey: ['entry-revisions', entryRef],
    queryFn: ({ signal }) => getEntryRevisions(entryRef, signal),
    staleTime: 30_000,
  })

  const rows = revisions.data?.revisions ?? []
  if (!revisions.isPending && rows.length === 0) return null

  return (
    <details
      data-testid="entry-revisions-panel"
      className="mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2 text-xs"
    >
      <summary
        className={cx(
          'flex cursor-pointer select-none items-center gap-1.5 font-medium',
          'text-[var(--lumi-text-secondary)] focus-visible:outline-2',
          'focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        )}
      >
        <History aria-hidden className="size-3.5" />
        <span data-testid="entry-revisions-trigger">修订记录</span>
        {rows.length > 0 && (
          <span
            data-testid="entry-revisions-count"
            className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-px text-[10px] text-[var(--lumi-text-secondary)]"
          >
            {rows.length}
          </span>
        )}
      </summary>
      {revisions.isPending ? (
        <div className="mt-2 text-[var(--lumi-text-tertiary)]">载入中…</div>
      ) : revisions.isError ? (
        <div role="alert" className="mt-2 text-[var(--lumi-text-secondary)]">
          修订记录载入失败。
        </div>
      ) : (
        <div role="list" className="mt-2 flex flex-col gap-2">
          {rows.map((rev) => {
            const summary = (rev.summary ?? {}) as Record<string, unknown>
            const basis = summary['basis']
            return (
              <div
                role="listitem"
                key={rev.id}
                data-testid="entry-revision-item"
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] px-2.5 py-1.5"
              >
                <div className="flex flex-wrap items-center gap-1.5 text-[var(--lumi-text-secondary)]">
                  <span>{rev.capturedAt.slice(0, 19).replace('T', ' ')}</span>
                  {rev.titleChanged && (
                    <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-px text-[10px]">
                      标题有修改
                    </span>
                  )}
                  {basis === 'hash_only' && (
                    <span
                      title="未保留上一版本内容，无法生成结构差异摘要"
                      className="text-[var(--lumi-text-tertiary)]"
                    >
                      内容已变化（无保留版本可比）
                    </span>
                  )}
                </div>
                {rev.titleChanged && (rev.prevTitle ?? rev.newTitle) !== null && (
                  <div className="mt-1 truncate text-[var(--lumi-text-tertiary)]">
                    {rev.prevTitle ?? '（空）'} → {rev.newTitle ?? '（空）'}
                  </div>
                )}
                {basis !== 'hash_only' && (
                  <div className="mt-1 flex flex-wrap gap-2 text-[var(--lumi-text-secondary)]">
                    {Object.keys(STRUCT_LABELS).map((key) => (
                      <span key={key} data-testid={`revision-${key}`}>
                        {STRUCT_LABELS[key]} {signed(summary[key] as number | undefined)}
                      </span>
                    ))}
                  </div>
                )}
                {basis !== 'hash_only' &&
                  typeof summary['excerptPrev'] === 'string' &&
                  typeof summary['excerptNew'] === 'string' &&
                  (summary['excerptPrev'] !== '' || summary['excerptNew'] !== '') && (
                    <div className="mt-1 flex flex-col gap-0.5">
                      <Excerpt label="改前：" text={String(summary['excerptPrev'])} />
                      <Excerpt label="改后：" text={String(summary['excerptNew'])} />
                    </div>
                  )}
              </div>
            )
          })}
        </div>
      )}
    </details>
  )
}
