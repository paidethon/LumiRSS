/** ReaderSummary — 0015 Gate 7：Reader 内的按需 AI 摘要卡片。
 *
 * 状态机（诚实呈现，绝不渲染神秘的空白区域）：
 *   loading        → 细骨架
 *   not_configured → 「AI 未配置」+ 去设置的说明（503 ai_not_configured）
 *   not_generated  → 「输入预览 + 范围选择 + AI 摘要」按钮（点击 = 唯一
 *                    可能产生付费调用的动作；F025：取消不发请求）
 *   generating     → 转圈 + 「正在生成摘要…」
 *   success        → 摘要正文按句子渲染（F026：点击定位原文）+
 *                    版本选择器（F027：切换/双栏对比）+ model · 时间
 *   failed         → 按 failureType 的稳定中文说明 + 重试
 *
 * F025 诚实口径：只显示字符数（「约 N 字符（token 计数以 Provider 为
 * 准）」），绝不估算 token。摘要输出按纯文本渲染，不经过 HTML 路径。
 */

import { useMemo, useState } from 'react'
import {
  AlertCircle,
  ChevronDown,
  Columns2,
  Loader2,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import {
  useActivateSummaryVersionMutation,
  useEntrySummary,
  useGenerateSummaryScopedMutation,
} from '../api/queries'
import type { SummaryVersionItem } from '../api/client'
import { ApiError } from '../api/client'
import { locateSentence, splitSentences } from '../lib/locate-sentence'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'
import { dateTimeFormatter } from '../lib/date-format'
import {
  aiFailureText,
  aiFailureTypeText,
  type AiFailureWording,
} from '../lib/ai-failure-text'

/** 摘要功能的特色文案；通用错误文案在 lib/ai-failure-text。 */
const WORDING: AiFailureWording = {
  fallback: '生成失败，请重试。',
  interrupted: '上次生成被中断，请重试。',
  contentUnavailable: '这篇文章没有可摘要的正文内容。',
}

const SCOPE_OPTIONS = [
  { label: '全文', value: undefined },
  { label: '8k 字符', value: 8000 },
  { label: '4k 字符', value: 4000 },
  { label: '2k 字符', value: 2000 },
] as const

function formatGeneratedAt(value: string | null | undefined): string {
  if (value === null || value === undefined) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateTimeFormatter.format(date)
}

function failureText(error: unknown): string {
  return aiFailureText(error, WORDING)
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cx(
        'rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5',
        className,
      )}
    >
      {children}
    </div>
  )
}

function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-1.5 text-sm font-medium text-[var(--lumi-text-primary)]">
      <Sparkles aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
      {children}
    </p>
  )
}

/** F025：输入预览（标题/正文字符数 + 截断选择 + 诚实口径说明）。 */
function InputPreview({
  titleChars,
  bodyChars,
  scope,
  onScopeChange,
}: {
  titleChars: number
  bodyChars: number
  scope: number | undefined
  onScopeChange: (value: number | undefined) => void
}) {
  const effective =
    scope === undefined ? Math.min(bodyChars, 12000) : Math.min(bodyChars, scope)
  return (
    <div
      className="mt-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2.5 py-2 text-xs"
      data-lumi-ai-input-preview=""
    >
      <p className="flex flex-wrap items-center gap-2 text-[var(--lumi-text-secondary)]">
        <span>
          输入预览：标题 {titleChars} 字符 · 正文 {bodyChars} 字符
        </span>
        <select
          aria-label="输入范围"
          value={scope === undefined ? 'full' : String(scope)}
          onChange={(e) =>
            onScopeChange(
              e.target.value === 'full' ? undefined : Number(e.target.value),
            )
          }
          className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs"
        >
          {SCOPE_OPTIONS.map((option) => (
            <option key={option.label} value={option.value === undefined ? 'full' : String(option.value)}>
              {option.label}
            </option>
          ))}
        </select>
      </p>
      <p className="mt-1 text-[var(--lumi-text-tertiary)]">
        本次约发送 {effective} 字符（token 计数以 Provider 为准）
      </p>
    </div>
  )
}

/** F026：摘要句子列表（点击定位原文；找不到诚实徽标）。 */
function SummarySentences({
  text,
  articleText,
}: {
  text: string
  articleText: string | undefined
}) {
  const [misses, setMisses] = useState<ReadonlySet<number>>(new Set())
  const sentences = useMemo(() => splitSentences(text), [text])

  function locate(index: number, sentence: string) {
    if (articleText === undefined) return
    const offset = locateSentence(sentence, articleText)
    if (offset < 0) {
      setMisses((prev) => new Set(prev).add(index))
      return
    }
    setMisses((prev) => {
      const next = new Set(prev)
      next.delete(index)
      return next
    })
    document.dispatchEvent(
      new CustomEvent('lumi:locate-evidence', { detail: { sentence } }),
    )
  }

  return (
    <div className="mt-2.5 whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]" data-lumi-summary-sentences="">
      {sentences.map((sentence, index) => (
        <span key={index}>
          {articleText !== undefined ? (
            <button
              type="button"
              title="点击在正文中定位"
              onClick={() => locate(index, sentence)}
              className="text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              {sentence}
            </button>
          ) : (
            <span>{sentence}</span>
          )}
          {misses.has(index) ? (
            <span
              className="mx-0.5 inline-block rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 align-middle text-[10px] text-[var(--lumi-text-tertiary)]"
              data-lumi-evidence-miss=""
            >
              未在原文定位
            </span>
          ) : null}
          {' '}
        </span>
      ))}
    </div>
  )
}

