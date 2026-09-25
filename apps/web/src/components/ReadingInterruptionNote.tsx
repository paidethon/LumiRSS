/** N045 阅读中断便签（Reader 内挂载；自包含，不侵入 Reader 逻辑）。
 *
 * - 追踪：document capture 滚动监听测 `[data-reader-body]` 的滚动比与
 *   当前段落（`[data-para-id]`，与 F056 锚点同构）——只读，不写任何
 *   进度数据；
 * - 离开提示：切走/关闭一篇滚动超过 30% 的文章时，弹一句话便签
 *   （≤200 字符，可跳过）；保存走 PUT /entries/{ref}/note（latest-wins）；
 * - 重开回显：打开文章时取便签（无则零噪音），显示「上次留笔」条 +
 *  「到上次的位置」——滚动到保存的段落位置（尽力而为：段落缺失则
 *   回到顶部，绝不伪造定位成功）。
 */

import { useEffect, useRef, useState } from 'react'
import { NotebookPen, X } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useReadingNote, useSaveReadingNoteMutation } from '../api/queries'
import { useReaderUi } from '../store/reader-ui'
import { Button } from './ui/Button'

/** 滚动比超过该阈值（离开时）才提示便签——低于 30% 算「没怎么读」。 */
const PROMPT_RATIO = 0.3

interface ReaderMeasure {
  ratio: number
  paraId: string | null
}

/** 模块级：当前正文滚动量测（最近的 capture 滚动事件；entryRef 由
 * hook 关联——DOM 本身不知道条目身份）。 */
const lastMeasure: { entryRef: string | null; data: ReaderMeasure } = {
  entryRef: null,
  data: { ratio: 0, paraId: null },
}

function measureReaderBody(): ReaderMeasure {
  const container = document.querySelector('[data-reader-body]')
  if (!(container instanceof HTMLElement)) return { ratio: 0, paraId: null }
  const max = container.scrollHeight - container.clientHeight
  const ratio = max > 0 ? Math.min(1, Math.max(0, container.scrollTop / max)) : 0
  const article = container.querySelector('.lumi-reader-article')
  const containerTop = container.getBoundingClientRect().top
  let paraId: string | null = null
  if (article !== null) {
    for (const el of article.querySelectorAll<HTMLElement>('[data-para-id]')) {
      if (el.getBoundingClientRect().top > containerTop + 80) break
      paraId = el.dataset.paraId ?? paraId
    }
  }
  return { ratio, paraId }
}

/** 自包含：entryRef 直接读 reader-ui store（挂载点在 Reader 外层——
 * 这样「关闭文章」的跳变也能被本组件观察到）。 */
export function ReadingInterruptionNote() {
  const entryRef = useReaderUi((s) => s.selectedEntryRef)
  const queryClient = useQueryClient()
  const saveMutation = useSaveReadingNoteMutation()
  const [pending, setPending] = useState<{
    entryRef: string
    ratio: number
    paraId: string | null
  } | null>(null)
  const [noteText, setNoteText] = useState('')
  // 重开回显条：按 entryRef 拉取便签（404 → null，零噪音）。
  const noteQuery = useReadingNote(entryRef)
  const [restoreVisible, setRestoreVisible] = useState(true)

  // 滚动量测：capture + passive，只写模块级量测值。
  useEffect(() => {
    lastMeasure.entryRef = entryRef
    const onScroll = () => {
      const data = measureReaderBody()
      lastMeasure.data = data
    }
    document.addEventListener('scroll', onScroll, { passive: true, capture: true })
    return () => {
      document.removeEventListener('scroll', onScroll, { capture: true })
    }
  }, [entryRef])

  // 离开检测：entryRef 变化（含关闭 = null）时看**前一篇**的滚动比。
  const prevRefRef = useRef<string | null>(null)
  useEffect(() => {
    const previous = prevRefRef.current
    prevRefRef.current = entryRef
    if (previous === null || previous === entryRef) return
    if (lastMeasure.entryRef !== previous) return
    const { ratio, paraId } = lastMeasure.data
    if (ratio < PROMPT_RATIO) return
    // 离开的是读了一半的文章 → 提示一句话便签（可跳过）。
    setPending({ entryRef: previous, ratio, paraId })
    setNoteText('')
    setRestoreVisible(true)
  }, [entryRef])

  // 重开回显：新文章的便签到达时重置展示状态。
  const noteRef = useRef<string | null>(null)
  const note = noteQuery.data ?? null
  useEffect(() => {
    if (note !== null && note.entryRef !== noteRef.current) {
      setRestoreVisible(true)
    }
    noteRef.current = note?.entryRef ?? null
  }, [note])

  if (entryRef === null && pending === null) return null

  return (
    <>
      {/* 重开回显：显示便签 + 回到保存段落 */}
      {entryRef !== null && note !== null && restoreVisible && (
        <div
          role="status"
          data-testid="reading-note-restore"
          className="mx-4 mb-1 flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-accent-soft)] px-2.5 py-1.5 text-xs"
        >
          <NotebookPen aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-accent-text)]" />
          <span className="min-w-0 flex-1 truncate text-[var(--lumi-accent-text)]">
            上次留笔：{note.note}
          </span>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              // 定位到保存段落（尽力而为；找不到段落 = 无操作）。
              const article = document.querySelector('.lumi-reader-article')
              const target =
                note.paraId !== null && article !== null
                  ? article.querySelector<HTMLElement>(`[data-para-id="${CSS.escape(note.paraId)}"]`)
                  : null
              if (target !== null) {
                target.scrollIntoView({ block: 'start' })
              } else {
                const container = document.querySelector('[data-reader-body]')
                if (container instanceof HTMLElement) container.scrollTop = 0
              }
              setRestoreVisible(false)
            }}
          >
            到上次的位置
          </Button>
          <button
            type="button"
            aria-label="关闭留笔回显"
            onClick={() => setRestoreVisible(false)}
            className="flex min-h-7 items-center rounded px-1 text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        </div>
      )}

      {/* 离开提示：一句话便签（可跳过） */}
      {pending !== null && (
        <div
          role="dialog"
          aria-modal="false"
          aria-label="阅读中断便签"
          data-testid="reading-note-prompt"
          className="mx-4 mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2.5"
        >
          <form
            className="flex flex-wrap items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault()
              const text = noteText.trim()
              if (text === '') return
              saveMutation.mutate(
                { entryRef: pending.entryRef, note: text, paraId: pending.paraId },
                {
                  onSuccess: () => {
                    void queryClient.invalidateQueries({
                      queryKey: ['entry', pending.entryRef, 'note'],
                    })
                  },
                  onSettled: () => setPending(null),
                },
              )
            }}
          >
            <NotebookPen aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-text-tertiary)]" />
            <input
              autoFocus
              maxLength={200}
              value={noteText}
              onChange={(event) => setNoteText(event.target.value)}
              placeholder="留一句话给回头的自己（可跳过）"
              aria-label="阅读中断便签"
              data-testid="reading-note-input"
              className="min-h-8 min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs"
            />
            <Button size="sm" variant="primary" type="submit" disabled={saveMutation.isPending || noteText.trim() === ''}>
              保存
            </Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setPending(null)}>
              跳过
            </Button>
          </form>
        </div>
      )}
    </>
  )
}

export default ReadingInterruptionNote
