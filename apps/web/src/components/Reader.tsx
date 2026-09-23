import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowUp, ChevronDown, ChevronUp, History, Pause, Play, RefreshCw, Square } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useEntryDetail, useEntryStateMutation } from '../api/queries'
import { ApiError } from '../api/client'
import { listSourceOverrides } from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import {
  captureAnchorText,
  findAnchorElement,
  loadReadingPosition,
  saveReadingPosition,
} from '../lib/reading-position'
import { useFinishRead } from '../lib/finish-read'
import {
  AUTO_SCROLL_SPEEDS,
  BACK_TO_TOP_THRESHOLD_PX,
  pageTargetTop,
  scrollContainerBy,
  type AutoScrollSpeed,
  type AutoScrollState,
} from '../lib/reader-tools'
import {
  applyFocusActive,
  clearFocusActive,
} from '../lib/reader-focus'
import {
  findStartBlockIndex,
  SPEECH_BLOCK_SELECTOR,
  type SpeechCollection,
} from '../lib/reader-speech'
import type { ReaderViewMode } from '../lib/translation-blocks'
import ArticleContent from './ArticleContent'
// bundle guard：阅读工具栏只在选中文章后出现，且本就挂在局部
// `<Suspense fallback={null}>` 边界里——与下方摘要/对话/查找条同一
// 模式改 lazy 分包（首开瞬时 null，chunk 缓存后同步渲染）。正文
// 渲染管线 ArticleContent 仍保持静态（首读关键路径零 lazy 不变）。
// P12/P14/P16 合并后首屏超 780/235 门槛，此举单独降 ~68 kB raw /
// ~21 kB gzip（810→742 / 244→223），随 reader-export、本地翻译引擎
// 与其专属 base-ui 部件一并移出首屏。
const ReaderHeader = lazy(() => import('./ReaderHeader'))
// bundle guard：摘要/来源/反链/对话面板非正文首帧结构（各自已有局部
// Suspense 边界 / 条件挂载）——lazy 分包。正文首读关键路径（原始渲染）
// 保持静态：original 模式直渲 ArticleContent；双语/仅译文才挂 lazy
// ReaderTranslation（其非手势第二等级 effect 会在挂载后按当前 viewMode
// 自启翻译——浏览器引擎 activation 被消费时诚实重试，既有语义）。
const ReaderTranslation = lazy(() => import('./ReaderTranslation'))
const ArticleConversation = lazy(() => import('./ArticleConversation'))
const ReaderSummary = lazy(() => import('./ReaderSummary'))
const ProvenanceCard = lazy(() => import('./ProvenanceCard'))
// N031：文章修订差异面板（元数据量级，按需查询；无修订零渲染）。
const EntryRevisionsPanel = lazy(() => import('./EntryRevisionsPanel'))
const EntryNotesBacklinks = lazy(() => import('./EntryNotesBacklinks'))
const EnclosurePlayer = lazy(() => import('./EnclosurePlayer').then((m) => ({ default: m.EnclosurePlayer })))
import ReaderPlaceholder from './ReaderPlaceholder'
import { useReadingProgressReporter } from '../lib/reading-progress-reporter'
import ReaderProgress from './ReaderProgress'
import { isPlayableEnclosure } from '../lib/enclosure'
import { lazy, Suspense } from 'react'
// Bundle guard：查找条/批注层/行辅助线非首读必需——懒加载分包
// （查找条仅在工具栏打开时可见，Suspense 瞬时 null 无感）。
const ArticleFindBar = lazy(() => import('./ArticleFindBar'))
const AnnotationsLayer = lazy(() =>
  import('./AnnotationsLayer').then((m) => ({ default: m.AnnotationsLayer })),
)
const ReadingRuler = lazy(() =>
  import('./ReadingRuler').then((m) => ({ default: m.ReadingRuler })),
)
// Bundle guard：N052 分页阅读非首读默认路径（阅读模式默认滚动）——
// 与行辅助线同一 lazy 分包模式。
const ReaderPager = lazy(() =>
  import('./ReaderPager').then((m) => ({ default: m.ReaderPager })),
)
const ArticleLinksPanel = lazy(() => import('./ArticleLinksPanel'))
const ItemRelationsPanel = lazy(() => import('./ItemRelationsPanel'))
const QuizPanel = lazy(() => import('./QuizPanel').then((m) => ({ default: m.QuizPanel })))
const KnowledgeCardsPanel = lazy(() => import('./KnowledgeCardsPanel').then((m) => ({ default: m.KnowledgeCardsPanel })))
const SearchHitsChip = lazy(() => import('./SearchHitsChip').then((m) => ({ default: m.SearchHitsChip })))
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'
import { useIsMobile } from '../lib/use-is-mobile'
import { readerStyleCssVars, resolveSourceReaderStyle } from '../lib/source-reader-style'

/** 段落锚点候选：正文容器内的常见内容元素（文档序遍历，取视口线上方
 * 最近的一个作为位置锚点）。 */
