import { useEffect, useRef, useState } from 'react'
import {
  Camera, Check, Clock, ExternalLink, FileCode, FileText, Languages,
  Link2, Loader2, MessageSquare, MoreHorizontal, Pause, Play, Printer, Quote,
  Search, Share2, Square, Star, Volume2,
} from 'lucide-react'
import type { EntryDetail } from '../api/types'
import { useAiSettings, useCreateSnapshotMutation, useEntryStateMutation } from '../api/queries'
import { getEntry } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'
import { useToggleReadLater } from '../lib/read-later'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { formatReadingTime, textFromHtml } from '../lib/reading-time'
import { dateTimeFormatter as dateFormatter } from '../lib/date-format'
import { localTranslatorAvailable } from '../lib/local-translator'
import { SourceGlyph, SourceLabel } from '../lib/source-meta'
import { useAppSettings } from '../store/app-settings'
import { useUndo } from '../store/undo'
import {
  buildQuoteMarkdownText,
  buildQuotePlainText,
  fallbackShareUrl,
  QUOTE_MAX_CHARS,
  type AutoScrollState,
} from '../lib/reader-tools'
import {
  SPEECH_RATES,
  speakText,
  speechSynthesisAvailable,
  type SpeechRate,
} from '../lib/reader-speech'
import {
  exportEntryAsHtml,
  exportEntryAsMarkdown,
  type ExportInput,
} from '../lib/reader-export'
import ReaderAaPanel from './ReaderAaPanel'
import type { ReaderViewMode } from '../lib/translation-blocks'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Menu } from './ui/Menu'
import { Tooltip } from './ui/Tooltip'
import { cx } from './ui/cx'

function formatPublishedAt(value: string | null | undefined): string {
  if (value == null) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateFormatter.format(date)
}

/** phase2 Gate 3：保存快照（monolith 离线快照；仅绝对 http/https 原文
 * 可保存——由父级以 safeExternalHttpUrl 过滤后条件渲染）。
 * 成功短暂显示「快照已保存」；失败原样透出 BFF message
 *（monolith_unavailable / 配额超限等，诚实语义）。 */
function SaveSnapshotButton({ url }: { url: string }) {
  const [savedRecently, setSavedRecently] = useState(false)
  const createSnapshot = useCreateSnapshotMutation()

  const failure =
    createSnapshot.isError && createSnapshot.error instanceof Error
      ? createSnapshot.error.message
      : createSnapshot.isError
        ? '快照保存失败，请稍后重试。'
        : null
  const tooltip = failure ?? (savedRecently ? '快照已保存' : '保存快照')

  return (
    <Tooltip content={tooltip}>
      <IconButton
        icon={
          createSnapshot.isPending ? (
            <Loader2 aria-hidden className="animate-spin" />
          ) : (
            <Camera
              aria-hidden
              className={cx(
                savedRecently && 'text-[var(--lumi-accent-text)]',
              )}
            />
          )
        }
        label="保存快照"
        touch
        disabled={createSnapshot.isPending}
        onClick={() =>
          createSnapshot.mutate(url, {
            onSuccess: () => {
              setSavedRecently(true)
              window.setTimeout(() => setSavedRecently(false), 3000)
            },
          })
        }
      />
    </Tooltip>
  )
}

/** F19 朗读：speechSynthesis 接线（能力缺失 = 按钮诚实禁用 + 原因）。
 * 点击循环 空闲→朗读→暂停→继续；「停止朗读」cancel 并复位。
 * collectText 由 Reader 提供（取视口顶部最近段落往后的全部正文）；
 * 本组件按 entryRef 重挂载（ReaderHeader key），卸载即 cancel——
 * 切文章自动停止朗读。 */
