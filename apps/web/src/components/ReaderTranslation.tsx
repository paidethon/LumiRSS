/** ReaderTranslation — 0016：Reader 内的原文/译文视图切换。
 *
 * 设计不变式：
 * - 原文永远是规范内容（ArticleContent 原样渲染）；译文是派生的
 *   LumiRSS 数据，纯文本渲染（whitespace-pre-wrap），绝不进 HTML 渲染路径；
 * - 切换文章时组件重挂载（key=entryRef），视图回到「原文」，不泄漏旧状态；
 * - GET 只读缓存（零 provider 调用）；只有切到「译文」且未生成时才
 *   发出一次显式 POST（成功的精确缓存命中不会再调用）；
 * - 失败绝不破坏阅读：错误内联展示 + 重试，原文一键切回。
 *
 * 状态机（诚实呈现）：
 *   loading        → 骨架
 *   not_configured → 说明 + 去设置
 *   content 不可用 → 说明
 *   not_generated  → 生成按钮
 *   generating     → 转圈
 *   success        → 译文标题 + 译文正文 + model · 时间（+ 缓存徽标）
 *   failed         → 按 failureType 说明 + 重试
 */

import { useEffect, useState } from 'react'
import { AlertCircle, Languages, Loader2, RefreshCw } from 'lucide-react'
import type { EntryDetail } from '../api/types'
import { useEntryTranslation, useGenerateTranslationMutation } from '../api/queries'
import { ApiError } from '../api/client'
import ArticleContent from './ArticleContent'
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

const FAILURE_TEXT: Record<string, string> = {
  auth_error: 'API 密钥被服务端拒绝，请检查服务端的 AI_API_KEY 配置。',
  model_error: '模型或接口地址不存在，请检查 AI 设置中的 Base URL 与 Model。',
  rate_limited: 'AI 服务请求过于频繁，请稍后再试。',
  timeout: 'AI 服务响应超时，请重试。',
  invalid_response: 'AI 服务返回了无法解析的结果，请重试。',
  upstream_error: 'AI 服务暂时不可用，请稍后再试。',
  interrupted: '上次翻译被中断，请重试。',
  not_configured: 'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
  ai_not_configured: 'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
  content_unavailable: '这篇文章没有可翻译的正文内容。',
  ai_content_unavailable: '这篇文章没有可翻译的正文内容。',
}

function failureText(error: unknown): string {
  if (error instanceof ApiError) {
    // BFF 错误信封类型带 ai_ 前缀（ai_timeout），缓存 failureType 不带
    // （timeout）——两种都按同一稳定文案查找。
    const known =
      FAILURE_TEXT[error.type] ??
      FAILURE_TEXT[error.type.replace(/^ai_/, '')]
    if (known !== undefined) {
      return known
    }
  }
  return error instanceof Error ? error.message : '翻译失败，请重试。'
}

/** 原文/译文分段开关。切到「译文」就是显式请求翻译视图的动作。 */
function ViewToggle({
  view,
  onChange,
}: {
  view: 'original' | 'translated'
  onChange: (view: 'original' | 'translated') => void
}) {
  const base =
    'inline-flex min-h-9 items-center gap-1.5 rounded-[var(--lumi-radius-md)] border px-3 text-sm transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
  return (
    <div
      role="group"
      aria-label="文章语言视图"
      className="inline-flex items-center gap-1.5"
    >
      <button
        type="button"
        aria-pressed={view === 'original'}
        onClick={() => onChange('original')}
        className={cx(
          base,
          view === 'original'
            ? 'border-[var(--lumi-border)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
            : 'border-transparent text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
        )}
      >
        原文
      </button>
      <button
        type="button"
        aria-pressed={view === 'translated'}
        onClick={() => onChange('translated')}
        className={cx(
          base,
          view === 'translated'
            ? 'border-[var(--lumi-border)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
            : 'border-transparent text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
        )}
      >
        <Languages aria-hidden className="size-3.5" />
        译文
      </button>
    </div>
  )
}

/** 译文视图的内容区：按翻译状态诚实呈现。
 *
 * 进入译文视图且尚未生成时自动发起一次显式 POST（用户点「译文」即
 * 显式动作；精确缓存命中零成本）。失败状态只呈现错误 + 显式重试，
 * 不自动重试。 */