/** F027：简单逐行 diff（旧→新；增行/删行标色）。 */
function lineDiff(oldText: string, newText: string): Array<{ kind: 'same' | 'add' | 'del'; text: string }> {
  const a = oldText.split('\n')
  const b = newText.split('\n')
  const result: Array<{ kind: 'same' | 'add' | 'del'; text: string }> = []
  let i = 0
  let j = 0
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      result.push({ kind: 'same', text: a[i] })
      i += 1
      j += 1
    } else if (j < b.length && (i >= a.length || !b.slice(j + 1).includes(a[i]))) {
      result.push({ kind: 'add', text: b[j] })
      j += 1
    } else {
      result.push({ kind: 'del', text: a[i] })
      i += 1
    }
  }
  return result
}

function VersionsPanel({
  entryRef,
  versions,
  activeSummary,
}: {
  entryRef: string
  versions: SummaryVersionItem[]
  activeSummary: string | null
}) {
  const activate = useActivateSummaryVersionMutation(entryRef)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [comparing, setComparing] = useState(false)
  if (versions.length === 0) return null
  const selected =
    versions.find((v) => v.versionId === selectedId) ?? versions[versions.length - 1]
  const previous = versions[versions.indexOf(selected) - 1]
  const diff = comparing && previous ? lineDiff(previous.summary, selected.summary) : null
  return (
    <div className="mt-2 border-t border-[var(--lumi-separator)] pt-2" data-lumi-summary-versions="">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <select
          aria-label="摘要版本"
          value={selected.versionId}
          onChange={(e) => setSelectedId(e.target.value)}
          className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
        >
          {versions.map((version) => (
            <option key={version.versionId} value={version.versionId}>
              {formatGeneratedAt(version.createdAt)} · {version.model}
            </option>
          ))}
        </select>
        {activate.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : null}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => activate.mutate(selected.versionId)}
          disabled={activate.isPending}
        >
          <ChevronDown aria-hidden className="size-3.5" />
          切换到此版本
        </Button>
        {previous ? (
          <Button size="sm" variant="ghost" aria-pressed={comparing} onClick={() => setComparing((v) => !v)}>
            <Columns2 aria-hidden className="size-3.5" />
            对比上一版
          </Button>
        ) : null}
      </div>
      {diff ? (
        <div className="mt-1.5 grid grid-cols-2 gap-1 text-[11px]" data-lumi-summary-diff="">
          <div>
            <p className="mb-0.5 text-[var(--lumi-text-tertiary)]">上一版</p>
            <pre className="whitespace-pre-wrap rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-1.5">
              {diff.map((row, index) =>
                row.kind === 'del' || row.kind === 'same' ? (
                  <span
                    key={index}
                    className={cx(
                      'block',
                      row.kind === 'del' && 'bg-[var(--lumi-danger-soft,rgba(220,38,38,0.12))] text-[var(--lumi-danger)]',
                    )}
                  >
                    {row.text}
                  </span>
                ) : null,
              )}
            </pre>
          </div>
          <div>
            <p className="mb-0.5 text-[var(--lumi-text-tertiary)]">所选版本</p>
            <pre className="whitespace-pre-wrap rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-1.5">
              {diff.map((row, index) =>
                row.kind === 'add' || row.kind === 'same' ? (
                  <span
                    key={index}
                    className={cx(
                      'block',
                      row.kind === 'add' && 'bg-[var(--lumi-success-soft,rgba(22,163,74,0.12))] text-[var(--lumi-success)]',
                    )}
                  >
                    {row.text}
                  </span>
                ) : null,
              )}
            </pre>
          </div>
        </div>
      ) : null}
      <p className="mt-1 text-[11px] text-[var(--lumi-text-tertiary)]">
        当前展示：{activeSummary === selected.summary ? '所选版本' : '最新生成'} · 共 {versions.length} 版
      </p>
    </div>
  )
}

