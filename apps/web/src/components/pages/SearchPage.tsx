/** SearchPage — 搜索页（0011 Gate 4，参考图 03-search）。
 *
 * 用户批准的策略（决策 2）：诚实空态 + 0011a Basic Global Search 候选。
 * BFF 无全局搜索端点，本页交付：
 * - 主搜索框：明确提交（Enter）、清空（type=search 原生 ×）、取消；
 * - 搜索历史：本地 UI 数据（上限 10、单条删除/清空）；
 * - 「全局搜索能力尚未接入」空态：明确说明 0011a 候选，
 *   不冒充全局搜索、不显示假结果数/相关度排序/热门搜索
 *   （Spec §7.4：范围 chips 只显示后端真正支持的范围——当前无）。 */

import { useState } from 'react'
import { Clock, Search, X } from 'lucide-react'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { cx } from '../ui/cx'
import {
  clearSearchHistory,
  pushSearchHistory,
  readSearchHistory,
  removeFromSearchHistory,
} from '../../lib/search-history'

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>(() => readSearchHistory())

  const submit = () => {
    const q = query.trim()
    if (!q) return
    setSubmitted(q)
    setHistory(pushSearchHistory(history, q))
  }

  const cancel = () => {
    setQuery('')
    setSubmitted(null)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 主搜索框：提交 / 清空（原生 ×）/ 取消 */}
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
              placeholder="搜索文章、订阅源或关键词…"
              aria-label="搜索"
              className={cx(
                'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
                'py-2.5 pl-9 pr-3 text-sm text-[var(--lumi-text-primary)]',
                'placeholder:text-[var(--lumi-text-tertiary)]',
                'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
              )}
            />
          </div>
          {query.trim() !== '' && (
            <Button variant="ghost" size="sm" onClick={cancel} className="shrink-0">
              取消
            </Button>
          )}
        </div>

        {/* 搜索历史（本地 UI 数据；上限 10；单条删/清空） */}
        {history.length > 0 && (
          <section className="mt-5" aria-label="搜索历史">
            <div className="mb-2 flex items-center justify-between px-1">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
                搜索历史
              </h2>
              <button
                type="button"
                onClick={() => setHistory(clearSearchHistory(history))}
                className="rounded-[var(--lumi-radius-md)] px-2 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                清空
              </button>
            </div>
            <ul className="flex flex-wrap gap-2">
              {history.map((q) => (
                <li key={q}>
                  <div className="flex items-center gap-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] pl-2.5 pr-1">
                    <Clock aria-hidden className="size-3 text-[var(--lumi-text-tertiary)]" />
                    <button
                      type="button"
                      onClick={() => {
                        setQuery(q)
                        setSubmitted(q)
                      }}
                      className="max-w-48 truncate py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                    >
                      {q}
                    </button>
                    <button
                      type="button"
                      onClick={() => setHistory(removeFromSearchHistory(history, q))}
                      aria-label={`删除历史「${q}」`}
                      className="flex size-6 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] transition-colors hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                    >
                      <X aria-hidden className="size-3" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 诚实空态：全局搜索尚未接入（0011a 候选）。
            无范围 chips / 热门搜索 / 结果数 / 相关度排序——后端均无契约。 */}
        <div className="mt-8">
          {submitted === null ? (
            <EmptyState
              icon={<Search aria-hidden className="size-8" />}
              title="全局搜索能力尚未接入"
              description="全局搜索将在 0011a 里程碑提供（候选，待批准 BFF 契约）；当前页面仅保存搜索历史。"
            />
          ) : (
            <div
              role="status"
              className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4 text-sm text-[var(--lumi-text-secondary)]"
            >
              <p className="font-medium text-[var(--lumi-text-primary)]">
                已记录「{submitted}」到搜索历史
              </p>
              <p className="mt-1 text-xs leading-relaxed">
                全局搜索尚未接入（0011a 候选）——输入的内容保存在本地搜索历史，
                未来接入后可直接重搜。
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