function TranslatedView({
  entryRef,
}: {
  entryRef: string
}) {
  const translation = useEntryTranslation(entryRef)
  const generate = useGenerateTranslationMutation(entryRef)

  const status = translation.data?.status
  useEffect(() => {
    if (status === 'not_generated' && !generate.isPending && !generate.isError) {
      generate.mutate()
    }
    // 依赖只取稳定原始值，避免 generate 对象身份变化导致重复触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, generate.isPending, generate.isError])

  if (translation.isPending) {
    return (
      <div className="flex flex-col gap-2.5" aria-label="正在加载翻译状态">
        <Skeleton className="h-5 w-2/5" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    )
  }

  if (translation.isError) {
    const error = translation.error
    const noRetry =
      error instanceof ApiError &&
      (error.type === 'ai_not_configured' || error.type === 'ai_content_unavailable')
    return (
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
        <p role="alert" className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--lumi-text-tertiary)]" />
          {failureText(error)}
        </p>
        {!noRetry && (
          <Button
            size="sm"
            variant="ghost"
            className="mt-2"
            onClick={() => translation.refetch()}
          >
            <RefreshCw aria-hidden className="size-3.5" />
            重试
          </Button>
        )}
      </div>
    )
  }

  const state = translation.data

  if (state.status === 'generating' || generate.isPending) {
    return (
      <p role="status" className="flex items-center gap-1.5 text-sm text-[var(--lumi-text-secondary)]">
        <Loader2 aria-hidden className="size-3.5 animate-spin" />
        正在翻译…
      </p>
    )
  }

  if (generate.isError) {
    return (
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
        <p role="alert" className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {failureText(generate.error)}
        </p>
        <Button
          size="sm"
          className="mt-3"
          onClick={() => generate.mutate()}
        >
          <RefreshCw aria-hidden className="size-3.5" />
          重试
        </Button>
      </div>
    )
  }

  if (state.status === 'not_generated') {
    return (
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
        <p className="text-sm text-[var(--lumi-text-secondary)]">
          按需生成，不会自动调用 AI；翻译成功后同一篇文章直接读取缓存。
        </p>
        <Button size="sm" className="mt-3" onClick={() => generate.mutate()}>
          <Languages aria-hidden className="size-3.5" />
          生成译文
        </Button>
      </div>
    )
  }

  if (state.status === 'failed') {
    const text = FAILURE_TEXT[state.failureType ?? ''] ?? '翻译失败，请重试。'
    return (
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
        <p role="alert" className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
          {text}
        </p>
        <Button size="sm" className="mt-3" onClick={() => generate.mutate()}>
          <RefreshCw aria-hidden className="size-3.5" />
          重试
        </Button>
      </div>
    )
  }

  // success（含缓存命中）：纯文本渲染，绝不进 HTML 渲染路径。
  const generatedAt = formatGeneratedAt(state.generatedAt)
  const metaParts = [state.model, generatedAt].filter((part) => part !== null && part !== '')
  return (
    <div>
      {state.translatedTitle !== null && (
        <h2 className="text-lg font-semibold leading-snug text-[var(--lumi-text-primary)]">
          {state.translatedTitle}
        </h2>
      )}
      <p className="mt-3 whitespace-pre-wrap text-[0.95rem] leading-[1.85] text-[var(--lumi-text-primary)]">
        {state.translatedText}
      </p>
      {metaParts.length > 0 && (
        <p className="mt-3 flex items-center gap-2 text-[11px] text-[var(--lumi-text-tertiary)]">
          {metaParts.join(' · ')}
          {state.cached && (
            <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5">
              缓存
            </span>
          )}
        </p>
      )}
    </div>
  )
}

export default function ReaderTranslation({ detail }: { detail: EntryDetail }) {
  const [view, setView] = useState<'original' | 'translated'>('original')

  return (
    <div className="pt-6">
      <div className="flex items-center justify-between gap-3">
        <ViewToggle view={view} onChange={setView} />
      </div>
      <div className="pt-4">
        {view === 'original' ? (
          <ArticleContent detail={detail} />
        ) : (
          <TranslatedView entryRef={detail.entryRef} />
        )}
      </div>
    </div>
  )
}
