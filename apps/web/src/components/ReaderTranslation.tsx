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
 * - P0-11：浏览器引擎的翻译编排在用户点击的手势任务内直接启动
 *   （Reader 把点击转发给本组件注册的 start 回调）——不走
 *   effect + 120ms timer 链，`Translator.create()` 是手势内第一个
 *   消耗 user activation 的长等待（语言包冷启动下载不再因此失败）。
 *   effect + MutationObserver 只保留为“激活之后内容才到达”的第二
 *   等级路径（此时手势可能已被消耗，失败就诚实给重试按钮）；
 * - 探测结果（源语言 / 语言对 availability）按文章与语言对缓存
 *   （模块级 + ref），点击链路在 create() 前不做可避免的等待；
 * - 同语言短路：探测源 === 目标语言(base) → 不调用任何 translate()；
 * - 配对依据稳定内容块 ID（annotateBlocks 的文档顺序编号），不是换行
 *   猜测；失败只标失败块，重试只重试失败内容；
 * - 执行位置如实标注：ai=AI 提供者（云端/自托管）、libretranslate=
 *   自托管服务器、browser=此浏览器（本地 Translator API，BFF 零参与）。
 *
 * 状态呈现（非 original 模式下的附注行，诚实不遮挡正文）：
 *   checking → 检查缓存 · generating → 翻译中 · partial → 失败块 + 重试
 *   · done → 引擎 · 语言 · 缓存徽标 · browser 引擎错误 → 说明
 */

import { useCallback, useEffect, useRef, useState } from 'react'
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
  detectArticleLanguage,
  isSameLanguage,
  LocalTranslatorActivationError,
  LocalTranslatorComponentError,
  LocalTranslatorLanguagePairError,
  LocalTranslatorUnsupportedError,
  localTranslatorPairStatus,
  type DetectedArticleLanguage,
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

/** run 键：块集合（顺序+索引）+ 目标语言的稳定签名（第二等级 effect 去重）。 */
function runSignature(list: ArticleBlock[], targetLanguage: string): string {
  return `${list.length}:${list.map((b) => b.index).join(',')}|${targetLanguage}`
}

/** 本地引擎错误分型 → 诚实中文文案（docs/research/local-translation.md §2）。
 * 返回 (message, retryable)：retryable=true 仅限“重试有意义”的错误——
 * 组件可更新（TranslateKit）或需要新的点击授权；unsupported /
 * 语言对不支持 重试永远失败，不给重试按钮。 */
function localEngineError(error: unknown): { message: string; retryable: boolean } {
  if (error instanceof LocalTranslatorComponentError) {
    return { message: error.message, retryable: true }
  }
  if (error instanceof LocalTranslatorActivationError) {
    return { message: error.message, retryable: true }
  }
  if (
    error instanceof LocalTranslatorLanguagePairError ||
    error instanceof LocalTranslatorUnsupportedError
  ) {
    return { message: error.message, retryable: false }
  }
  return {
    message: '本地翻译失败：此浏览器可能不支持该语言对，或下载语言包失败。',
    retryable: true,
  }
}

function blocksToInputs(blocks: ArticleBlock[]): TranslationSegmentBlockInput[] {
  return blocks.map((b) => ({ index: b.index, text: b.text }))
}