const ANCHOR_SELECTOR = [
  '.lumi-reader-article p',
  '.lumi-reader-article li',
  '.lumi-reader-article pre',
  '.lumi-reader-article blockquote',
  '.lumi-reader-article h1',
  '.lumi-reader-article h2',
  '.lumi-reader-article h3',
  '.lumi-reader-article h4',
  '.lumi-reader-article h5',
  '.lumi-reader-article h6',
].join(', ')

/** F18 自动滚屏速度标签（chip 展示）。 */
const AUTO_SCROLL_SPEED_LABELS: Record<AutoScrollSpeed, string> = {
  slow: '慢',
  medium: '中',
  fast: '快',
}

/** F18 自动滚屏状态 chip：状态文字（aria-live）+ 三档速度 segmented +
 * 暂停/继续 + 停止。rAF 循环在 Reader effect 中，chip 只做展示/操作。 */
function AutoScrollChip({
  state,
  speed,
  onSpeedChange,
  onToggle,
  onStop,
}: {
  state: Exclude<AutoScrollState, 'off'>
  speed: AutoScrollSpeed
  onSpeedChange: (speed: AutoScrollSpeed) => void
  onToggle: () => void
  onStop: () => void
}) {
  return (
    <div
      data-lumi-autoscroll-chip=""
      className="absolute bottom-6 left-4 z-10 flex items-center gap-1.5 rounded-full border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] py-1 pe-1.5 ps-3 shadow-[var(--lumi-shadow-popover)]"
    >
      <span
        aria-live="polite"
        className="whitespace-nowrap text-xs text-[var(--lumi-text-secondary)]"
      >
        {state === 'running'
          ? `自动滚屏 · ${AUTO_SCROLL_SPEED_LABELS[speed]}`
          : '自动滚屏 · 已暂停'}
      </span>
      <div
        role="group"
        aria-label="自动滚屏速度"
        className="flex items-center gap-0.5"
      >
        {(['slow', 'medium', 'fast'] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={speed === value}
            aria-label={`速度${AUTO_SCROLL_SPEED_LABELS[value]}`}
            onClick={() => onSpeedChange(value)}
            className={cx(
              'min-h-8 min-w-8 rounded-[var(--lumi-radius-md)] px-1.5 text-xs transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              speed === value
                ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
            )}
          >
            {AUTO_SCROLL_SPEED_LABELS[value]}
          </button>
        ))}
      </div>
      <IconButton
        size="sm"
        icon={state === 'running' ? <Pause aria-hidden className="size-4" /> : <Play aria-hidden className="size-4" />}
        label={state === 'running' ? '暂停自动滚屏' : '继续自动滚屏'}
        touch
        onClick={onToggle}
      />
      <IconButton
        size="sm"
        icon={<Square aria-hidden className="size-4" />}
        label="停止自动滚屏"
        touch
        onClick={onStop}
      />
    </div>
  )
}

/** Reader — 右栏状态机（0006 行为 / 0009 Gate 3 视觉重建）：
 *
 *   no selection → ReaderPlaceholder（不发 Detail 请求）
 *   pending      → Reader skeleton（Sidebar / EntryList 不受影响）
 *   404          → 「这篇文章已经不存在或不可用了。」+ 返回文章列表
 *   其它 error   → 「文章加载失败」+ 安全错误信息 + 重试
 *   success      → ReaderHeader（key=entryRef，防止旧 mutation UI 泄漏到
 *                  新 Entry）+ ArticleContent
 *
 * 0009 Gate 3：
 * - 容器背景用 --lumi-reader-bg（Reader 独立背景钩子，tokens.css 默认
 *   指向 --lumi-reader；App Theme 与 Reader Theme 分离的接线点）；
 * - 正文最大宽度 46rem（~736px，Spec 720–780 区间），居中；
 * - skeleton / error / 404 全部 token 化 + primitives。
 *
 * Reader 自己滚动；切换选择时恢复该文章的上次阅读位置（pool #01），
 * 无记录则回到顶部。
 *
 * Reader 工具类功能（F11–F25）在成功分支集成：
 * - F11 阅读进度条（滚动容器顶部，ReaderProgress 自挂原生监听）；
 * - F13 文内查找（工具栏入口 + ArticleFindBar 浮层）；
 * - F16/F14 灯箱与表格展开在 ArticleContent 内部；
 * - F17 按屏翻页（readerPagedMode，右下角上一屏/下一屏）；
 * - F18 自动滚屏（rAF 循环；每帧 noteProgrammaticScroll 续豁免窗口，
 *   切文章/离开/页面 hidden 自动停止）；
 * - F25 回到顶部 / 返回刚才位置（>600px 且未到底时出现；恢复滚动
 *   先 noteProgrammaticScroll 豁免，不计主动推进）；
 * - 专注阅读（会话级开关；视口中心块标记，其余降透明度）。 */
/** F011：当前 Entry 的可播放 enclosure 列表（无附件 → 零渲染）。 */
function EnclosurePlayers({ detail }: { detail: { entryRef: string; enclosure?: { href: string; type?: string | null }[] | null } }) {
  const items = (detail.enclosure ?? []).filter((item) => isPlayableEnclosure(item))
  if (items.length === 0) return null
  return (
    <div className="mb-3 flex flex-col gap-2">
      {items.map((item) => (
        <EnclosurePlayer key={item.href} enclosure={item} entryRef={detail.entryRef} />
      ))}
    </div>
  )
}

