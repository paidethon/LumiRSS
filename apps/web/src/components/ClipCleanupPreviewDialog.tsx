/** ClipCleanupPreviewDialog — N123 剪藏清理预览。
 *
 * 把 HTML 交给 POST /library/clips/preview-cleanup（零写入）得到逐块
 * 「建议保留/建议移除」分类；用户逐块改勾选后，由调用方拿到最终
 * keepIds 去走既有的净化保存路径（PATCH revision / 应用候选——同一
 * sanitize_html 管线）。本组件自身绝不写库，确认前原内容不动。
 */

import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useClipCleanupPreviewMutation } from '../api/queries'
import type { ClipCleanupBlock } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

const reasonLabel: Record<ClipCleanupBlock['reason'], string> = {
  paragraph: '段落',
  heading: '标题',
  image: '图片',
  ad: '广告话术',
  nav: '导航/页脚',
  link_list: '链接列表',
}

export function ClipCleanupPreviewDialog({
  html,
  onConfirm,
  onCancel,
  confirmLabel = '应用清理',
}: {
  html: string
  onConfirm: (keepIds: string[]) => void
  onCancel: () => void
  confirmLabel?: string
}) {
  const preview = useClipCleanupPreviewMutation()
  const [keep, setKeep] = useState<Set<string> | null>(null)

  useEffect(() => {
    preview.mutate(html)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 挂载时预览一次（html 由调用方持有，零写入）
  }, [html])

  const blocks: ClipCleanupBlock[] = preview.data?.blocks ?? []
  const selected = keep ?? new Set(blocks.filter((b) => b.keep).map((b) => b.id))

  function toggle(id: string) {
    setKeep((prev) => {
      const base = prev ?? new Set(blocks.filter((b) => b.keep).map((b) => b.id))
      const next = new Set(base)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Dialog
      open
      onClose={onCancel}
      title="清理预览"
      panelClassName="max-w-xl"
      footer={
        <div className="flex w-full items-center gap-2">
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            保留 {selected.size}/{blocks.length} 块 · 保存前仍走服务端净化
          </span>
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" size="sm" onClick={onCancel}>
              取消
            </Button>
            <Button
              variant="primary"
              size="sm"
              data-cleanup-confirm=""
              disabled={preview.isPending}
              onClick={() => onConfirm([...selected])}
            >
              {confirmLabel}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-clip-cleanup-preview="">
        {preview.isPending && (
          <div aria-label="清理预览加载中">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="mt-2 h-6 w-full" />
          </div>
        )}
        {preview.isPending && (
          <p className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
            正在分析块结构…
          </p>
        )}
        {preview.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            清理预览失败：
            {preview.error instanceof Error
              ? preview.error.message
              : '请稍后重试。'}
          </p>
        )}
        {preview.isSuccess && (
          <>
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              建议移除 {blocks.length - preview.data.keepCount} 块（导航 / 广告 /
              短链接列表），标题、段落与图片默认保留。逐块可自行调整。
            </p>
            <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
              {blocks.map((block) => (
                <li key={block.id}>
                  <label
                    className={cx(
                      'flex items-start gap-2 rounded-[var(--lumi-radius-md)] border p-2 text-xs',
                      selected.has(block.id)
                        ? 'border-[var(--lumi-border)]'
                        : 'border-[var(--lumi-danger)]/30 opacity-70',
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(block.id)}
                      onChange={() => toggle(block.id)}
                      aria-label={`保留块：${block.id}`}
                      className="mt-0.5"
                    />
                    <span
                      className={cx(
                        'shrink-0 rounded-[var(--lumi-radius-full) px-1.5 py-0.5 text-[10px]',
                        'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]',
                      )}
                      data-cleanup-reason={block.reason}
                    >
                      {reasonLabel[block.reason]}
                    </span>
                    <span className="min-w-0 flex-1 line-clamp-3 text-[var(--lumi-text-secondary)]">
                      {block.text}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Dialog>
  )
}
