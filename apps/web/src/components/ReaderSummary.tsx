/** ReaderSummary — 0015 Gate 7：Reader 内的按需 AI 摘要卡片。
 *
 * 状态机（诚实呈现，绝不渲染神秘的空白区域）：
 *   loading        → 细骨架
 *   not_configured → 「AI 未配置」+ 去设置的说明（503 ai_not_configured）
 *   not_generated  → 「AI 摘要」按钮（点击 = 唯一可能产生付费调用的动作）
 *   generating     → 转圈 + 「正在生成摘要…」
 *   success        → 摘要正文（纯文本渲染）+ model · 生成时间（+ 缓存徽标）
 *   failed         → 按 failureType 的稳定中文说明 + 重试
 *   content 不可用 → 「这篇文章没有可摘要的正文内容」
 *
 * 成功缓存命中不会再次调用 AI；失败重试是显式用户动作。
 * 摘要输出按纯文本渲染（whitespace-pre-wrap），不经过 HTML 渲染路径。
 */

import { AlertCircle, Loader2, RefreshCw, Sparkles } from 'lucide-react'
import { useEntrySummary, useGenerateSummaryMutation } from '../api/queries'
import { ApiError } from '../api/client'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatGeneratedAt(value: string | null): string {
  if (value === null) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateTimeFormatter.format(date)
}

/** failureType / 错误类型 → 稳定的用户中文说明。 */
const FAILURE_TEXT: Record<string, string> = {
  auth_error: 'API 密钥被服务端拒绝，请检查服务端的 AI_API_KEY 配置。',
  model_error: '模型或接口地址不存在，请检查 AI 设置中的 Base URL 与 Model。',
  rate_limited: 'AI 服务请求过于频繁，请稍后再试。',
  timeout: 'AI 服务响应超时，请重试。',
  invalid_response: 'AI 服务返回了无法解析的结果，请重试。',
  upstream_error: 'AI 服务暂时不可用，请稍后再试。',
  interrupted: '上次生成被中断，请重试。',
  not_configured: 'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
  ai_not_configured: 'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
  content_unavailable: '这篇文章没有可摘要的正文内容。',
  ai_content_unavailable: '这篇文章没有可摘要的正文内容。',
}

function failureText(error: unknown): string {
  if (error instanceof ApiError) {
    const known = FAILURE_TEXT[error.type]
    if (known !== undefined) {
      return known
    }
  }
  return error instanceof Error ? error.message : '生成失败，请重试。'
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
      <Sparkles aria-hidden className="size-3.5 text-[var(--lumi-accent)]" />
      {children}
    </p>
  )
}

export default function ReaderSummary({ entryRef }: { entryRef: string }) {
  const summary = useEntrySummary(entryRef)
  const generate = useGenerateSummaryMutation(entryRef)
  const generating = generate.isPending

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
              <Button
                size="sm"
                className="mt-3"
                disabled={generating}
                onClick={() => generate.mutate()}
              >
                {generating ? (
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                ) : (
                  <Sparkles aria-hidden className="size-3.5" />
                )}
                {generating ? '正在生成…' : 'AI 摘要'}
              </Button>
              {generate.isError && (
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
    const text = FAILURE_TEXT[state.failureType ?? ''] ?? '生成失败，请重试。'
    return (
      <div className="mt-5">
        <Card>
          <CardTitle>AI 摘要失败</CardTitle>
          <p role="alert" className="mt-1.5 text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
            {text}
          </p>
          <Button
            size="sm"
            className="mt-3"
            disabled={generating}
            onClick={() => generate.mutate()}
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
        <p className="mt-2.5 whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
          {state.summary}
        </p>
        {metaParts.length > 0 && (
          <p className="mt-2.5 text-[11px] text-[var(--lumi-text-tertiary)]">
            {metaParts.join(' · ')}
          </p>
        )}
      </Card>
    </div>
  )
}
