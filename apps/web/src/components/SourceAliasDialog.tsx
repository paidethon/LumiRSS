/** SourceAliasDialog — N013 来源改名（服务端别名 + 改名历史）。
 *
 * - 服务端真源：PUT /api/v1/sources/alias（upsert，变化写历史）；
 * - 历史（≤20，新→旧）：「恢复」= 用历史旧名重新 PUT；
 * - 清除别名：DELETE（历史保留）；
 * - 上游标题（FreshRSS truth）永不修改，输入留空保存禁用；
 * - 展示接线（SourceLabel / 订阅行）由 useSourceAliasesQuery 统一提供：
 *   服务端别名赢，localStorage（lib/source-aliases.ts）只是离线回退。
 */

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { History, Loader2 } from 'lucide-react'
import {
  useDeleteSourceAliasMutation,
  useSetSourceAliasMutation,
  useSourceAliasHistoryQuery,
  useSourceAliasesQuery,
} from '../api/queries'
import { managementErrorText } from '../lib/management-errors'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'

export default function SourceAliasDialog({
  open,
  onClose,
  feedUrl,
  title,
}: {
  open: boolean
  onClose: () => void
  feedUrl: string
  title: string
}) {
  const queryClient = useQueryClient()
  const aliasesQuery = useSourceAliasesQuery(open)
  const historyQuery = useSourceAliasHistoryQuery(open ? feedUrl : null)
  const serverAlias = aliasesQuery.data?.items.find((alias) => alias.feedUrl === feedUrl)
  const [draft, setDraft] = useState('')
  useEffect(() => {
    if (open) setDraft(serverAlias?.customName ?? '')
    // 打开时以服务端当前值初始化草稿（加载完成前为空）
  }, [open, serverAlias?.customName])

  const setMutation = useSetSourceAliasMutation()
  const deleteMutation = useDeleteSourceAliasMutation()
  const busy = setMutation.isPending || deleteMutation.isPending
  const error =
    setMutation.isError
      ? managementErrorText(setMutation.error)
      : deleteMutation.isError
        ? managementErrorText(deleteMutation.error)
        : null

  const save = (name: string) => {
    if (busy) return
    setMutation.mutate(
      { feedUrl, customName: name },
      {
        onSuccess: async () => {
          setDraft('')
          await queryClient.invalidateQueries({ queryKey: ['source-alias-history', feedUrl] })
        },
      },
    )
  }

  const history = historyQuery.data?.items ?? []

  return (
    <Dialog open={open} onClose={onClose} title={`${title} — 来源改名`}>
      <div className="flex flex-col gap-3">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          为来源设置一个更好认的显示名。别名保存在你的账户（跨设备生效）；
          上游标题变更不会覆盖别名。
        </p>
        <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-2">
          <p className="truncate text-sm text-[var(--lumi-text-primary)]" title={feedUrl}>
            {feedUrl}
          </p>
          <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]" data-testid="alias-current">
            当前别名：{serverAlias?.customName ?? '未设置'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            aria-label="新的别名"
            placeholder="输入别名"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="h-11 min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          />
          <Button
            variant="primary"
            size="sm"
            className="min-h-11"
            disabled={draft.trim() === '' || busy}
            onClick={() => save(draft)}
          >
            {setMutation.isPending ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
            保存
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="min-h-11"
            disabled={serverAlias === undefined || busy}
            onClick={() => deleteMutation.mutate(feedUrl)}
          >
            清除
          </Button>
        </div>

        {error !== null && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {error.title}
          </p>
        )}

        <div>
          <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-primary)]">
            <History aria-hidden className="size-3.5" />
            改名历史（新→旧）
          </p>
          {historyQuery.isPending ? (
            <p className="mt-1.5 text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>
          ) : history.length === 0 ? (
            <EmptyState
              title="还没有改名记录"
              description="首次设置别名或更名后会在这里留下历史（最多 20 条）。"
            />
          ) : (
            <ul className="mt-1.5 flex flex-col gap-1" data-testid="alias-history">
              {history.map((item) => {
                const nameToRestore =
                  item.oldCustomName ?? null
                return (
                  <li
                    key={item.id}
                    className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                      {item.oldCustomName ?? '（首设别名）'}
                      {item.upstreamNameAtSave !== null && (
                        <span className="text-[var(--lumi-text-tertiary)]">
                          {' '}
                          · 上游当时：{item.upstreamNameAtSave}
                        </span>
                      )}
                    </span>
                    {nameToRestore !== null && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="min-h-9"
                        disabled={busy}
                        onClick={() => save(nameToRestore)}
                        aria-label={`恢复「${nameToRestore}」`}
                      >
                        恢复
                      </Button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </Dialog>
  )
}
