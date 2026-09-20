/** DuplicatesDialog — F071 疑似重复审核队列（BookmarksPage「整理」入口）。
 *
 * 扫描（幂等，从不自动删除/合并）→ pending 队列：双方标题/来源/
 * 相似原因 + 三动作（确认重复→建 duplicate 关联 / 忽略 / 白名单）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  duplicateAction,
  listDuplicates,
  scanDuplicates,
  type DuplicatePair,
} from '../api/client'
import { Dialog } from './ui/Dialog'
import { Button } from './ui/Button'

const REASON_LABELS: Record<string, string> = {
  title_jaccard: '标题高度相似',
  same_content_url: '同一内容地址（不同来源）',
}

export function DuplicatesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [scanned, setScanned] = useState<number | null>(null)
  const queryClient = useQueryClient()
  const queue = useQuery({
    queryKey: ['duplicates', 'pending'],
    queryFn: () => listDuplicates('pending'),
    enabled: open,
  })
  const scan = useMutation({
    mutationFn: () => scanDuplicates(),
    onSuccess: async (result) => {
      setScanned(result.scanned)
      await queryClient.invalidateQueries({ queryKey: ['duplicates'] })
    },
  })
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'confirm' | 'ignore' | 'whitelist' }) =>
      duplicateAction(id, action),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['duplicates'] })
    },
  })

  const items = queue.data?.items ?? []

  return (
    <Dialog open={open} onClose={onClose} title="疑似重复" panelClassName="max-w-lg">
      <div className="flex flex-col gap-3" data-lumi-duplicates="">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={scan.isPending}
            onClick={() => scan.mutate()}
          >
            {scan.isPending ? '扫描中…' : '扫描书签/剪藏'}
          </Button>
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            扫描只产「疑似」对，绝不自动删除或合并任何条目。
          </span>
        </div>
        {scanned !== null && (
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
            已扫描 {scanned} 条，待审核 {items.length} 对。
          </p>
        )}

        {queue.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>}
        {queue.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">队列加载失败。</p>
        )}
        {!queue.isPending && items.length === 0 && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            没有待审核的疑似重复。先执行扫描，或此前已全部处理。
          </p>
        )}

        <ul className="flex flex-col gap-2">
          {items.map((pair: DuplicatePair) => (
            <li
              key={pair.id}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs"
            >
              <div className="flex flex-col gap-0.5">
                <span className="font-medium text-[var(--lumi-text-primary)]">甲：{pair.aTitle ?? pair.aRef}</span>
                <span className="font-medium text-[var(--lumi-text-primary)]">乙：{pair.bTitle ?? pair.bRef}</span>
                <span className="text-[var(--lumi-text-tertiary)]">
                  相似原因：{REASON_LABELS[pair.reason] ?? pair.reason}
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-1.5">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ id: pair.id, action: 'confirm' })}
                >
                  确认重复
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ id: pair.id, action: 'ignore' })}
                >
                  忽略
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={act.isPending}
                  onClick={() => act.mutate({ id: pair.id, action: 'whitelist' })}
                >
                  白名单（不再提示）
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </Dialog>
  )
}
