/** TranslationRevisionPanel — F062 译文手工纠错与保护（服务端引擎）。
 *
 * - 每段可编辑译文：textarea 保存修订 / 撤销修订 / 查看机器原文；
 * - 修订失配标记：保存修订后源段已变化 → 「原文已更新」徽标；
 * - 重新生成：默认保留已修订段；显式「全部覆盖」才撤销并重译；
 * - 修订与机器原文一律按纯文本渲染（React 文本节点，绝不 HTML 注入）。 */

import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, PencilLine } from 'lucide-react'
import {
  useGenerateTranslationSegmentsMutation,
  useTranslationSegmentRevisionMutation,
} from '../api/queries'
import type { TranslationSegmentState } from '../api/types'
import type { TranslationSegmentBlockInput } from '../api/client'
import type { ArticleBlock } from '../lib/translation-blocks'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

function preview(text: string | null | undefined, max = 24): string {
  const clean = (text ?? '').replace(/\s+/g, ' ').trim()
  return clean.length > max ? `${clean.slice(0, max)}…` : clean
}

export default function TranslationRevisionPanel({
  entryRef,
  segments,
  blocks,
}: {
  entryRef: string
  segments: TranslationSegmentState[]
  blocks: ArticleBlock[] | null
}) {
  const [open, setOpen] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const revision = useTranslationSegmentRevisionMutation(entryRef)
  const generate = useGenerateTranslationSegmentsMutation(entryRef)

  const candidates = useMemo(
    () => segments.filter((s) => s.status !== 'failed' || s.translatedText !== null),
    [segments],
  )
  const revisedCount = segments.filter((s) => s.userRevision !== null && s.userRevision !== undefined).length
  const selected = candidates.find((s) => s.index === selectedIndex) ?? candidates[0] ?? null
  const sourceBlock = blocks?.find((b) => b.index === selected?.index) ?? null

  useEffect(() => {
    setDraft(selected?.userRevision ?? selected?.translatedText ?? '')
  }, [selected?.index, selected?.userRevision, selected?.translatedText])

  if (candidates.length === 0) return null

  const save = () => {
    if (selected === null || draft.trim() === '') return
    setActionError(null)
    revision.mutate(
      { blockIndex: selected.index, text: draft },
      { onError: (e) => setActionError(e instanceof Error ? e.message : '保存失败，请稍后重试。') },
    )
  }
  const undo = () => {
    if (selected === null) return
    setActionError(null)
    revision.mutate(
      { blockIndex: selected.index, text: null },
      { onError: (e) => setActionError(e instanceof Error ? e.message : '撤销失败，请稍后重试。') },
    )
  }
  const regenerate = (overwriteRevisions: boolean) => {
    if (blocks === null || blocks.length === 0) return
    const inputs: TranslationSegmentBlockInput[] = blocks.map((b) => ({ index: b.index, text: b.text }))
    setActionError(null)
    generate.mutate(
      { blocks: inputs, overwriteRevisions },
      { onError: (e) => setActionError(e instanceof Error ? e.message : '重新生成失败，请稍后重试。') },
    )
  }

  return (
    <section
      data-lumi-translation-revisions=""
      className="mt-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-xs"
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex items-center gap-1 font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <PencilLine aria-hidden className="size-3.5" />
          译文修订{revisedCount > 0 ? `（${revisedCount} 段已修订）` : ''}
        </button>
        {open && (
          <>
            <Button
              size="sm"
              variant="ghost"
              disabled={generate.isPending}
              onClick={() => regenerate(false)}
            >
              重新生成（保留我的修订）
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={generate.isPending}
              onClick={() => {
                if (window.confirm('全部覆盖将撤销所有手工修订并重新翻译，确定？')) {
                  regenerate(true)
                }
              }}
            >
              全部覆盖
            </Button>
          </>
        )}
      </div>
      {open && (
        <div className="mt-2 flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-[var(--lumi-text-secondary)]">
            选择段落
            <select
              aria-label="选择要修订的段落"
              value={selected?.index ?? ''}
              onChange={(e) => setSelectedIndex(Number(e.target.value))}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs"
            >
              {candidates.map((s) => (
                <option key={s.index} value={s.index}>
                  第 {s.index + 1} 段 · {preview(s.userRevision ?? s.translatedText)}
                </option>
              ))}
            </select>
          </label>
          {selected !== null && (
            <>
              {selected.revisionStale && (
                <p className="inline-flex items-center gap-1 text-[var(--lumi-warning, var(--lumi-text-secondary))]">
                  <AlertCircle aria-hidden className="size-3" />
                  原文已更新：该段修订对应的源文已变化。
                </p>
              )}
              {sourceBlock !== null && (
                <p className="max-h-16 overflow-y-auto text-[var(--lumi-text-tertiary)]">
                  原文：{sourceBlock.text}
                </p>
              )}
              {selected.translatedText !== null && (
                <p className="text-[var(--lumi-text-tertiary)]">
                  机器原文：{selected.translatedText}
                </p>
              )}
              <textarea
                aria-label={`第 ${selected.index + 1} 段译文修订`}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={3}
                maxLength={10000}
                className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs text-[var(--lumi-text-primary)]"
              />
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  disabled={revision.isPending || draft.trim() === ''}
                  onClick={save}
                >
                  保存修订
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={revision.isPending || (selected.userRevision ?? null) === null}
                  onClick={undo}
                >
                  撤销修订
                </Button>
                {selected.userRevision != null && (
                  <span className={cx('text-[var(--lumi-text-tertiary)]')}>已修订</span>
                )}
              </div>
            </>
          )}
          {(actionError !== null || generate.isPending) && (
            <p role="alert" className="text-[var(--lumi-danger)]">
              {generate.isPending ? '正在重新生成…' : actionError}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