function ReaderSpeechControl({ collectText }: { collectText: () => string | null }) {
  const [state, setState] = useState<'idle' | 'speaking' | 'paused'>('idle')
  const [rate, setRate] = useState<SpeechRate>(1)
  const [error, setError] = useState<string | null>(null)
  const textRef = useRef('')
  const stateRef = useRef(state)
  stateRef.current = state
  const available = speechSynthesisAvailable()

  // 切文章（key 重挂载）/卸载：cancel 朗读，绝不跨文章延续。
  useEffect(() => {
    return () => {
      if (speechSynthesisAvailable()) window.speechSynthesis.cancel()
    }
  }, [])

  if (!available) {
    return (
      <Tooltip content="此浏览器不支持语音朗读（speechSynthesis 不可用）">
        <IconButton
          icon={<Volume2 aria-hidden />}
          label="朗读"
          touch
          disabled
          title="此浏览器不支持语音朗读（speechSynthesis 不可用）"
        />
      </Tooltip>
    )
  }

  const speakCurrent = (nextRate: SpeechRate) => {
    speakText(textRef.current, {
      rate: nextRate,
      onEnd: () => setState('idle'),
      onError: (message) => {
        setError(message)
        setState('idle')
      },
    })
    setState('speaking')
  }

  const toggle = () => {
    setError(null)
    if (state === 'idle') {
      const text = collectText()
      if (text === null || text.trim() === '') {
        setError('没有可朗读的正文。')
        return
      }
      textRef.current = text
      speakCurrent(rate)
      return
    }
    if (state === 'speaking') {
      window.speechSynthesis.pause()
      setState('paused')
      return
    }
    window.speechSynthesis.resume()
    setState('speaking')
  }

  const stop = () => {
    window.speechSynthesis.cancel()
    setState('idle')
    setError(null)
  }

  const changeRate = (next: SpeechRate) => {
    setRate(next)
    // 朗读中调速：取消并按新语速从头重读同一段文本（诚实且立即可感）。
    if (stateRef.current !== 'idle') speakCurrent(next)
  }

  return (
    <>
      <Tooltip
        content={
          state === 'idle' ? '朗读' : state === 'speaking' ? '暂停朗读' : '继续朗读'
        }
      >
        <IconButton
          icon={
            state === 'speaking' ? (
              <Pause aria-hidden />
            ) : state === 'paused' ? (
              <Play aria-hidden />
            ) : (
              <Volume2 aria-hidden />
            )
          }
          label={state === 'idle' ? '朗读' : state === 'speaking' ? '暂停朗读' : '继续朗读'}
          aria-pressed={state !== 'idle'}
          touch
          onClick={toggle}
        />
      </Tooltip>
      {state !== 'idle' && (
        <>
          <Tooltip content="停止朗读">
            <IconButton
              icon={<Square aria-hidden />}
              label="停止朗读"
              touch
              onClick={stop}
            />
          </Tooltip>
          {/* 语速 segmented（0.75 / 1 / 1.25 / 1.5）；朗读中调速即重读 */}
          <div
            role="group"
            aria-label="朗读语速"
            className="hidden items-center gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5 lg:inline-flex"
          >
            {SPEECH_RATES.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={rate === value}
                onClick={() => changeRate(value)}
                className={cx(
                  'min-h-8 min-w-11 rounded-[var(--lumi-radius-sm)] px-1 text-xs tabular-nums transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  rate === value
                    ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                    : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
                )}
              >
                {value}x
              </button>
            ))}
          </div>
        </>
      )}
      {error !== null && (
        <span role="alert" className="text-xs text-[var(--lumi-danger)]">
          {error}
        </span>
      )}
    </>
  )
}

/** F21 分享：navigator.share 可用 → 系统分享（AbortError=用户取消，
 * 静默）；其它错误 → 回退复制链接；无 share 能力 → 直接复制链接。
 * 复制结果以按钮旁即时文案反馈（成功「链接已复制」/失败可见）。 */