export default function ReaderSummary({
  entryRef,
  articleTitle,
  articleText,
}: {
  entryRef: string
  articleTitle?: string
  articleText?: string
}) {
  const summary = useEntrySummary(entryRef)
  const generate = useGenerateSummaryScopedMutation(entryRef)
  const generating = generate.isPending
  const [scope, setScope] = useState<number | undefined>(undefined)

  if (summary.isPending) {
    return (
      <div className="mt-5" aria-label="正在加载摘要状态">
        <Skeleton className="h-14 w-full max-w-[36rem]" />
      </div>
    )
  }

  if (summary.isError) {
    const text = failureText(summary.error)
    const notConfigured = (summary.error as ApiError | null)?.type === 'ai_not_configured'
    const noContent =
      (summary.error as ApiError | null)?.type === 'ai_content_unavailable'
    return (
      <div className="mt-5">
        <Card>
          <CardTitle>{noContent ? '无法摘要' : notConfigured ? 'AI 摘要未配置' : '摘要状态不可用'}</CardTitle>
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
            {text}
          </p>
          {!notConfigured && !noContent && (
            <Button
              size="sm"
              variant="ghost"
              className="mt-2"
              onClick={() => summary.refetch()}
            >
              <RefreshCw aria-hidden className="size-3.5" />
              重试
            </Button>
          )}
        </Card>
      </div>
    )
  }

  const state = summary.data
  const notConfigured = (generate.error as ApiError | null)?.type === 'ai_not_configured'

  if (state.status === 'not_generated' || state.status === 'generating') {
    return (
      <div className="mt-5">
        <Card>
          <CardTitle>AI 摘要</CardTitle>
          {state.status === 'generating' ? (
            <p role="status" className="mt-2 flex items-center gap-1.5 text-sm text-[var(--lumi-text-secondary)]">
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
              正在生成摘要…
            </p>
          ) : (
            <>
              <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                按需生成，不会自动调用 AI；成功后同一篇文章直接读取缓存。
              </p>
              {notConfigured ? (
                <p role="alert" className="mt-2.5 flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-danger)]">
                  <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  AI 未配置：请先在设置中配置 API 地址与模型，再生成摘要。
                </p>
              ) : null}
              <InputPreview
                titleChars={articleTitle?.length ?? 0}
                bodyChars={articleText?.length ?? 0}
                scope={scope}
                onScopeChange={setScope}
              />
              <Button
                size="sm"
                className="mt-3"
                disabled={generating}
                onClick={() => generate.mutate(scope)}
              >
                {generating ? (
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                ) : (
                  <Sparkles aria-hidden className="size-3.5" />
                )}
                {generating ? '正在生成…' : 'AI 摘要'}
              </Button>
              {generate.isError && !notConfigured && (
                <p role="alert" className="mt-2.5 flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-danger)]">
                  <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  {failureText(generate.error)}
                </p>
              )}
            </>
          )}
        </Card>
      </div>
    )
  }

  if (state.status === 'failed') {
    const text = aiFailureTypeText(state.failureType ?? '', WORDING)
    return (
      <div className="mt-5">
        <Card>
          <CardTitle>AI 摘要失败</CardTitle>
          <p role="alert" className="mt-1.5 text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
            {text}
          </p>
          <InputPreview
            titleChars={articleTitle?.length ?? 0}
            bodyChars={articleText?.length ?? 0}
            scope={scope}
            onScopeChange={setScope}
          />
          <Button
            size="sm"
            className="mt-3"
            disabled={generating}
            onClick={() => generate.mutate(scope)}
          >
            {generating ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw aria-hidden className="size-3.5" />
            )}
            {generating ? '正在重试…' : '重试'}
          </Button>
          {generate.isError && (
            <p role="alert" className="mt-2.5 flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {failureText(generate.error)}
            </p>
          )}
        </Card>
      </div>
    )
  }

  // success（含缓存命中）
  const generatedAt = formatGeneratedAt(state.generatedAt)
  const metaParts = [state.model, generatedAt].filter((part) => part !== null && part !== '')
  const versions = (state as { versions?: SummaryVersionItem[] }).versions ?? []
  const inputChars = (state as { inputChars?: number | null }).inputChars
  const truncated = (state as { truncated?: boolean }).truncated
  return (
    <div className="mt-5">
      <Card>
        <div className="flex items-start justify-between gap-3">
          <CardTitle>AI 摘要</CardTitle>
          {state.cached && (
            <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
              缓存
            </span>
          )}
        </div>
        {articleText !== undefined && state.summary ? (
          <SummarySentences text={state.summary} articleText={articleText} />
        ) : (
          <p className="mt-2.5 whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
            {state.summary}
          </p>
        )}
        <p className="mt-2.5 text-[11px] text-[var(--lumi-text-tertiary)]">
          {[
            ...metaParts,
            inputChars != null ? `约 ${inputChars} 字符（token 计数以 Provider 为准）` : null,
            truncated ? '已按所选范围截断' : null,
          ]
            .filter((part) => part !== null && part !== '')
            .join(' · ')}
        </p>
        <VersionsPanel
          entryRef={entryRef}
          versions={versions}
          activeSummary={state.summary ?? null}
        />
      </Card>
    </div>
  )
}
