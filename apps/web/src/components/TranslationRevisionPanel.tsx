/** TranslationRevisionPanel — F062 译文手工纠错与保护（服务端引擎）。
 *
 * - 每段可编辑译文：textarea 保存修订 / 撤销修订 / 查看机器原文；
 * - 修订失配标记：保存修订后源段已变化 → 「原文已更新」徽标；
 * - 重新生成：默认保留已修订段；显式「全部覆盖」才撤销并重译；
 * - N086：每段「不翻译」开关（服务端持久；标记块不再参与生成，
 *   已有缓存译文照常展示，没有则诚实显示原文）；
 * - N083：受保护术语保留报告（✓ 已保留 / 未保护原因）；
 * - N082：数字校验（基于可见数字差异，非语义判断），逐块列出差异，
 *   点击定位到正文对应块；
 * - 修订/机器原文/差异上下文一律按纯文本渲染（React 文本节点，
 *   绝不 HTML 注入）。 */

import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Calculator, PencilLine } from 'lucide-react'
import { scrollToBlock } from '../lib/linked-scroll'
import {
  useGenerateTranslationSegmentsMutation,
  useNoTranslateBlockMutation,
  useTranslationSegmentRevisionMutation,
} from '../api/queries'
import { getTranslationVerification } from '../api/client'
import type {
  TranslationSegmentState,
  TranslationVerificationView,
} from '../api/types'
import type { TranslationSegmentBlockInput } from '../api/client'
import type { ArticleBlock } from '../lib/translation-blocks'
import { Button } from './ui/Button'
import { Switch } from './ui/Switch'
import { cx } from './ui/cx'

function preview(text: string | null | undefined, max = 24): string {
  const clean = (text ?? '').replace(/\s+/g, ' ').trim()
  return clean.length > max ? `${clean.slice(0, max)}…` : clean
}

const FINDING_KIND_LABELS: Record<string, string> = {
  missing: '缺失',
  changed: '变动',
  added: '新增',
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
  const noTranslate = useNoTranslateBlockMutation(entryRef)

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
  const toggleNoTranslate = (marked: boolean) => {
    if (selected === null) return
    setActionError(null)
    noTranslate.mutate(
      { blockIndex: selected.index, marked },
      { onError: (e) => setActionError(e instanceof Error ? e.message : '操作失败，请稍后重试。') },
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
        <NumberVerificationSection entryRef={entryRef} />
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
                  {s.noTranslate ? '（不翻译）' : ''}
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
              {/* N086：不翻译开关（持久到服务端；标记块不参与生成）。 */}
              <div className="flex items-center gap-2">
                <Switch
                  checked={selected.noTranslate}
                  label="不翻译此段"
                  onCheckedChange={toggleNoTranslate}
                />
                <span>不翻译此段</span>
                {selected.noTranslate && selected.translatedText && (
                  <span className="text-[var(--lumi-text-tertiary)]">
                    已有译文将继续显示
                  </span>
                )}
              </div>
              {/* N083：受保护术语保留报告（诚实：未保护给原因）。 */}
              {selected.protectedTerms.length > 0 && (
                <ul className="flex flex-col gap-0.5" data-lumi-protect-report="">
                  {selected.protectedTerms.map((p) => (
                    <li key={p.term} className="text-[var(--lumi-text-tertiary)]">
                      {p.protected ? (
                        <>
                          <span className="text-[var(--lumi-accent-text)]">✓</span>{' '}
                          「{p.term}」已保留
                          {p.count > 1 ? `（${p.count} 处）` : ''}
                        </>
                      ) : (
                        <>
                          <span className="text-[var(--lumi-warning, var(--lumi-text-secondary))]">⚠</span>{' '}
                          「{p.term}」未保留：{p.reason === 'term not found in translation' ? '译文中未找到该词' : p.reason}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
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

/** N082 数字校验：按需请求 + 逐块差异列表 + 点击定位到块。
 * 诚实文案：基于可见数字差异，非语义判断（CJK 数字不在范围）。 */
function NumberVerificationSection({ entryRef }: { entryRef: string }) {
  const [view, setView] = useState<TranslationVerificationView | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setBusy(true)
    setError(null)
    getTranslationVerification(entryRef)
      .then((result) => setView(result))
      .catch(() => setError('数字校验失败，请稍后重试。'))
      .finally(() => setBusy(false))
  }

  const findings = (view?.blocks ?? []).flatMap((block) =>
    block.findings.map((finding) => ({ blockIndex: block.blockIndex, finding })),
  )

  return (
    <span data-lumi-number-verification="" className="inline-flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={run}
        disabled={busy}
        aria-expanded={view !== null}
        className="inline-flex items-center gap-1 font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:opacity-60"
      >
        <Calculator aria-hidden className="size-3.5" />
        {view === null ? '数字校验' : `数字校验（${view.totalFindings} 处差异）`}
      </button>
      {busy && <span className="text-[var(--lumi-text-tertiary)]">校验中…</span>}
      {error !== null && (
        <span role="alert" className="text-[var(--lumi-danger)]">{error}</span>
      )}
      {view !== null && (
        <span className="flex w-full flex-col gap-1">
          <span className="text-[var(--lumi-text-tertiary)]">
            基于可见数字差异，非语义判断（中文数字不在范围内）。
          </span>
          {findings.length === 0 ? (
            <span className="text-[var(--lumi-text-tertiary)]">
              {view.blocks.length > 0 ? '未发现可见数字差异。' : '当前没有可校验的译文。'}
            </span>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {findings.map(({ blockIndex, finding }) => (
                <li key={`${blockIndex}-${finding.kind}-${finding.token}`}>
                  <button
                    type="button"
                    onClick={() => {
                      const container =
                        document.querySelector<HTMLElement>('[data-reader-body]')
                      if (container !== null) scrollToBlock(container, blockIndex)
                    }}
                    className="text-left text-[var(--lumi-text-secondary)] underline-offset-2 hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                  >
                    第 {blockIndex + 1} 段 ·{' '}
                    <span className="font-medium">{FINDING_KIND_LABELS[finding.kind] ?? finding.kind}</span>{' '}
                    {finding.token}
                    {finding.kind !== 'added' && finding.sourceContext
                      ? ` · 原文：…${finding.sourceContext}…`
                      : ''}
                    {finding.kind !== 'missing' && finding.translatedContext
                      ? ` · 译文：…${finding.translatedContext}…`
                      : ''}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </span>
      )}
    </span>
  )
}