function ShareButton({ title, url }: { title: string; url: string | null }) {
  const [feedback, setFeedback] = useState<string | null>(null)
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function'
  const shareUrl = url ?? fallbackShareUrl()

  const showFeedback = (message: string) => {
    setFeedback(message)
    window.setTimeout(() => setFeedback((current) => (current === message ? null : current)), 2000)
  }

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
      showFeedback('链接已复制')
    } catch {
      showFeedback('复制失败')
    }
  }

  const onShare = async () => {
    if (canShare) {
      try {
        await navigator.share({ title, url: shareUrl })
        return
      } catch (error) {
        // AbortError = 用户取消分享系统面板，静默（不算失败）。
        if ((error as { name?: string } | null)?.name === 'AbortError') return
        // 其它错误 → 回退复制链接
      }
    }
    await copyLink()
  }

  return (
    <>
      <Tooltip content={feedback ?? (canShare ? '分享' : '复制链接')}>
        <IconButton
          icon={<Share2 aria-hidden />}
          label={canShare ? '分享' : '复制链接'}
          touch
          onClick={() => {
            void onShare()
          }}
        />
      </Tooltip>
      {feedback !== null && (
        <span aria-live="polite" data-lumi-share-feedback="" className="text-xs text-[var(--lumi-accent-text)]">
          {feedback}
        </span>
      )}
    </>
  )
}

/** F24 复制引用：无选区 = 标题+来源+链接；有选区附加引文（≤500 字）。
 * 两种格式（纯文本 / Markdown）菜单二选一；成功按钮短暂变 Check；
 * 失败展示可手动复制的只读文本框（诚实失败）。 */
function QuoteCopyButton({
  title,
  source,
  url,
}: {
  title: string
  source: string
  url: string | null
}) {
  const [copiedRecently, setCopiedRecently] = useState(false)
  const [fallbackText, setFallbackText] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const copy = async (format: 'plain' | 'markdown') => {
    const selection =
      typeof window.getSelection === 'function' ? window.getSelection()?.toString() ?? '' : ''
    const quote = selection.trim().slice(0, QUOTE_MAX_CHARS)
    const input = { title, source, url, quote }
    const text =
      format === 'plain' ? buildQuotePlainText(input) : buildQuoteMarkdownText(input)
    try {
      await navigator.clipboard.writeText(text)
      setFallbackText(null)
      setCopiedRecently(true)
      window.setTimeout(() => setCopiedRecently(false), 1200)
    } catch {
      setFallbackText(text)
    }
  }

  return (
    <>
      <Menu
        trigger={({ triggerProps }) => (
          <Tooltip content="复制引用">
            <IconButton
              {...triggerProps}
              icon={
                copiedRecently ? (
                  <Check aria-hidden className="text-[var(--lumi-accent-text)]" />
                ) : (
                  <Quote aria-hidden />
                )
              }
              label="复制引用"
              touch
            />
          </Tooltip>
        )}
        items={[
          { key: 'plain', content: '复制为纯文本' },
          { key: 'markdown', content: '复制为 Markdown' },
        ]}
        onSelect={(key) => {
          void copy(key === 'markdown' ? 'markdown' : 'plain')
        }}
      />
      {fallbackText !== null && (
        <div className="flex w-full basis-full items-start gap-2" data-lumi-quote-fallback="">
          <textarea
            ref={textareaRef}
            readOnly
            value={fallbackText}
            aria-label="复制失败的引用文本（可手动复制）"
            rows={4}
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          />
          <Button size="sm" onClick={() => textareaRef.current?.select()}>
            全选
          </Button>
        </div>
      )}
    </>
  )
}

/** ReaderHeader — 标题 / 元信息 / 工具栏（0009 Gate 3 视觉重建）。
 *
 * 布局（Spec Task 12）：紧凑工具栏（IconButton 32px + Tooltip）+
 * 强标题（27px 级，Folo 实测锚点）+ 弱化元信息行。原 0006 的两个
 * 大按钮（标记已读/收藏）改为工具栏图标按钮——set 语义、共用
 * mutation 实例、pending 双禁用、key=entryRef 防泄漏等行为全部保留
 * （在 Reader.tsx 上挂 key）。
 *
 * 行为不变式（Spec 硬边界 3/5）：
 * - set 语义（PATCH 目标状态，非 toggle）；
 * - 打开原文只放行绝对 http/https（safeExternalHttpUrl），
 *   target=_blank + rel=noopener noreferrer。
 *
 * Reader 工具类功能（F13/F18/F19/F21/F22/F23/F24）挂同一工具栏：
 * 文内查找 / 朗读 / 分享 / 复制引用 / 打印 / 更多操作（自动滚屏、
 * 导出 Markdown、导出 HTML）。 */
