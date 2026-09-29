/** NEW-247 原文变动关注 — 以基线正文建关注，显式提交当前正文做哈希比对；
 * 检测到变化后开放差异入口（watching 态没有差异可看，诚实 409）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  checkContentWatch,
  getContentWatch,
  getContentWatchDiff,
  unwatchContent,
  watchContent,
} from '../../api/new241'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

const BLOCK_LABELS: Record<string, string> = {
  unchanged: '不变',
  added: '增加',
  removed: '删除',
  modified: '修改',
}

export function ContentWatchPanel({ entryRef }: { entryRef: string }) {
  const queryClient = useQueryClient()
  const [baselineText, setBaselineText] = useState('')
  const [currentText, setCurrentText] = useState('')
  const [diffOpen, setDiffOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const watch = useQuery({
    queryKey: ['new247-content-watch', entryRef],
    queryFn: ({ signal }) => getContentWatch(entryRef, signal),
    retry: false,
  })
  const diffQuery = useQuery({
    queryKey: ['new247-content-watch-diff', entryRef],
    queryFn: ({ signal }) => getContentWatchDiff(entryRef, signal),
    enabled: diffOpen,
    retry: false,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new247-content-watch', entryRef] })
  }

  const watchMutation = useMutation({
    mutationFn: () => watchContent(entryRef, baselineText),
    onSuccess: async () => {
      setNotice('已开始关注；之后提交当前正文做显式比对。')
      setBaselineText('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '关注失败'),
  })

  const checkMutation = useMutation({
    mutationFn: () => checkContentWatch(entryRef, currentText),
    onSuccess: async (result) => {
      setNotice(result.changed ? '检测到正文变化。' : '与基线一致，暂无变化。')
      setCurrentText('')
      if (result.changed) {
        setDiffOpen(true)
        await queryClient.invalidateQueries({ queryKey: ['new247-content-watch', entryRef] })
      }
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '比对失败'),
  })

  const unwatchMutation = useMutation({
    mutationFn: () => unwatchContent(entryRef),
    onSuccess: async () => {
      setNotice('已取消关注。')
      setDiffOpen(false)
      await queryClient.resetQueries({ queryKey: ['new247-content-watch', entryRef] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '取消关注失败'),
  })

  const notFound =
    watch.isError && watch.error instanceof Error && watch.error.message.includes('404')

  return (
    <section
      aria-label="原文变动关注（NEW-247）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">原文变动关注</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-247</span>
      </div>

      {watch.isPending && <Skeleton className="h-10 w-full" />}

      {watch.data && (
        <div className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          <span>
            状态：{watch.data.status === 'changed' ? '已检测到变化' : '关注中'}
            ；基线 {watch.data.baselineChars} 字；已比对 {watch.data.checksCount} 次。
          </span>
          {watch.data.status === 'changed' && (
            <div>
              <button
                type="button"
                aria-expanded={diffOpen}
                onClick={() => setDiffOpen((v) => !v)}
                className="text-[var(--lumi-accent)] underline underline-offset-2"
              >
                {diffOpen ? '收起差异' : '查看差异'}
              </button>
              {diffOpen && diffQuery.isPending && <Skeleton className="mt-1 h-8 w-full" />}
              {diffOpen && diffQuery.data && (
                <div className="mt-1 flex flex-col gap-1" aria-label="变动差异">
                  <p>
                    增加 {diffQuery.data.added} 段 / 删除 {diffQuery.data.removed} 段 / 修改{' '}
                    {diffQuery.data.modified} 段
                  </p>
                  {diffQuery.data.blocks.map((block, index) => (
                    <div key={index} className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2">
                      <span className="mr-2 text-[var(--lumi-text-tertiary)]">
                        {BLOCK_LABELS[block.type] ?? block.type}
                      </span>
                      {block.type === 'modified' ? `${block.oldText} → ${block.newText}` : block.text}
                    </div>
                  ))}
                </div>
              )}
              {diffOpen && diffQuery.isError && (
                <div role="alert" className="mt-1">
                  差异加载失败。{diffQuery.error instanceof Error ? diffQuery.error.message : ''}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {notFound && (
        <div className="flex flex-col gap-1">
          <textarea
            aria-label="基线正文"
            value={baselineText}
            onChange={(event) => setBaselineText(event.target.value)}
            placeholder="粘贴当前正文作为关注基线（空行分段）…"
            rows={3}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <Button
            size="sm"
            variant="secondary"
            className="self-start"
            disabled={baselineText.trim() === '' || watchMutation.isPending}
            onClick={() => watchMutation.mutate()}
          >
            开始关注
          </Button>
        </div>
      )}

      {watch.data && (
        <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
          <textarea
            aria-label="当前正文（用于比对）"
            value={currentText}
            onChange={(event) => setCurrentText(event.target.value)}
            placeholder="粘贴当前正文做显式比对…"
            rows={3}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={currentText.trim() === '' || checkMutation.isPending}
              onClick={() => checkMutation.mutate()}
            >
              提交比对
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={unwatchMutation.isPending}
              onClick={() => unwatchMutation.mutate()}
            >
              取消关注
            </Button>
          </div>
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
