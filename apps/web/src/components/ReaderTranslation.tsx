/** ReaderTranslation — Gate：原文 / 双语 / 仅译文 三模式内容区。
 *
 * 设计不变式（延续 0016 并扩展）：
 * - 原文永远是规范内容（ArticleContent 原样渲染）；译文是派生的
 *   LumiRSS 数据，只以 textContent 注入（translation-blocks overlay），
 *   绝不进 HTML 渲染路径；
 * - 语言视图控制的 UI 在 ReaderHeader 工具栏（本组件只消费 viewMode），
 *   旧的正文内“原文/译文”切换控件已移除，不存在两套不同步状态；
 * - 新文章默认“原文”：打开页面绝不发起翻译；切到 双语/仅译文 就是
 *   显式的按需动作（一次），精确缓存命中零 provider 调用；仅查看原文
 *   与纯排版切换（bilingual ↔ translated）不再触发任何请求；
 * - 配对依据稳定内容块 ID（annotateBlocks 的文档顺序编号），不是换行
 *   猜测；失败只标失败块，重试只重试失败内容；
 * - 执行位置如实标注：ai=AI 提供者（云端/自托管）、libretranslate=
 *   自托管服务器、browser=此浏览器（本地 Translator API，BFF 零参与）。
 *
 * 状态呈现（非 original 模式下的附注行，诚实不遮挡正文）：
 *   checking → 检查缓存 · generating → 翻译中 · partial → 失败块 + 重试
 *   · done → 引擎 · 语言 · 缓存徽标 · browser 引擎错误 → 说明
 */

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Languages, Loader2, RefreshCw } from 'lucide-react'
import type { EntryDetail, TranslationSegmentState } from '../api/types'
import {
  useAiSettings,
  useGenerateTranslationSegmentsMutation,
  useTranslationSegments,
} from '../api/queries'
import type { TranslationSegmentBlockInput } from '../api/client'
import type { ReaderViewMode } from '../lib/translation-blocks'
import {
  annotateBlocks,
  applyOverlay,
  resetOverlay,
  type ArticleBlock,
} from '../lib/translation-blocks'
import {
  createLocalTranslator,
  LocalTranslatorUnsupportedError,
  type LocalTranslator,
} from '../lib/local-translator'
import ArticleContent from './ArticleContent'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

const ENGINE_LABELS: Record<string, string> = {
  ai: 'AI 翻译（AI 提供者执行）',
  libretranslate: '机器翻译（自托管服务器执行）',
  browser: '本地翻译（此浏览器执行）',
}

function sameBlocks(a: ArticleBlock[] | null, b: ArticleBlock[]): boolean {
  if (a === null || a.length !== b.length) return false
  return a.every((block, i) => block.index === b[i].index && block.text === b[i].text)
}

function blocksToInputs(blocks: ArticleBlock[]): TranslationSegmentBlockInput[] {
  return blocks.map((b) => ({ index: b.index, text: b.text }))
}