/** Gate：语言视图三态控件（原文/双语/仅译文）。
 * 桌面 = 三段分段按钮；窄屏 = 紧凑 Menu（不遮挡/不挤出工具栏）。
 * 两态 Switch 表达不了三态，这里用显式的选项组。
 * P0-11：engine=browser 且浏览器不支持本地 Translator API 时整组
 * 禁用并给原因（不再让用户点开才发现不可用）；支持矩阵在设置页。 */
function LanguageViewControl({
  value,
  onChange,
  disabledReason,
}: {
  value: ReaderViewMode
  onChange: (mode: ReaderViewMode) => void
  /** 非 null = 当前引擎在此浏览器不可用（附原因），控件禁用。 */
  disabledReason?: string | null
}) {
  const options: { key: ReaderViewMode; label: string; short: string }[] = [
    { key: 'original', label: '原文', short: '原文' },
    { key: 'bilingual', label: '双语', short: '双语' },
    { key: 'translated', label: '仅译文', short: '译文' },
  ]
  const base =
    'inline-flex min-h-8 items-center gap-1 rounded-[var(--lumi-radius-md)] px-2 text-sm transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
  const gated = disabledReason != null
  return (
    <>
      {/* 桌面分段 */}
      <div
        role="group"
        aria-label="语言视图"
        title={gated ? disabledReason : undefined}
        className="hidden items-center gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5 lg:inline-flex"
      >
        {options.map((option) => (
          <button
            key={option.key}
            type="button"
            aria-pressed={value === option.key}
            disabled={gated && option.key !== 'original'}
            title={gated && option.key !== 'original' ? disabledReason : undefined}
            onClick={() => onChange(option.key)}
            className={cx(
              base,
              'min-w-0 px-2.5',
              value === option.key
                ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
              gated && option.key !== 'original' && 'opacity-50',
            )}
          >
            {option.key === 'translated' && (
              <Languages aria-hidden className="size-3.5" />
            )}
            {option.label}
          </button>
        ))}
      </div>
      {/* 移动端紧凑菜单 */}
      <div className="lg:hidden">
        <Menu
          trigger={({ triggerProps }) => (
            <Tooltip content={gated ? disabledReason : '语言视图'}>
              <IconButton
                {...triggerProps}
                icon={<Languages aria-hidden className={cx(value !== 'original' && 'text-[var(--lumi-accent-text)]')} />}
                label={
                  gated
                    ? `语言视图不可用：${disabledReason}`
                    : `语言视图：当前 ${options.find((o) => o.key === value)?.label ?? '原文'}`
                }
                touch
                disabled={gated}
              />
            </Tooltip>
          )}
          items={options.map((o) => ({
            key: o.key,
            content: value === o.key ? <strong>✓ {o.label}</strong> : o.label,
          }))}
          onSelect={(key) => onChange(key as ReaderViewMode)}
        />
      </div>
    </>
  )
}

