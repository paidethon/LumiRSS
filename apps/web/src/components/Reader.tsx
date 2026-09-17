import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useEntryDetail } from '../api/queries'
import { ApiError } from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import {
  captureAnchorText,
  findAnchorElement,
  loadReadingPosition,
  saveReadingPosition,
} from '../lib/reading-position'
import type { ReaderViewMode } from '../lib/translation-blocks'
import ArticleConversation from './ArticleConversation'
import ReaderHeader from './ReaderHeader'
import ReaderPlaceholder from './ReaderPlaceholder'
import ReaderSummary from './ReaderSummary'
import ProvenanceCard from './ProvenanceCard'
import ReaderTranslation from './ReaderTranslation'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'

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
 * 无记录则回到顶部。 */
export default function Reader() {
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const { data, isPending, isError, error, refetch } = useEntryDetail(selectedEntryRef)
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

// 阅读位置恢复（pool #01）：按 ItemRef 记录滚动比例 + 段落锚点，切换
// 返回时恢复；锚点优先、ratio 回退，正文改版只会落在本篇内。只读滚动
// 位置，绝不触碰已读状态。列表窗格滚动与正文互不影响。
const restorePosition = useCallback(() => {
  const container = scrollRef.current
  if (container === null || selectedEntryRef === null) return
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
}, [selectedEntryRef])

useEffect(() => {
  restorePosition()
}, [restorePosition])

// 正文渲染完成后再恢复一次——此时锚点段落可被真正命中。
const detailEntryRef = data?.entryRef ?? null
useEffect(() => {
  if (detailEntryRef !== null) restorePosition()
}, [detailEntryRef, restorePosition])

// 滚动保存：rAF 合并；锚点取视口顶 80px 线上方最近的正文段落。
const saveTickRef = useRef<number | null>(null)
const handleScroll = useCallback(() => {
  if (saveTickRef.current !== null) return
  saveTickRef.current = requestAnimationFrame(() => {
    saveTickRef.current = null
    const container = scrollRef.current
    if (container === null || selectedEntryRef === null) return
    const max = container.scrollHeight - container.clientHeight
    const ratio = max > 0 ? container.scrollTop / max : 0
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
  })
}, [selectedEntryRef])

  if (selectedEntryRef === null) {
    return (
      <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
        <ReaderPlaceholder />
      </div>
    )
  }

  if (isPending) {
    return (
      <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
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
        <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
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
      <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
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
  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]"
    >
      {/* 0010 Gate A：正文宽度消费 --lumi-reader-content-width（默认 46rem
          ≈ 736px，设置中心可调）；0017：页面左右边距消费
          --lumi-reader-page-margin（.lumi-reader-article 连续值，
          移动端 CSS 钳制安全范围）；底部计入 safe area。
          AUDIT-002：同时提供稳定的 .lumi-reader 作用域根，使设置/主题包
          的自定义 CSS（prefixCustomCss 默认前缀 .lumi-reader）在正式 Reader
          中生效（此前正式 Reader 只有 .lumi-reader-article，自定义 CSS 从不命中）。 */}
      <article
        className="lumi-reader lumi-reader-article mx-auto py-6"
        style={{
          maxWidth: 'var(--lumi-reader-content-width, 46rem)',
          paddingBottom: 'max(1.5rem, var(--safe-bottom))',
        }}
      >
        {/* key=entryRef：切换 Entry = 组件重挂载，旧 mutation 的
            pending / error UI 不泄漏到新 Entry。（三处 key 必须互不相同，
            React 兄弟节点不允许重复 key。） */}
        <ReaderHeader
          key={`header-${detail.entryRef}`}
          detail={detail}
          viewMode={viewMode}
          onViewModeChange={handleViewModeChange}
          onOpenAiConversation={() => setAiConversationOpen(true)}
        />
        {/* 0015：AI 摘要卡片（按需生成；状态机与 Reader 其它 UI 同源）。
            AUDIT-011：key=entryRef 保证切换文章时重挂载，A 的
            pending / error / result 不泄漏到 B（与 translation/conversation 同源）。 */}
        <ReaderSummary key={`summary-${detail.entryRef}`} entryRef={detail.entryRef} />
        {/* F30：资料溯源卡（来源/作者/发布/收录/链接/内容版本；未知诚实显示） */}
        <ProvenanceCard key={`provenance-${detail.entryRef}`} detail={detail} />
        {/* Gate：三模式内容区（控件在 ReaderHeader 工具栏；本组件只渲染）。
            P0-11：注册浏览器引擎的手势启动回调（点击 → 直接编排）。 */}
        <ReaderTranslation
          key={`translation-${detail.entryRef}`}
          detail={detail}
          viewMode={viewMode}
          registerTranslationStart={registerTranslationStart}
        />
        {/* 0016：文章限定 AI 对话面板（桌面右侧 / 移动全屏） */}
        <ArticleConversation
          key={`conversation-${detail.entryRef}`}
          entryRef={detail.entryRef}
          articleTitle={detail.title}
          open={aiConversationOpen}
          onClose={() => setAiConversationOpen(false)}
        />
      </article>
    </div>
  )
}