export default function ReaderTranslation({
  detail,
  viewMode,
  registerTranslationStart,
}: {
  detail: EntryDetail
  viewMode: ReaderViewMode
  /** P0-11：把“从点击手势直接启动浏览器引擎翻译”的回调注册给 Reader
   *（Reader 在 LanguageViewControl 的点击事件内同步调用）。 */
  registerTranslationStart?: (start: () => void) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [blocks, setBlocks] = useState<ArticleBlock[] | null>(null)
  const [localTexts, setLocalTexts] = useState<Map<number, string>>(new Map())
  const [localBusy, setLocalBusy] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null)
  const [localRetryable, setLocalRetryable] = useState(false)
  const [localSource, setLocalSource] = useState<DetectedArticleLanguage | null>(null)
  // P0-11(c)：同语言短路命中（原文即目标语言，零 translate() 调用）。
  const [sameLanguage, setSameLanguage] = useState(false)
  const attemptedRef = useRef<string>('')
  const localTranslatorRef = useRef<LocalTranslator | null>(null)
  const localTranslatorLangRef = useRef<string | null>(null)
  const localAbortRef = useRef<AbortController | null>(null)
  // P0-11：点击前预探测的源语言缓存（按正文抽样 key；点击链路命中时
  // create() 前不再等待 LanguageDetector）。
  const detectionCacheRef = useRef<{ key: string; value: DetectedArticleLanguage } | null>(null)
  // 正在/已经按此输入（块集合 + 目标语言）启动过的 run 键：第二等级
  // effect 据此不重复启动（也不 abort 手势路径的在途下载）。
  const runKeyRef = useRef<string>('')

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

  // 本地引擎：整个链路只在此浏览器执行。
  // P0-11 编排契约：
  // - 手势路径：Reader 在语言视图点击事件内同步调用 startTranslation →
  //   DOM 块就地同步收集 → runLocalTranslation。LanguageDetector（不消耗
  //   user activation）之后，`Translator.create()` 是第一个可消耗
  //   activation 的调用（语言包冷启动下载在手势内存活）；
  // - effect 路径（第二等级）：激活后内容才到达（MutationObserver）或
  //   组件直接以非 original 模式挂载。若当时需要下载且 activation 已被
  //   消耗 → NotAllowedError → 诚实重试按钮（重试永远带新 activation）；
  // - 探测/availability 双层缓存：ref（按文章抽样）+ 模块级语言对缓存；
  // - 同语言短路：source === target(base) → 零 translate() 调用；
  // - 文章切换/目标语言变更时 abort 旧任务，cancelled 标志防旧译文回写；
  //   detect→create 跨 await 处逐一检查 abort（不浪费下载）。
  const runLocalTranslation = useCallback(
    async (override?: ArticleBlock[]): Promise<void> => {
      const list = override ?? blocks
      if (list === null || list.length === 0) return
      runKeyRef.current = runSignature(list, targetLanguage)
      localAbortRef.current?.abort()
      const controller = new AbortController()
      localAbortRef.current = controller
      setLocalBusy(true)
      setLocalError(null)
      setLocalRetryable(false)
      setDownloadProgress(null)
      setSameLanguage(false)
      if (localTranslatorLangRef.current !== targetLanguage) {
        setLocalTexts(new Map())
        localTranslatorRef.current?.destroy()
        localTranslatorRef.current = null
      }
      const cancelled = () => controller.signal.aborted
      try {
        if (localTranslatorRef.current === null) {
          const sample = list.map((b) => b.text).join(' ')
          // 源语言：命中点击前预探测缓存则零等待；未命中就地探测
          // （探测不消耗 activation，但仍在手势任务内完成）。
          let source =
            detectionCacheRef.current !== null && detectionCacheRef.current.key === sample
              ? detectionCacheRef.current.value
              : null
          if (source === null) {
            source = await detectArticleLanguage(sample)
            detectionCacheRef.current = { key: sample, value: source }
          }
          setLocalSource(source)
          if (cancelled()) return
          // P0-11(c)：同语言短路——原文即目标语言，诚实提示，零翻译。
          if (isSameLanguage(source.lang, targetLanguage)) {
            setSameLanguage(true)
            setLocalTexts(new Map())
            return
          }
          // availability 预热进模块级缓存（探测不触发下载、不消耗
          // activation；后续对同一语言对零 await）。
          void localTranslatorPairStatus(source.lang, targetLanguage)
          localTranslatorRef.current = await createLocalTranslator(
            source.lang,
            targetLanguage,
            {
              onDownloadProgress: (fraction) => {
                if (!cancelled()) setDownloadProgress(fraction)
              },
            },
          )
          if (cancelled()) return
          localTranslatorLangRef.current = targetLanguage
        }
        const translator = localTranslatorRef.current
        const next = new Map<number, string>()
        for (const block of list) {
          if (cancelled()) return
          const text = await translator.translate(block.text, controller.signal)
          next.set(block.index, text)
        }
        if (!cancelled()) setLocalTexts(next)
      } catch (error) {
        if (cancelled()) return
        const mapped = localEngineError(error)
        setLocalError(mapped.message)
        setLocalRetryable(mapped.retryable)
      } finally {
        if (!cancelled()) {
          setLocalBusy(false)
          setDownloadProgress(null)
        }
      }
    },
    [blocks, targetLanguage],
  )

  // P0-11：手势入口——同步收集当前 DOM 块（点击时刻快照）后立即编排。
  // 注册本身在 effect（不是 activation 的一部分）；调用发生在点击事件
  // 的同步任务里，user activation 完整保留给 Translator.create()。
  const startTranslation = useCallback(() => {
    if (engine !== 'browser') return
    const root = containerRef.current
    if (root === null) return
    const found = annotateBlocks(root)
    setBlocks((prev) => (sameBlocks(prev, found) ? prev : found))
    void runLocalTranslation(found.length > 0 ? found : undefined)
  }, [engine, runLocalTranslation])

  useEffect(() => {
    registerTranslationStart?.(startTranslation)
    return () => registerTranslationStart?.(() => {})
  }, [registerTranslationStart, startTranslation])

  // 第二等级路径（非手势）：切到 双语/仅译文 时内容尚未到达（observer
  // 稍后产出块）、或组件直接以非 original 挂载、或目标语言变化。
  // 此时若语言包需要下载而 activation 已被消耗 → 诚实重试按钮。
  // 手势路径已按同一输入启动过的 run 不重复启动/不 abort。
  useEffect(() => {
    if (!active || engine !== 'browser' || blocks === null || blocks.length === 0) {
      return
    }
    if (runKeyRef.current === runSignature(blocks, targetLanguage)) return
    void runLocalTranslation()
    return () => {
      localAbortRef.current?.abort()
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
      setLocalRetryable(false)
      setDownloadProgress(null)
      setLocalSource(null)
      setSameLanguage(false)
      attemptedRef.current = ''
      localAbortRef.current?.abort()
      localTranslatorRef.current?.destroy()
      localTranslatorRef.current = null
      localTranslatorLangRef.current = null
      detectionCacheRef.current = null
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
          downloadProgress={downloadProgress}
          localSource={localSource}
          sameLanguage={sameLanguage}
          onLocalRetry={
            localError !== null &&
            localRetryable &&
            blocks !== null &&
            blocks.length > 0
              ? () => {
                  // 重试 = 直接调用（真实点击带来的新 user activation）。
                  void runLocalTranslation()
                }
              : undefined
          }
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
  downloadProgress,
  localSource,
  sameLanguage,
  onLocalRetry,
  lookupError,
  cached,
  onRetry,
}: {
  engine: string
  busy: boolean
  doneCount: number
  failedCount: number
  localError: string | null
  /** 语言包下载进度 0..1（null = 不在下载中）。 */
  downloadProgress: number | null
  /** 探测到的源语言（base code）+ 来源；via='fallback' 才显示回退标注。 */
  localSource: DetectedArticleLanguage | null
  /** P0-11(c)：原文即目标语言（同语言短路，零 translate() 调用）。 */
  sameLanguage: boolean
  onLocalRetry?: () => void
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
      {engine === 'browser' && localSource !== null && (
        <span>
          源语言：{localSource.lang}
          {localSource.lang === 'en' && localSource.via === 'fallback' && (
            <span className="ml-1">（探测失败回退）</span>
          )}
        </span>
      )}
      {engine === 'browser' && sameLanguage && !busy && (
        <span className="text-[var(--lumi-text-secondary)]">
          原文即目标语言，无需翻译。
        </span>
      )}
      {busy && (
        <span className="inline-flex items-center gap-1 text-[var(--lumi-text-secondary)]">
          <Loader2 aria-hidden className="size-3 animate-spin" />
          翻译中…
        </span>
      )}
      {downloadProgress !== null && (
        <span>
          下载语言包 {Math.round(downloadProgress * 100)}%
          <span
            role="progressbar"
            aria-valuenow={Math.round(downloadProgress * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="语言包下载进度"
            className="ml-1 inline-block h-1 w-16 overflow-hidden rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] align-middle"
          >
            <span
              className="block h-full bg-[var(--lumi-accent)]"
              style={{ width: `${Math.round(downloadProgress * 100)}%` }}
            />
          </span>
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
        <span className="inline-flex items-center gap-1.5 text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3" />
          {localError}
          {onLocalRetry && (
            <Button size="sm" variant="ghost" onClick={onLocalRetry}>
              <RefreshCw aria-hidden className="size-3" />
              重试
            </Button>
          )}
        </span>
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