export default function ReaderHeader({
  detail,
  viewMode = 'original',
  onViewModeChange,
  onOpenAiConversation,
  onOpenFind,
  onOpenLinks,
  collectSpeechText,
  autoScrollState = 'off',
  onAutoScrollToggle,
  focusMode,
  onFocusModeChange,
}: {
  detail: EntryDetail
  /** Gate：语言视图（由 Reader 持有；工具栏与内容区共享同一状态）。 */
  viewMode?: ReaderViewMode
  onViewModeChange?: (mode: ReaderViewMode) => void
  /** 0016：打开文章限定 AI 对话（由 Reader 持有面板开关状态）。 */
  onOpenAiConversation?: () => void
  /** F13：打开文内查找（Reader 持有查找条状态）。 */
  onOpenFind?: () => void
  /** F054：文中链接清单（Reader 持有面板状态）。 */
  onOpenLinks?: () => void
  /** F19：收集「从视口顶部段落开始」的朗读文本（Reader 提供容器几何）。 */
  collectSpeechText?: () => string | null
  /** F18：自动滚屏状态 + 切换（Reader 持有 rAF 循环）。 */
  autoScrollState?: AutoScrollState
  onAutoScrollToggle?: () => void
  /** 专注阅读（Reader 会话级状态，透传给 Aa 面板）。 */
  focusMode?: boolean
  onFocusModeChange?: (value: boolean) => void
}) {
  const mutation = useEntryStateMutation()
  const queryClient = useQueryClient()
  // F20：读/未读切换的短时撤销（撤销前核对服务器状态，防跨设备覆盖）
  const pushUndo = useUndo((s) => s.push)
  const { isReadLater, toggleReadLater, pendingFor, errorFor } = useToggleReadLater()
  const readLaterMarked = isReadLater(detail.entryRef)
  const readLaterPending = pendingFor(detail.entryRef)
  const readLaterError = errorFor(detail.entryRef)
  const showReadingTime = useAppSettings((s) => s.settings.readerShowReadingTime)
  // P0-11：本地引擎支持门控——engine=browser 且此浏览器没有 Translator
  // API（localTranslatorAvailable() 此前导出零调用）→ 控件禁用 + 原因。
  const aiSettings = useAiSettings()
  const translationDisabledReason =
    (aiSettings.data?.translationEngine ?? 'ai') === 'browser' && !localTranslatorAvailable()
      ? '此浏览器不支持本地翻译（需要 Chrome 内置 Translator API）；可在 设置 → 翻译 更换翻译引擎。'
      : null

  // url 与 contentHtml 一样来自外部 RSS，是不可信输入：
  // 只放行绝对 http/https，其余一律不渲染「打开原文」。
  const articleUrl = safeExternalHttpUrl(detail.url)
  const published = formatPublishedAt(detail.publishedAt)
  const pending = mutation.isPending

  // 0012 Gate 5：CJK 感知阅读时间（弱化展示；开关控制）。
  // 输入用 contentText（BFF 已产出的安全纯文本）优先，回退从
  // contentHtml 提取（本地 DOMParser，不进入渲染）。仅对不可信
  // HTML做只读解析，输出只有数字。文本量极小，不 memo。
  const readingTime = showReadingTime
    ? formatReadingTime(
        detail.contentText.trim() !== ''
          ? detail.contentText
          : textFromHtml(detail.contentHtml ?? ''),
      )
    : null

  // F22 导出输入：url 只放行 safeExternalHttpUrl 通过的地址（导出文件
  // 不携带不可信协议链接）；日期用已格式化的本地时间。
  const exportInput: ExportInput = {
    title: detail.title,
    source: detail.feedTitle,
    date: published,
    url: articleUrl,
    text: detail.contentText,
    html: detail.contentHtml ?? null,
  }

  return (
    <header className="border-b border-[var(--lumi-separator)] pb-5">
      {/* 元信息行（弱化）：来源（P2：可点击进入该订阅范围）· 作者 ·
          时间 · 阅读时间。来源缺失降级「来源未知」。 */}
      <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-xs text-[var(--lumi-text-tertiary)]">
        <SourceGlyph name={detail.feedTitle} />
        <SourceLabel
          feedTitle={detail.feedTitle}
          feedUrl={detail.feedUrl}
          className="min-w-0 max-w-[16rem] text-left"
        />
        {detail.author !== null && <span className="truncate">· {detail.author}</span>}
        {published !== '' && <span>· {published}</span>}
        {readingTime !== null && <span>· {readingTime}</span>}
      </p>

      {/* 强标题（Folo 锚点 27px/700；移动端略小） */}
      <h1 className="mt-2 text-[1.7rem] font-bold leading-snug text-[var(--lumi-text-primary)] max-lg:text-2xl max-lg:leading-tight">
        {detail.title}
      </h1>

      {/* 工具栏：紧凑图标按钮（桌面 32px，手机 touch 44px）。
          pending 时统一转圈，双按钮禁用（同一篇同时最多一个 PATCH）。 */}
      {/* flex-wrap：移动端窄屏溢出时换行而不是把「打开原文」挤成竖排 */}
      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.read ? '标记为未读' : '标记为已读'}>
            <IconButton
              icon={
                <Check
                  aria-hidden
                  className={cx(
                    detail.read
                      ? 'text-[var(--lumi-accent-text)]'
                      : 'text-current',
                  )}
                />
              }
              label={detail.read ? '标记为未读' : '标记为已读'}
              aria-pressed={detail.read}
              touch
              onClick={() => {
                const next = !detail.read
                mutation.mutate(
                  { entryRef: detail.entryRef, patch: { read: next } },
                  {
                    onSuccess: () => {
                      // F20：8 秒撤销窗口；撤销前核对服务器 read 状态
                      pushUndo({
                        label: next ? '已标记已读' : '已标记未读',
                        check: async () => {
                          const fresh = await queryClient.fetchQuery({
                            queryKey: ['entry', detail.entryRef],
                            queryFn: ({ signal }) => getEntry(detail.entryRef, signal),
                            staleTime: 0,
                          })
                          return fresh.read === next
                        },
                        undo: async () => {
                          await mutation.mutateAsync({
                            entryRef: detail.entryRef,
                            patch: { read: !next },
                          })
                        },
                      })
                    },
                  },
                )
              }}
            />
          </Tooltip>
        )}

        {/* 稍后读（P0-01）：服务端保留工作区成员（真源）——乐观切换 +
            失败回滚由 useReadLaterMemberMutation 承载；✓ ◷ ☆ 顺序——
            阅读处理 → 临时保存 → 长期收藏；active = accent icon，同一
            Clock 图标不换形（§23）；失败行内诚实提示（不假装成功）。 */}
        <Tooltip content={readLaterMarked ? '从稍后读移除' : '加入稍后读'}>
          <IconButton
            icon={
              readLaterPending ? (
                <Loader2 aria-hidden className="animate-spin" />
              ) : (
                <Clock
                  aria-hidden
                  className={cx(
                    readLaterMarked && 'fill-[var(--lumi-accent-soft)]',
                  )}
                />
              )
            }
            label={readLaterMarked ? '从稍后读移除' : '加入稍后读'}
            aria-pressed={readLaterMarked}
            touch
            disabled={readLaterPending}
            className={readLaterMarked ? 'text-[var(--lumi-accent-text)]' : undefined}
            onClick={() => toggleReadLater(detail.entryRef)}
          />
        </Tooltip>
        {readLaterError !== null && (
          <span role="alert" className="text-xs text-[var(--lumi-danger)]">
            稍后读操作失败：{readLaterError instanceof Error ? readLaterError.message : '请稍后重试。'}
          </span>
        )}

        {pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.starred ? '取消收藏' : '收藏'}>
            <IconButton
              icon={
                <Star
                  aria-hidden
                  className={cx(
                    detail.starred &&
                      'fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]',
                  )}
                />
              }
              label={detail.starred ? '取消收藏' : '收藏'}
              aria-pressed={detail.starred}
              touch
              onClick={() =>
                mutation.mutate({
                  entryRef: detail.entryRef,
                  patch: { starred: !detail.starred },
                })
              }
            />
          </Tooltip>
        )}

        {articleUrl !== null && (
          <a
            href={articleUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 items-center gap-1.5 whitespace-nowrap rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <ExternalLink aria-hidden className="size-3.5" />
            打开原文
          </a>
        )}

        {/* phase2 Gate 3：保存快照——只在原文是绝对 http/https 时出现
            （articleUrl 已过 safeExternalHttpUrl）。 */}
        {articleUrl !== null && <SaveSnapshotButton url={articleUrl} />}

        {/* 0016：文章限定 AI 对话入口（右侧面板；Reader 持有开关） */}
        {onOpenAiConversation !== undefined && (
          <Tooltip content="AI 对话">
            <IconButton
              icon={<MessageSquare aria-hidden />}
              label="AI 对话"
              touch
              onClick={onOpenAiConversation}
            />
          </Tooltip>
        )}

        {/* Gate：语言视图（原文/双语/仅译文）——与 稍后读/收藏/Aa 同一
            工具栏；Reader 持有状态，正文区消费。P0-11：不支持的平台
            禁用 + 原因，不再让用户点开才发现不可用。 */}
        {onViewModeChange !== undefined && (
          <LanguageViewControl
            value={viewMode ?? 'original'}
            onChange={onViewModeChange}
            disabledReason={translationDisabledReason}
          />
        )}

        {/* F13：文内查找（Reader 持有查找条状态） */}
        {onOpenFind !== undefined && (
          <Tooltip content="文内查找">
            <IconButton
              icon={<Search aria-hidden />}
              label="文内查找"
              touch
              onClick={onOpenFind}
            />
          </Tooltip>
        )}

        {/* F054：文中链接清单 */}
        {onOpenLinks !== undefined && (
          <Tooltip content="文中链接">
            <IconButton icon={<Link2 aria-hidden />} label="文中链接" touch onClick={onOpenLinks} />
          </Tooltip>
        )}

        {/* F19：朗读（collectText 由 Reader 提供；未提供不渲染） */}
        {collectSpeechText !== undefined && (
          <ReaderSpeechControl collectText={collectSpeechText} />
        )}

        {/* F21：分享 / 复制链接（navigator.share 能力决定行为，回退诚实） */}
        <ShareButton title={detail.title} url={articleUrl} />

        {/* F24：复制引用（纯文本 / Markdown 格式菜单） */}
        <QuoteCopyButton title={detail.title} source={detail.feedTitle} url={articleUrl} />

        {/* F23：打印（window.print；不承诺 PDF） */}
        <Tooltip content="打印">
          <IconButton
            icon={<Printer aria-hidden />}
            label="打印"
            touch
            onClick={() => {
              if (typeof window.print === 'function') window.print()
            }}
          />
        </Tooltip>

        {/* F18/F22：更多操作菜单（自动滚屏 / 导出 Markdown / 导出 HTML） */}
        {(onAutoScrollToggle !== undefined) && (
          <Menu
            trigger={({ triggerProps }) => (
              <Tooltip content="更多操作">
                <IconButton
                  {...triggerProps}
                  icon={<MoreHorizontal aria-hidden />}
                  label="更多操作"
                  touch
                />
              </Tooltip>
            )}
            items={[
              {
                key: 'autoscroll',
                content: (
                  <span className="flex items-center gap-2">
                    {autoScrollState === 'off' ? (
                      <Play aria-hidden className="size-4" />
                    ) : (
                      <Pause aria-hidden className="size-4" />
                    )}
                    {autoScrollState === 'off'
                      ? '自动滚屏'
                      : autoScrollState === 'running'
                        ? '暂停自动滚屏'
                        : '继续自动滚屏'}
                  </span>
                ),
              },
              { key: 'export-md', content: (
                <span className="flex items-center gap-2">
                  <FileText aria-hidden className="size-4" />
                  导出 Markdown
                </span>
              ) },
              { key: 'export-html', content: (
                <span className="flex items-center gap-2">
                  <FileCode aria-hidden className="size-4" />
                  导出 HTML
                </span>
              ) },
            ]}
            onSelect={(key) => {
              if (key === 'autoscroll') {
                onAutoScrollToggle?.()
                return
              }
              if (key === 'export-md') {
                exportEntryAsMarkdown(exportInput)
                return
              }
              if (key === 'export-html') exportEntryAsHtml(exportInput)
            }}
          />
        )}

        {/* 0012 Gate 7：Reader 内快速阅读样式面板（Aa）；与设置中心
            同一 settings source，不遮挡正文关键操作。F15/F17/专注：
            代码换行 / 按屏翻页 / 专注阅读开关挂同一面板。 */}
        <ReaderAaPanel focusMode={focusMode} onFocusModeChange={onFocusModeChange} />
      </div>

      {mutation.isError && (
        <p className="mt-2 text-sm text-[var(--lumi-danger)]" role="alert">
          状态更新失败：{mutation.error instanceof Error ? mutation.error.message : '请稍后重试。'}
        </p>
      )}
    </header>
  )
}
