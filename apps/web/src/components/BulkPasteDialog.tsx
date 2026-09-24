/** BulkPasteDialog — N121 粘贴多链接收件箱（书签页 / 剪藏页共用）。
 *
 * textarea 逐行粘贴 URL → POST /library/bulk-links（≤50 条）→ 逐条
 * created | duplicate | failed 结果列表（单条失败绝不影响其余条目）。
 * 提交前由本组件剥掉空行；失败项在结果区如实带 reason。
 */

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useBulkLinksMutation } from '../api/queries'
import type { BulkLinkResultItem } from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'

const textareaCls = cx(
  'w-full resize-y rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
  'px-3 py-2 font-mono text-xs leading-relaxed text-[var(--lumi-text-primary)]',
  'placeholder:text-[var(--lumi-text-tertiary)]',
  'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
)

const statusLabel: Record<BulkLinkResultItem['status'], string> = {
  created: '已创建',
  duplicate: '重复',
  failed: '失败',
}

export function BulkPasteDialog({
  target,
  onClose,
}: {
  target: 'bookmark' | 'clip'
  onClose: () => void
}) {
  const [text, setText] = useState('')
  const [results, setResults] = useState<BulkLinkResultItem[] | null>(null)
  const [summary, setSummary] = useState<
    { created: number; duplicate: number; failed: number } | null
  >(null)
  const mutation = useBulkLinksMutation()

  const urls = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
  const pending = mutation.isPending
  const canSubmit = urls.length > 0 && urls.length <= 50 && !pending

  const submit = () => {
    if (!canSubmit) return
    mutation.mutate(
      { urls, target },
      {
        onSuccess: (data) => {
          setResults(data.items)
          setSummary({
            created: data.created,
            duplicate: data.duplicate,
            failed: data.failed,
          })
        },
      },
    )
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={target === 'bookmark' ? '批量粘贴书签' : '批量粘贴剪藏链接'}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
          <Button
            variant="primary"
            size="sm"
            data-bulk-paste-submit=""
            onClick={submit}
            disabled={!canSubmit}
          >
            {pending ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : null}
            {pending
              ? '处理中…'
              : target === 'bookmark'
                ? '全部存为书签'
                : '全部生成剪藏'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-sm" data-bulk-paste-dialog="">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          每行一个链接（最多 50 条；空行忽略）。逐条独立处理：重复的自动跳过，
          单条失败不影响其余。
        </p>
        <textarea
          rows={7}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={'https://example.com/a\nhttps://example.com/b'}
          aria-label="批量链接（每行一个）"
          className={textareaCls}
        />
        {urls.length > 50 && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            一次最多 50 条（当前 {urls.length} 条）。
          </p>
        )}
        {mutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {mutation.error instanceof Error
              ? mutation.error.message
              : '批量处理失败，请稍后重试。'}
          </p>
        )}
        {results !== null && summary !== null && (
          <div
            role="status"
            className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5"
            data-bulk-paste-results=""
          >
            <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
              处理完成：新建 {summary.created}，重复 {summary.duplicate}
              {summary.failed > 0 ? `，失败 ${summary.failed}` : ''}。
            </p>
            <ul className="flex max-h-52 flex-col gap-0.5 overflow-y-auto">
              {results.map((item, index) => (
                <li
                  key={`${item.url}-${index}`}
                  className="flex min-w-0 items-baseline gap-1.5 text-xs"
                  data-bulk-result={item.status}
                >
                  <span
                    className={cx(
                      'shrink-0',
                      item.status === 'created' && 'text-[var(--lumi-success)]',
                      item.status === 'duplicate' &&
                        'text-[var(--lumi-text-tertiary)]',
                      item.status === 'failed' && 'text-[var(--lumi-danger)]',
                    )}
                  >
                    {statusLabel[item.status]}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
                    {item.url}
                  </span>
                  {item.reason != null && item.reason !== '' && (
                    <span className="shrink-0 text-[var(--lumi-danger)]">
                      {item.reason}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Dialog>
  )
}