export default function ReaderTranslation({
  detail,
  viewMode,
}: {
  detail: EntryDetail
  viewMode: ReaderViewMode
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [blocks, setBlocks] = useState<ArticleBlock[] | null>(null)
  const [localTexts, setLocalTexts] = useState<Map<number, string>>(new Map())
  const [localBusy, setLocalBusy] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const attemptedRef = useRef<string>('')
  const localTranslatorRef = useRef<LocalTranslator | null>(null)
  const localTranslatorLangRef = useRef<string | null>(null)

  const settings = useAiSettings()
  const engine = settings.data?.translationEngine ?? 'ai'
  const targetLanguage = settings.data?.translationLanguage ?? 'zh-CN'
  const active = viewMode !== 'original'
  const serverEngine = engine !== 'browser'

  // 正文 DOM 观察管线的产物（contentHtml 是异步管线输出）稳定后，按文档
  // 顺序给内容块编号并收集文本。viewMode=original 不做任何 DOM 改动。
  useEffect(() => {
    if (!active) return
    const root = containerRef.current
    if (root === null) return
    let timer: number | undefined
    const scan = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        setBlocks((prev) => {
          const found = annotateBlocks(root)
          return sameBlocks(prev, found) ? prev : found
        })
      }, 120)
    }
    const observer = new MutationObserver(scan)
    observer.observe(root, { childList: true, subtree: true })
    scan()
    return () => {
      observer.disconnect()
      window.clearTimeout(timer)
    }
  }, [active, detail.entryRef])

  const lookup = useTranslationSegments(detail.entryRef, blocks, active && serverEngine)
  const generate = useGenerateTranslationSegmentsMutation(detail.entryRef)

  // 切到 双语/仅译文 的那一次点击 = 显式请求：未生成的块自动生成一次
  // （精确命中缓存的部分不会重复生成）。失败块的重试只送失败块。
  const serverSegments = lookup.data?.segments
  useEffect(() => {
    if (!active || !serverEngine || blocks === null || blocks.length === 0) return
    if (lookup.isPending || lookup.isError || generate.isPending) return
    const pending = (serverSegments ?? []).filter(
      (s) => s.status === 'not_generated',
    )
    const failed = (serverSegments ?? []).filter((s) => s.status === 'failed')
    if (pending.length === 0) return
    const signature = `${detail.entryRef}:${blocks.length}:${pending.length}`
    if (attemptedRef.current === signature) return
    attemptedRef.current = signature
    generate.mutate(blocksToInputs(blocks))
    // failed 块只在用户点重试时重新生成（money rule：不自动重试）
    void failed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, serverEngine, blocks, lookup.isPending, lookup.isError, serverSegments])

  // 本地引擎：整个链路只在此浏览器执行；切模式的点击即 user activation。
  // 目标语言变更也走这里：旧语言对的译文先作废，再按新语言对重建
  // （服务端路径经缓存身份自然切换，与此处无关）。
  useEffect(() => {
    if (!active || engine !== 'browser' || blocks === null || blocks.length === 0) {
      return
    }
    const controller = new AbortController()
    setLocalBusy(true)
    setLocalError(null)
    if (localTranslatorLangRef.current !== targetLanguage) {
      setLocalTexts(new Map())
      localTranslatorRef.current?.destroy()
      localTranslatorRef.current = null
    }
    let cancelled = false
    void (async () => {
      try {
        if (localTranslatorRef.current === null) {
          localTranslatorRef.current = await createLocalTranslator('en', targetLanguage)
          localTranslatorLangRef.current = targetLanguage
        }
        const translator = localTranslatorRef.current
        const next = new Map<number, string>()
        for (const block of blocks) {
          if (controller.signal.aborted) return
          const text = await translator.translate(block.text, controller.signal)
          next.set(block.index, text)
        }
        if (!cancelled) setLocalTexts(next)
      } catch (error) {
        if (!cancelled && !controller.signal.aborted) {
          setLocalError(
            error instanceof LocalTranslatorUnsupportedError
              ? error.message
              : '本地翻译失败：此浏览器可能不支持该语言对，或下载语言包失败。',
          )
        }
      } finally {
        if (!cancelled) setLocalBusy(false)
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, engine, blocks, targetLanguage])

  // overlay：texts 变化（或 mode 切换）时重放；纯排版切换零网络。
  useEffect(() => {
    const root = containerRef.current
    if (root === null || !active) return
    const texts = new Map<number, string>()
    if (engine === 'browser') {
      for (const [index, text] of localTexts) texts.set(index, text)
    } else {
      for (const s of serverSegments ?? []) {
        if (s.status === 'success' && s.translatedText) {
          texts.set(s.index, s.translatedText)
        }
      }
    }
    applyOverlay(root, { texts, mode: viewMode === 'bilingual' ? 'bilingual' : 'translated' })
    return () => resetOverlay(root)
  }, [active, viewMode, engine, serverSegments, localTexts, blocks])

  // 切换文章：重置一切（Reader 已按 entryRef 对 key 重挂载，这里兜底）。
  useEffect(() => {
    return () => {
      setBlocks(null)
      setLocalTexts(new Map())
      setLocalError(null)
      attemptedRef.current = ''
      localTranslatorRef.current?.destroy()
      localTranslatorRef.current = null
      localTranslatorLangRef.current = null
    }
  }, [detail.entryRef])

  const retryFailed = () => {
    if (blocks === null) return
    const failedIndexes = new Set(
      (serverSegments ?? [])
        .filter((s) => s.status === 'failed')
        .map((s) => s.index),
    )
    const failedBlocks = blocks.filter((b) => failedIndexes.has(b.index))
    if (failedBlocks.length === 0) return
    generate.mutate(blocksToInputs(failedBlocks))
  }

  const segmentList = serverSegments ?? []
  const failedCount = segmentList.filter((s) => s.status === 'failed').length
  const busy = generate.isPending || localBusy
  const doneCount = engine === 'browser' ? localTexts.size : segmentList.filter((s) => s.status === 'success').length

  return (
    <div className={cx('pt-6', viewMode === 'bilingual' && 'reader-bilingual-active')}>
      <div ref={containerRef}>
        <ArticleContent detail={detail} />
      </div>

      {active && (
        <TranslationStatusBar
          engine={engine}
          busy={busy}
          doneCount={doneCount}
          failedCount={failedCount}
          localError={localError}
          lookupError={serverEngine && lookup.isError ? lookup.error : null}
          cached={segmentList.some((s) => s.status === 'success' && s.cached)}
          onRetry={failedCount > 0 ? retryFailed : undefined}
        />
      )}
    </div>
  )
}

/** 附注行：执行位置 · 状态 · 失败重试。role=status，不遮挡正文。 */
function TranslationStatusBar({
  engine,
  busy,
  doneCount,
  failedCount,
  localError,
  lookupError,
  cached,
  onRetry,
}: {
  engine: string
  busy: boolean
  doneCount: number
  failedCount: number
  localError: string | null
  lookupError: unknown
  cached: boolean
  onRetry?: () => void
}) {
  const engineLabel = ENGINE_LABELS[engine] ?? engine
  return (
    <p
      role="status"
      className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]"
    >
      <Languages aria-hidden className="size-3.5" />
      <span>{engineLabel}</span>
      {busy && (
        <span className="inline-flex items-center gap-1 text-[var(--lumi-text-secondary)]">
          <Loader2 aria-hidden className="size-3 animate-spin" />
          翻译中…
        </span>
      )}
      {!busy && doneCount > 0 && (
        <span>
          已译 {doneCount} 段
          {cached && (
            <span className="ml-1.5 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5">
              缓存
            </span>
          )}
        </span>
      )}
      {failedCount > 0 && (
        <span className="inline-flex items-center gap-1.5 text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3" />
          {failedCount} 段失败
          {onRetry && (
            <Button size="sm" variant="ghost" onClick={onRetry}>
              <RefreshCw aria-hidden className="size-3" />
              只重试失败段
            </Button>
          )}
        </span>
      )}
      {localError !== null && (
        <span className="text-[var(--lumi-danger)]">{localError}</span>
      )}
      {lookupError !== null && (
        <span className="text-[var(--lumi-danger)]">
          翻译服务暂不可用，原文阅读不受影响。
        </span>
      )}
    </p>
  )
}

export type { TranslationSegmentState }
