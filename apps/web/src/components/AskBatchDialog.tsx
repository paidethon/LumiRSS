/** AskBatchDialog — F065 多篇共同问答（EntryList 多选 ≥1）。
 *
 * - 范围清单（可移除）+ 问题输入（≤2000）；
 * - 回答纯文本渲染 + 引用文章 chips（点击打开该文并关闭对话框）；
 * - 诚实状态：加载 / 错误重试；跳过条目如实展示。 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertCircle, HelpCircle, X } from 'lucide-react'
import { askBatchEntries, compareEntries, type AskBatchResult, type CompareResult } from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import { Dialog } from './ui/Dialog'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export interface AskBatchTarget {
  ref: string
  title: string
}

export function AskBatchDialog({
  open,
  onClose,
  targets,
  onRemove,
}: {
  open: boolean
  onClose: () => void
  targets: AskBatchTarget[]
  onRemove: (ref: string) => void
}) {
  const [question, setQuestion] = useState('')
  // F067：模式切换（提问 / 对照分析）；旧对照结果保留在组件态供重试对照。
  const [mode, setMode] = useState<'ask' | 'compare'>('ask')
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null)
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const ask = useMutation({
    mutationFn: () =>
      askBatchEntries({
        entryRefs: targets.map((t) => t.ref),
        question: question.trim(),
      }),
  })
  const compare = useMutation({
    mutationFn: () => compareEntries({ entryRefs: targets.map((t) => t.ref) }),
    onSuccess: (result) => setCompareResult(result),
  })

  const close = () => {
    onClose()
    setQuestion('')
    ask.reset()
  }

  const openCitation = (ref: string) => {
    selectEntry(ref)
    close()
  }

  return (
    <Dialog open={open} onClose={close} title="基于所选">
      <div className="flex flex-col gap-3">
        {/* F067：模式切换（同一多选对话框的「提问 / 对照分析」两页） */}
        <div role="tablist" aria-label="分析模式" className="flex items-center gap-1">
          {(
            [
              ['ask', '基于所选提问'],
              ['compare', '对照分析'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              onClick={() => setMode(value)}
              className={cx(
                'min-h-7 rounded-[var(--lumi-radius-full)] px-2.5 text-xs font-medium transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                mode === value
                  ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                  : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            范围（{targets.length} 篇，回答仅基于这些文章）
          </span>
          <ul className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
            {targets.map((t) => (
              <li
                key={t.ref}
                className="flex max-w-full items-center gap-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] py-0.5 pe-1 ps-2.5 text-xs text-[var(--lumi-accent-text)]"
              >
                <span className="max-w-40 truncate">{t.title}</span>
                <button
                  type="button"
                  onClick={() => onRemove(t.ref)}
                  aria-label={`从范围移除「${t.title}」`}
                  className="relative flex size-5 items-center justify-center rounded-full transition-colors after:absolute after:-inset-y-1.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <X aria-hidden className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        </div>
        {mode === 'ask' && (
          <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            问题
            <textarea
              aria-label="问题输入"
              value={question}
              rows={3}
              maxLength={2000}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="例如：这几篇文章的观点有哪些异同？"
              className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
            />
          </label>
        )}
        {mode === 'compare' && (
          <p className="flex items-center gap-1 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2.5 py-2 text-xs text-[var(--lumi-text-secondary)]">
            <AlertCircle aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-text-tertiary)]" />
            对照分析为模型生成，可能不准确；证据引文会与原文比对并标注是否核验通过。
          </p>
        )}
        <div className="flex items-center justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={close}>
            关闭
          </Button>
          {mode === 'ask' ? (
            <Button
              size="sm"
              variant="primary"
              disabled={targets.length === 0 || question.trim() === '' || ask.isPending}
              onClick={() => ask.mutate()}
            >
              <HelpCircle aria-hidden className="size-3.5" />
              {ask.isPending ? '提问中…' : '提问'}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="primary"
              disabled={targets.length < 2 || compare.isPending}
              onClick={() => compare.mutate()}
            >
              {compare.isPending ? '分析中…' : '开始对照分析'}
            </Button>
          )}
        </div>
        {mode === 'ask' && ask.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {ask.error instanceof Error ? ask.error.message : '提问失败，请稍后重试。'}
          </p>
        )}
        {mode === 'ask' && ask.data !== undefined && (
          <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-3" data-lumi-ask-answer="">
            {/* 回答按纯文本渲染（React 文本节点），绝不 HTML 注入 */}
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
              {ask.data.answer}
            </p>
            {ask.data.skipped.length > 0 && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                已跳过 {ask.data.skipped.length} 篇不可用条目。
              </p>
            )}
            {ask.data.citations.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-[var(--lumi-text-tertiary)]">引用：</span>
                {ask.data.citations.map((c) => {
                  const target = targets.find((t) => t.ref === c.entryRef)
                  return (
                    <button
                      key={`${c.index}-${c.entryRef}`}
                      type="button"
                      onClick={() => openCitation(c.entryRef)}
                      title={target?.title ?? c.entryRef}
                      className="max-w-52 truncate rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-xs text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                    >
                      [{c.index}] {target?.title ?? c.entryRef}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )}
        {/* F067：对照分析结果（分节渲染；旧结果保留，失败可重试） */}
        {mode === 'compare' && (compare.isError || compareResult !== null) && (
          <div
            data-lumi-compare-result=""
            className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-3"
          >
            {compareResult !== null && (
              <>
                {compareResult.commonPoints.length > 0 && (
                  <section>
                    <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">共同点</h4>
                    <ul className="mt-1 list-disc ps-4 text-xs text-[var(--lumi-text-secondary)]">
                      {compareResult.commonPoints.map((point, i) => (
                        <li key={i}>{point}</li>
                      ))}
                    </ul>
                  </section>
                )}
                {compareResult.differences.length > 0 && (
                  <section>
                    <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">分歧</h4>
                    {compareResult.differences.map((d, i) => (
                      <div key={i} className="mt-1.5">
                        <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">{d.topic}</p>
                        <ul className="mt-0.5 flex flex-col gap-0.5">
                          {d.positions.map((p, j) => {
                            const target = compareResult.materials.find((m) => m.index === p.entry)
                            return (
                              <li key={j} className="text-xs text-[var(--lumi-text-secondary)]">
                                <button
                                  type="button"
                                  onClick={() => target && openCitation(target.entryRef)}
                                  className="me-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-1.5 text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                                  title={target?.title}
                                >
                                  [{p.entry}]
                                </button>
                                {p.claim}
                              </li>
                            )
                          })}
                        </ul>
                      </div>
                    ))}
                  </section>
                )}
                {compareResult.evidence.length > 0 && (
                  <section>
                    <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">证据</h4>
                    <ul className="mt-1 flex flex-col gap-1">
                      {compareResult.evidence.map((e, i) => (
                        <li key={i} className="text-xs text-[var(--lumi-text-secondary)]">
                          <button
                            type="button"
                            onClick={() => {
                              const target = compareResult.materials.find((m) => m.index === e.entry)
                              if (target) openCitation(target.entryRef)
                            }}
                            className="me-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-1.5 text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                            title={compareResult.materials.find((m) => m.index === e.entry)?.title}
                          >
                            [{e.entry}]
                          </button>
                          “{e.quote}”
                          <span
                            className={cx(
                              'ms-1 rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[11px]',
                              e.verified
                                ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]'
                                : 'bg-[var(--lumi-danger-soft, var(--lumi-surface-selected))] text-[var(--lumi-danger)]',
                            )}
                          >
                            {e.verified ? '已核验' : '未验证'}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {compareResult.uncertainties.length > 0 && (
                  <section>
                    <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">不确定</h4>
                    <ul className="mt-1 list-disc ps-4 text-xs text-[var(--lumi-text-tertiary)]">
                      {compareResult.uncertainties.map((u, i) => (
                        <li key={i}>{u}</li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            )}
            {compare.isError && (
              <div className="flex flex-wrap items-center gap-2">
                <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                  {compare.error instanceof Error ? compare.error.message : '对照分析失败。'}
                </p>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={compare.isPending || targets.length < 2}
                  onClick={() => compare.mutate()}
                >
                  重试
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </Dialog>
  )
}

export type { AskBatchResult }
