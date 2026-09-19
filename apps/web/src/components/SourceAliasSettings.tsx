/** SourceAliasSettings — R03 来源显示别名管理（设置 → 订阅与来源）。
 *
 * - 数据：lib/source-aliases.ts（localStorage，设备本地，上限 200）；
 * - 订阅列表：useFeeds()（api/queries，与侧栏同一 FreshRSS truth）；
 * - 每行：真实名（只读展示，永不被修改）+ 别名输入 + 保存 + 清除；
 * - 诚实空态：无订阅时说明而非留白；
 * - 别名只影响展示层；列表来源名的显示接入由集成方统一完成。
 */

import { useMemo, useState } from 'react'
import { useFeeds } from '../api/queries'
import { Button } from './ui/Button'
import {
  clearSourceAlias,
  getSourceAliases,
  setSourceAlias,
  SOURCE_ALIAS_LIMIT,
} from '../lib/source-aliases'

export function SourceAliasSettings() {
  const feedsQuery = useFeeds()
  const feeds = useMemo(() => feedsQuery.data ?? [], [feedsQuery.data])
  /** 每行输入草稿（feedTitle → 输入框内容） */
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  /** 保存/清除后递增，触发别名表重读 */
  const [version, setVersion] = useState(0)
  const aliases = useMemo(() => getSourceAliases(), [version])

  const setDraft = (title: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [title]: value }))
  }

  const handleSave = (title: string) => {
    if ((drafts[title] ?? '').trim() === '') return
    setSourceAlias(title, drafts[title] ?? '')
    setVersion((v) => v + 1)
    setDrafts((prev) => ({ ...prev, [title]: '' }))
  }

  const handleClear = (title: string) => {
    clearSourceAlias(title)
    setVersion((v) => v + 1)
    setDrafts((prev) => ({ ...prev, [title]: '' }))
  }

  if (feedsQuery.isLoading) {
    return (
      <p className="py-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        正在加载订阅列表…
      </p>
    )
  }

  if (feedsQuery.isError) {
    return (
      <p className="py-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]" role="alert">
        订阅列表加载失败，请稍后重试（别名设置暂不可用）。
      </p>
    )
  }

  if (feeds.length === 0) {
    return (
      <div className="py-3">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          暂无订阅。订阅来源后可在这里为来源设置显示别名。
        </p>
        <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          别名仅保存在本设备（上限 {SOURCE_ALIAS_LIMIT} 条），不会修改真实订阅名，也不会同步到其它设备。
        </p>
      </div>
    )
  }

  return (
    <div className="py-2">
      <p className="mb-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        为来源设置一个更好认的显示名（仅本设备生效；真实订阅名不变，上限 {SOURCE_ALIAS_LIMIT} 条）。
      </p>
      <ul className="divide-y divide-[var(--lumi-separator)]">
        {feeds.map((feed) => {
          const alias = aliases.get(feed.title)
          const draft = drafts[feed.title] ?? ''
          return (
            <li key={feed.feedUrl} className="flex flex-wrap items-center gap-2 py-2.5">
              <div className="min-w-0 flex-1 basis-40">
                <p className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                  {feed.title}
                </p>
                <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
                  {alias !== undefined ? `当前别名：${alias}` : '未设置别名'}
                </p>
              </div>
              <input
                type="text"
                aria-label={`${feed.title} 的别名`}
                placeholder="输入别名"
                value={draft}
                onChange={(e) => setDraft(feed.title, e.target.value)}
                className="h-11 min-w-0 basis-40 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              />
              <Button
                variant="secondary"
                size="sm"
                className="min-h-11"
                disabled={draft.trim() === ''}
                onClick={() => handleSave(feed.title)}
              >
                保存
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="min-h-11"
                disabled={alias === undefined}
                onClick={() => handleClear(feed.title)}
              >
                清除
              </Button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default SourceAliasSettings