export default function Reader() {
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const readerAutoMarkRead = useAppSettings((s) => s.settings.readerAutoMarkRead)
  // F11：进度条开关；F17：按屏翻页开关（均来自 settings store）。
  const readerShowReadingProgress = useAppSettings((s) => s.settings.readerShowReadingProgress)
  const readerPagedMode = useAppSettings((s) => s.settings.readerPagedMode)
  // N052：阅读模式（设备本地）——'paged' = 分页阅读，优先于 F17 按屏翻页。
  const readerReadingMode = useAppSettings((s) => s.settings.readerReadingMode)
  const pagedReading = readerReadingMode === 'paged'
  const { data, isPending, isError, error, refetch } = useEntryDetail(selectedEntryRef)
  // F055 消费端：按 entry 的 feed 匹配 source_overrides.readerStyle
  // （fontSize/lineHeight/width 三键，全局仍是基础、覆盖仅这三键；
  // width 移动端忽略）。查询随 detail 有 feedUrl 才启用。
  const isMobile = useIsMobile()
  const detailFeedUrl = data?.feedUrl ?? null
  const overridesQuery = useQuery({
    queryKey: ['source-overrides'],
    queryFn: async () => {
      try {
        return await listSourceOverrides()
      } catch {
        // 覆盖是增强能力：拿不到（网络/接口异常）→ 诚实退回全局样式。
        return { items: [] }
      }
    },
    enabled: detailFeedUrl !== null,
    staleTime: 60_000,
  })
  const sourceStyleVars = readerStyleCssVars(
    resolveSourceReaderStyle(detailFeedUrl, overridesQuery.data?.items, { isMobile }),
  )
  // F056：阅读进度上报（15s 节流 + 仅页面可见时；切文自动换 ref）。
  // 无条件调用（Hooks 规则）；entryRef 为 null 时 hook 内部直接跳过。
  useReadingProgressReporter(data?.entryRef ?? null)
  // 0016：AI 对话面板开关（纯 UI 状态；面板内容跟随当前文章）。
  const [aiConversationOpen, setAiConversationOpen] = useState(false)
  // Gate：语言视图（原文/双语/仅译文）——Reader 层持有，工具栏与内容区
  // 共享同一状态；默认原文（打开文章绝不发起翻译）。
  const [viewMode, setViewMode] = useState<ReaderViewMode>('original')
  // P0-11：浏览器引擎翻译的手势入口——ReaderTranslation 注册 start 回调，
  // 语言视图点击在同一个事件任务内转发（activation 不经 effect/timer 消耗）。
  const translationStartRef = useRef<(() => void) | null>(null)
  const registerTranslationStart = useCallback((start: () => void) => {
    translationStartRef.current = start
  }, [])
  const handleViewModeChange = useCallback(
    (mode: ReaderViewMode) => {
      setViewMode(mode)
      if (mode !== 'original') translationStartRef.current?.()
    },
    [],
  )
  useEffect(() => {
    // 换文章回原文：不为“打开页面”付任何翻译钱。
    setViewMode('original')
  }, [selectedEntryRef])

  const scrollRef = useRef<HTMLDivElement | null>(null)
  /** F20/R05：正文容器 ref（AnnotationsLayer 选区监听 / ReadingRuler
   * 指针跟随用；与 scrollRef 同一 DOM 节点，通过双写保持同步）。 */
  const articleScrollRef = useRef<HTMLDivElement | null>(null)
  // N052：正文 article 元素（分页多栏 track，ReaderPager 施加样式用）。
  const articleElementRef = useRef<HTMLElement | null>(null)
  // F054：正文容器（收集文中链接）；F048：提取失败徽标状态。
  const contentRef = useRef<HTMLElement | null>(null)

  // P0-2：正文读到底自动已读（与列表划过标读、位置保存严格区分）。
  const stateMutation = useEntryStateMutation()
  const finishRead = useFinishRead({
    enabled: readerAutoMarkRead,
    entryRef: selectedEntryRef,
    read: data?.read ?? false,
    markRead: (entryRef) =>
      stateMutation.mutateAsync({ entryRef, patch: { read: true } }),
  })

  /** 容器 ref 双挂：位置保存/恢复用 scrollRef；读完判定挂原生滚动监听；
   * F20/R05 的正文组件经 articleScrollRef 共享同一 DOM 节点。
   * 只依赖 hook 的稳定函数成员（对象身份每渲染可能变化，ref 回调与
   * 恢复效应不得随之重触发——否则会重置读完判定的进度基线）。 */
  const finishSetContainer = finishRead.setContainer
  const finishNoteProgrammatic = finishRead.noteProgrammaticScroll
  const setScrollContainer = useCallback(
    (node: HTMLDivElement | null) => {
      scrollRef.current = node
      articleScrollRef.current = node
      finishSetContainer(node)
    },
    [finishSetContainer],
  )

// 阅读位置恢复（pool #01）：按 ItemRef 记录滚动比例 + 段落锚点，切换
// 返回时恢复；锚点优先、ratio 回退，正文改版只会落在本篇内。只读滚动
// 位置，绝不触碰已读状态。列表窗格滚动与正文互不影响。
// P0-2：恢复属程序性滚动——先豁免，不计为主动阅读推进。
const restorePosition = useCallback(() => {
  const container = scrollRef.current
  if (container === null || selectedEntryRef === null) return
  finishNoteProgrammatic()
  const saved = loadReadingPosition(selectedEntryRef)
  if (saved === null) {
    container.scrollTop = 0
    return
  }
  const anchor = findAnchorElement(container, saved.anchorText)
  if (anchor !== null) {
    const top =
      anchor.getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      container.scrollTop
    container.scrollTop = Math.max(0, top - 12)
  } else {
    const max = container.scrollHeight - container.clientHeight
    container.scrollTop = max > 0 ? Math.round(saved.ratio * max) : 0
  }
}, [selectedEntryRef, finishNoteProgrammatic])

useEffect(() => {
  restorePosition()
}, [restorePosition])

// 正文渲染完成后再恢复一次——此时锚点段落可被真正命中。
const detailEntryRef = data?.entryRef ?? null
useEffect(() => {
  if (detailEntryRef !== null) restorePosition()
}, [detailEntryRef, restorePosition])

// ---- F11/F13/F17/F18/F25/专注：Reader 工具类状态 ----

// F13：文内查找条开关。
const [findOpen, setFindOpen] = useState(false)
  // F054：文中链接面板
  const [linksOpen, setLinksOpen] = useState(false)
// 专注阅读：会话级开关（settings store 无此键；Aa 面板经 props 切换）。
const [focusMode, setFocusMode] = useState(false)
const focusModeRef = useRef(focusMode)
focusModeRef.current = focusMode
// F18：自动滚屏状态 + 速度（速度经 ref 读，避免 rAF 循环重启闪烁）。
const [autoScroll, setAutoScroll] = useState<AutoScrollState>('off')
const [autoSpeed, setAutoSpeed] = useState<AutoScrollSpeed>('medium')
const autoSpeedRef = useRef(autoSpeed)
autoSpeedRef.current = autoSpeed
// F17/F25：滚动派生标志（翻页按钮可用性）。滚动帧内只在标志翻转时
// setState——避免每帧重渲染整棵 Reader 子树（正文宿主元素被频繁更新
// 会清掉渲染后 DOM 装饰）。回顶按钮可见性由 backMode 单独承载。
interface ScrollFlags {
  canUp: boolean
  canDown: boolean
}
const [scrollFlags, setScrollFlags] = useState<ScrollFlags>({ canUp: false, canDown: false })
const scrollFlagsRef = useRef(scrollFlags)
const updateScrollFlags = useCallback((next: ScrollFlags) => {
  const prev = scrollFlagsRef.current
  if (prev.canUp === next.canUp && prev.canDown === next.canDown) return
  scrollFlagsRef.current = next
  setScrollFlags(next)
}, [])
const [backMode, setBackMode] = useState<'top' | 'return' | null>(null)
const backSavedTopRef = useRef<number | null>(null)
// 程序性滚动（回顶/恢复）产生的 scroll 事件不重置回顶按钮状态。
const backSuppressRef = useRef(false)
// 专注模式滚动 rAF 句柄。
const focusTickRef = useRef<number | null>(null)

const getScrollContainer = useCallback(() => scrollRef.current, [])
/** F13 查找根：正文 article（标题/工具栏不参与查找）。 */
const getFindRoot = useCallback(
  () => (scrollRef.current?.querySelector('.lumi-reader-article') as HTMLElement | null) ?? null,
  [],
)

// P18 朗读块收集：视口顶部线所在段落往后（含）的全部块文本（DOM 序，
// 下标即块索引——引擎入队时空块跳过但原始下标保留，高亮按块定位）。
// 总量上限（20k）由引擎入队时单点施加。
const collectSpeechBlocks = useCallback((): SpeechCollection | null => {
  const container = scrollRef.current
  const article = container?.querySelector('.lumi-reader-article')
  if (container === null || article === undefined || article === null) return null
  const blocks = Array.from(article.querySelectorAll(SPEECH_BLOCK_SELECTOR))
  if (blocks.length === 0) return null
  const containerTop = container.getBoundingClientRect().top
  const tops = blocks.map((block) => block.getBoundingClientRect().top)
  const startIndex = findStartBlockIndex(tops, containerTop)
  const texts = blocks.map((block) => block.textContent ?? '')
  if (texts.slice(startIndex).every((text) => text.trim() === '')) return null
  return { texts, startIndex }
}, [])

// F18：切文章自动停止（自动滚屏/查找/回顶状态一并复位）。
useEffect(() => {
  setAutoScroll('off')
  setFindOpen(false)
  setBackMode(null)
  backSavedTopRef.current = null
}, [selectedEntryRef])

// F18：页面 hidden 自动停止（后台不偷滚）。
useEffect(() => {
  const onVisibility = () => {
    if (document.visibilityState === 'hidden') setAutoScroll('off')
  }
  document.addEventListener('visibilitychange', onVisibility)
  return () => document.removeEventListener('visibilitychange', onVisibility)
}, [])

// F17/F25：正文渲染后测一次容器（初始按钮 disabled 态无需等首次滚动；
// 图片/译文展开后的余量变化仍由滚动帧内的 rAF 重测兜底）。
useEffect(() => {
  if (detailEntryRef === null) return
  const container = scrollRef.current
  if (container === null) return
  const max = container.scrollHeight - container.clientHeight
  const top = container.scrollTop
  updateScrollFlags({
    canUp: top > 0,
    canDown: max > 0 && top < max - 1,
  })
}, [detailEntryRef, updateScrollFlags])

// F18：自动滚屏 rAF 循环。每帧先 noteProgrammaticScroll() 续写豁免
// 窗口——自动滚屏属程序性滚动，不计为 finish-read 的主动阅读推进
//（直接写 programmaticUntil 不可行，finish-read 属他人模块；每帧调用
// 官方入口等价续期）。到底自动停止。
useEffect(() => {
  if (autoScroll !== 'running') return
  let raf = 0
  let stopped = false
  const step = () => {
    if (stopped) return
    const container = scrollRef.current
    if (container === null) {
      setAutoScroll('off')
      return
    }
    finishNoteProgrammatic()
    const max = container.scrollHeight - container.clientHeight
    if (max <= 0 || container.scrollTop >= max) {
      setAutoScroll('off')
      return
    }
    container.scrollTop = Math.min(max, container.scrollTop + AUTO_SCROLL_SPEEDS[autoSpeedRef.current])
    raf = requestAnimationFrame(step)
  }
  raf = requestAnimationFrame(step)
  return () => {
    stopped = true
    cancelAnimationFrame(raf)
  }
}, [autoScroll, finishNoteProgrammatic])

// 专注阅读：滚动帧内重算视口中心最近的块并打标（关闭时清理全部标记）。
useEffect(() => {
  if (!focusMode) return
  const article = scrollRef.current?.querySelector('.lumi-reader-article')
  if (!(article instanceof HTMLElement)) return
  article.setAttribute('data-lumi-focus', 'on')
  const applyNow = () => {
    const container = scrollRef.current
    const node = scrollRef.current?.querySelector('.lumi-reader-article')
    if (container === null || !(node instanceof HTMLElement)) return
    const rect = container.getBoundingClientRect()
    applyFocusActive(node, rect.top + rect.height / 2)
  }
  applyNow()
  const onScroll = () => {
    if (focusTickRef.current !== null) return
    focusTickRef.current = requestAnimationFrame(() => {
      focusTickRef.current = null
      applyNow()
    })
  }
  const container = scrollRef.current
  container?.addEventListener('scroll', onScroll, { passive: true })
  return () => {
    container?.removeEventListener('scroll', onScroll)
    if (focusTickRef.current !== null) {
      cancelAnimationFrame(focusTickRef.current)
      focusTickRef.current = null
    }
    clearFocusActive(article)
  }
}, [focusMode, detailEntryRef])

// F17：按屏翻页（±clientHeight×0.9，平滑滚动；翻页产生的滚动事件不
// 豁免——计入 finish-read 主动推进，这正是「翻页也是阅读」的语义）。
const pageBy = useCallback((direction: 1 | -1) => {
  const container = scrollRef.current
  if (container === null) return
  const target = pageTargetTop(
    container.scrollTop,
    container.clientHeight,
    container.scrollHeight - container.clientHeight,
    direction,
  )
  scrollContainerBy(container, target - container.scrollTop)
}, [])

// F25：回到顶部（记录原位置 + 程序性豁免）；再次点击返回刚才位置。
const handleBackToTop = useCallback(() => {
  const container = scrollRef.current
  if (container === null) return
  backSuppressRef.current = true
  finishNoteProgrammatic()
  backSavedTopRef.current = container.scrollTop
  container.scrollTop = 0
  setBackMode('return')
}, [finishNoteProgrammatic])

const handleReturnToPosition = useCallback(() => {
  const container = scrollRef.current
  const saved = backSavedTopRef.current
  if (container === null || saved === null) {
    setBackMode(null)
    return
  }
  backSuppressRef.current = true
  // F25：恢复用的滚动必须先豁免——不计为主动阅读推进。
  finishNoteProgrammatic()
  container.scrollTop = saved
  backSavedTopRef.current = null
  setBackMode('top')
}, [finishNoteProgrammatic])

// 滚动保存：rAF 合并；锚点取视口顶 80px 线上方最近的正文段落。
// 同一 rAF 内顺带更新 F17/F25 依赖的滚动指标（回顶按钮出现/重置）。
const saveTickRef = useRef<number | null>(null)
const handleScroll = useCallback(() => {
  if (saveTickRef.current !== null) return
  saveTickRef.current = requestAnimationFrame(() => {
    saveTickRef.current = null
    const container = scrollRef.current
    if (container === null || selectedEntryRef === null) return
    const max = container.scrollHeight - container.clientHeight
    const top = container.scrollTop
    const ratio = max > 0 ? top / max : 0
    const containerTop = container.getBoundingClientRect().top
    let anchor: Element | null = null
    for (const el of container.querySelectorAll(ANCHOR_SELECTOR)) {
      if (el.getBoundingClientRect().top > containerTop + 80) break
      anchor = el
    }
    saveReadingPosition(selectedEntryRef, {
      ratio,
      anchorText: captureAnchorText(anchor),
      savedAt: new Date().toISOString(),
    })
    // F17/F25：派生标志（只在翻转时 setState，见上方 ScrollFlags 注释）
    updateScrollFlags({
      canUp: top > 0,
      canDown: max > 0 && top < max - 1,
    })
    // F25：程序性回顶/恢复的 scroll 事件不重置按钮状态；用户滚动则
    // 重置为「回到顶部」（清掉旧的保存位置），到顶/到底时隐藏。
    if (backSuppressRef.current) {
      backSuppressRef.current = false
      return
    }
    backSavedTopRef.current = null
    setBackMode((current) => {
      const next = top > BACK_TO_TOP_THRESHOLD_PX && max > 0 && top < max - 1 ? 'top' : null
      return current === next ? current : next
    })
  })
}, [selectedEntryRef, updateScrollFlags])

  if (selectedEntryRef === null) {
    return (
      <div ref={setScrollContainer} className="lumi-reader-bg-image h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
        <ReaderPlaceholder />
      </div>
    )
  }

  if (isPending) {
    return (
      <div ref={setScrollContainer} className="lumi-reader-bg-image h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
        <div className="mx-auto flex max-w-[46rem] flex-col gap-3 p-8 max-lg:px-5" aria-label="文章加载中">
          <Skeleton className="h-3 w-2/5" />
          <Skeleton className="h-8 w-11/12" />
          <Skeleton className="h-8 w-3/4" />
          <div className="mt-4 flex flex-col gap-2.5">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-10/12" />
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
      </div>
    )
  }

  if (isError) {
    const isNotFound =
      error instanceof ApiError && error.status === 404
    if (isNotFound) {
      return (
        <div ref={setScrollContainer} className="lumi-reader-bg-image h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
          <div className="flex h-full items-center justify-center p-8">
            <div className="max-w-sm text-center">
              <p className="text-base font-medium text-[var(--lumi-text-primary)]">
                这篇文章已经不存在或不可用了。
              </p>
              <Button
                variant="secondary"
                onClick={() => selectEntry(null)}
                className="mt-4"
              >
                返回文章列表
              </Button>
            </div>
          </div>
        </div>
      )
    }
    return (
      <div ref={setScrollContainer} className="lumi-reader-bg-image h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
        <div className="flex h-full items-center justify-center p-8">
          <div className="max-w-sm text-center" role="alert">
            <p className="text-base font-medium text-[var(--lumi-text-primary)]">文章加载失败</p>
            <p className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
              {error instanceof Error ? error.message : '请稍后重试。'}
            </p>
            <Button
              variant="secondary"
              onClick={() => refetch()}
              className="mt-4"
            >
              <RefreshCw aria-hidden className="size-3.5" />
              重试
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const detail = data
  // F17 翻页按钮边界：到顶禁用上一屏、到底禁用下一屏（无滚动空间双禁）。
  const pagedUpDisabled = !scrollFlags.canUp
  const pagedDownDisabled = !scrollFlags.canDown
  return (
    <div className="relative h-full bg-[var(--lumi-reader-bg)]">
      {/* F11：阅读进度条（滚动容器顶部；自挂原生 passive 监听） */}
      <ReaderProgress getContainer={getScrollContainer} enabled={readerShowReadingProgress} />
      {/* F072：搜索命中定位 chip（命中 N 处/下一处；正文已变化 → 诚实降级）。
          局部 Suspense 边界：lazy 首帧挂起只影响 chip 本身，绝不把
          Reader 主体（含静态哨兵结构）拖进挂起态。 */}
      <Suspense fallback={null}>
        <SearchHitsChip entryRef={detailEntryRef} getRoot={getFindRoot} detailReady={!isPending && !isError} />
      </Suspense>
      {/* F13：文内查找条（工具栏 Search 按钮打开；Escape/× 关闭清高亮） */}
      {(findOpen || linksOpen) && (
        <Suspense fallback={null}>
          <ArticleFindBar open={findOpen} onClose={() => setFindOpen(false)} getRoot={getFindRoot} />
          {linksOpen && <ArticleLinksPanel containerRef={contentRef} onClose={() => setLinksOpen(false)} />}
        </Suspense>
      )}
      {/* 0010 Gate A：正文宽度消费 --lumi-reader-content-width（默认 46rem
          ≈ 736px，设置中心可调）；0017：页面左右边距消费
          --lumi-reader-page-margin（.lumi-reader-article 连续值，
          移动端 CSS 钳制安全范围）；底部计入 safe area。
          AUDIT-002：同时提供稳定的 .lumi-reader 作用域根，使设置/主题包
          的自定义 CSS（prefixCustomCss 默认前缀 .lumi-reader）在正式 Reader
          中生效（此前正式 Reader 只有 .lumi-reader-article，自定义 CSS 从不命中）。
          F25：滚动容器带 .lumi-reader-scroll 定位基础类（打印/锚定样式）。 */}
      <div
        ref={setScrollContainer}
        onScroll={handleScroll}
        className="lumi-reader-scroll lumi-reader-bg-image h-full overflow-y-auto bg-[var(--lumi-reader-bg)]"
      >
      <article
        ref={articleElementRef}
        className="lumi-reader lumi-reader-article mx-auto py-6"
        style={
          {
            maxWidth: 'var(--lumi-reader-content-width, 46rem)',
            paddingBottom: 'max(1.5rem, var(--safe-bottom))',
            // F055：per-source 覆盖以内联变量作用于本篇（未覆盖的键
            // 继续继承根节点全局值；无覆盖时空对象零影响）。
            ...sourceStyleVars,
          } as CSSProperties
        }
      >
        {/* key=entryRef：切换 Entry = 组件重挂载，旧 mutation 的
            pending / error UI 不泄漏到新 Entry。（三处 key 必须互不相同，
            React 兄弟节点不允许重复 key。） */}
        <Suspense fallback={null}>
          <ReaderHeader
            key={`header-${detail.entryRef}`}
            detail={detail}
            viewMode={viewMode}
            onViewModeChange={handleViewModeChange}
            onOpenAiConversation={() => setAiConversationOpen(true)}
            onOpenFind={() => setFindOpen(true)}
            onOpenLinks={() => setLinksOpen(true)}
            collectSpeechBlocks={collectSpeechBlocks}
            autoScrollState={autoScroll}
            onAutoScrollToggle={() =>
              setAutoScroll((current) => (current === 'running' ? 'paused' : 'running'))
            }
            focusMode={focusMode}
            onFocusModeChange={setFocusMode}
          />
        </Suspense>
        {/* O127 内容优先重排：媒体附件（enclosure 属于内容）紧随标题，
            正文之后才是工具面板（AI 摘要/溯源/自测/知识卡片/关联）——
            打开文章首屏即正文，工具不再把内容推到折叠线下。 */}
        {/* F011：enclosure 播放器（audio/video 附件；显式开始，禁止 autoplay） */}
        <Suspense fallback={null}>
          <EnclosurePlayers key={`enclosures-${detail.entryRef}`} detail={detail} />
        </Suspense>
        {/* Gate：三模式内容区（控件在 ReaderHeader 工具栏；本组件只渲染）。
            original 直渲 ArticleContent（首读关键路径零 lazy）；非 original
            挂 lazy ReaderTranslation，fallback 用同一 ArticleContent 防
            白闪。翻译启动不依赖挂载前的手势注册：ReaderTranslation 的
            第二等级 effect 以 active=viewMode!=='original' 驱动，挂载后
            自启（浏览器引擎 activation 被消费 → 诚实重试，既有语义）。 */}
        {viewMode === 'original' ? (
          <div>
            <ArticleContent detail={detail} />
          </div>
        ) : (
          <Suspense
            fallback={
              <div>
                <ArticleContent detail={detail} />
              </div>
            }
          >
            <ReaderTranslation
              key={`translation-${detail.entryRef}`}
              detail={detail}
              viewMode={viewMode}
              registerTranslationStart={registerTranslationStart}
            />
          </Suspense>
        )}
        {/* P0-2：正文读完判定哨兵——紧贴实际正文结束处（工具面板之前），
            IntersectionObserver 以本滚动容器为 root。 */}
        <div ref={finishRead.sentinelRef} aria-hidden="true" data-finish-sentinel="" className="h-px" />
        {/* P0-2：短文（不足一屏）不自动判定——「读完了」明确按钮作为
            主动确认路径；自动判定失败给可理解的提示与重试入口。 */}
        {finishRead.needsExplicitConfirm && (
          <div className="mt-4 flex justify-center">
            <Button variant="secondary" size="sm" onClick={finishRead.confirmFinished}>
              读完了
            </Button>
          </div>
        )}
        {finishRead.autoError !== null && (
          <p
            role="alert"
            className="mt-3 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-3 py-2 text-xs text-[var(--lumi-danger)]"
          >
            自动标记已读失败：{finishRead.autoError}
            <Button variant="secondary" size="sm" className="ml-2" onClick={finishRead.retry}>
              重试
            </Button>
          </p>
        )}
        {/* 0015：AI 摘要卡片（按需生成；状态机与 Reader 其它 UI 同源）。
            AUDIT-011：key=entryRef 保证切换文章时重挂载，A 的
            pending / error / result 不泄漏到 B（与 translation/conversation 同源）。 */}
        <Suspense fallback={null}>
        <ReaderSummary
          key={`summary-${detail.entryRef}`}
          entryRef={detail.entryRef}
          articleTitle={detail.title}
          articleText={detail.contentText}
        />
        </Suspense>
        {/* F30：资料溯源卡（来源/作者/发布/收录/链接/内容版本；未知诚实显示） */}
        <Suspense fallback={null}>
        <ProvenanceCard key={`provenance-${detail.entryRef}`} detail={detail} />
        </Suspense>
        {/* N031：修订记录（内容哈希变化的摄取历史；无修订不渲染入口） */}
        <Suspense fallback={null}>
          <EntryRevisionsPanel key={`revisions-${detail.entryRef}`} entryRef={detail.entryRef} />
        </Suspense>
        {/* F29：来源相关笔记反向入口（无笔记引用时零渲染） */}
        <Suspense fallback={null}>
        <EntryNotesBacklinks key={`notes-${detail.entryRef}`} entryRef={detail.entryRef} />
        </Suspense>
        {/* F069：文章阅读自测（生成→作答→评分→再来一次） */}
        <Suspense fallback={null}>
        <QuizPanel key={`quiz-${detail.entryRef}`} entryRef={detail.entryRef} />
        </Suspense>
        {/* F070：提取知识卡片（预览→选择编辑→保存） */}
        <Suspense fallback={null}>
        <KnowledgeCardsPanel key={`cards-${detail.entryRef}`} detail={detail} />
        </Suspense>
        {/* F021：手工关联内容（双向列表 + 解除 + 关联选择；无 AI 参与） */}
        <Suspense fallback={null}>
        <ItemRelationsPanel key={`relations-${detail.entryRef}`} itemRef={`rss:${detail.entryRef}`} />
        </Suspense>
        {/* F20：正文锚定高亮/批注（选区浮动条 + 批注卡；设备本地存储）。
            entryRef 必填；contentVersion 缺省时组件按正文文本自行派生，
            锚点失效诚实降级。 */}
        <Suspense fallback={null}>
          <AnnotationsLayer entryRef={detail.entryRef} containerRef={articleScrollRef} />
        </Suspense>
        {/* R05：阅读行辅助线（默认关；正文右上角开关，pointer-events 不遮挡选择） */}
        <Suspense fallback={null}>
          <ReadingRuler containerRef={articleScrollRef} />
        </Suspense>
        {/* 0016：文章限定 AI 对话面板（桌面右侧 / 移动全屏）——条件挂载：
            open-prop 门控的 lazy 仍会首帧拉 chunk；对话框类按 bundle
            guard 契约改为条件挂载 */}
        {aiConversationOpen && (
          <Suspense fallback={null}>
            <ArticleConversation
              key={`conversation-${detail.entryRef}`}
              entryRef={detail.entryRef}
              articleTitle={detail.title}
              open={aiConversationOpen}
              onClose={() => setAiConversationOpen(false)}
            />
          </Suspense>
        )}
      </article>
      </div>
      {/* F17：按屏翻页（滚动容器右下角竖排；连续滚动不受影响）。
          N052：阅读模式 = 分页时由 ReaderPager 接管翻页，F17 不重复出现。 */}
      {!pagedReading && readerPagedMode && (
        <div className="absolute bottom-24 right-4 z-10 flex flex-col gap-1.5" data-lumi-paged-nav="">
          <IconButton
            size="lg"
            icon={<ChevronUp aria-hidden className="size-5" />}
            label="上一屏"
            disabled={pagedUpDisabled}
            onClick={() => pageBy(-1)}
            className="border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-popover)]"
          />
          <IconButton
            size="lg"
            icon={<ChevronDown aria-hidden className="size-5" />}
            label="下一屏"
            disabled={pagedDownDisabled}
            onClick={() => pageBy(1)}
            className="border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-popover)]"
          />
        </div>
      )}
      {/* N052/N053：分页阅读（多栏横向翻页 + 点按翻页区 + 页码指示）。
          局部 Suspense：lazy 首帧挂起只影响翻页 UI 本身。 */}
      <Suspense fallback={null}>
        <ReaderPager
          enabled={pagedReading}
          containerRef={scrollRef}
          articleRef={articleElementRef}
          entryRef={detailEntryRef}
        />
      </Suspense>
      {/* F25：回到顶部 / 返回刚才位置（>600px 且未到底出现；用户滚动重置） */}
      {backMode !== null && (
        <div className="absolute bottom-6 right-4 z-10" data-lumi-back-nav="">
          <IconButton
            size="lg"
            icon={
              backMode === 'top' ? (
                <ArrowUp aria-hidden className="size-5" />
              ) : (
                <History aria-hidden className="size-5" />
              )
            }
            label={backMode === 'top' ? '回到顶部' : '返回刚才位置'}
            onClick={backMode === 'top' ? handleBackToTop : handleReturnToPosition}
            className="border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-popover)]"
          />
        </div>
      )}
      {/* F18：自动滚屏状态 chip（状态文字 + 三档速度 + 暂停/停止） */}
      {autoScroll !== 'off' && (
        <AutoScrollChip
          state={autoScroll}
          speed={autoSpeed}
          onSpeedChange={setAutoSpeed}
          onToggle={() =>
            setAutoScroll((current) => (current === 'running' ? 'paused' : 'running'))
          }
          onStop={() => setAutoScroll('off')}
        />
      )}
    </div>
  )
}
