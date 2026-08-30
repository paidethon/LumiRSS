import { ChevronLeft } from 'lucide-react'
import { useFeeds } from '../api/queries'
import type { EntryView } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import MobilePageHeader from './MobilePageHeader'

const VIEW_LABELS: Record<EntryView, string> = {
  all: '全部信息流',
  unread: '未读',
  starred: '收藏',
}

/** MobileHeader — <1024px 顶栏控制器（0011 Gate 1 重构）。
 *
 * 基于 MobilePageHeader 三列 grid（标题真正居中）：
 * - 按当前 AppSection 渲染页面标题；首页标题为动态 scope
 *   （参考图 05-home：全部信息流 / 未读 / 某个订阅源）；
 * - Reader 打开时左侧变返回（selectEntry(null)，Query cache 直接
 *   恢复列表，不重新 fetch——0007 语义保留）；
 * - 首页右侧为真实的已读/未读过滤入口（view 切换）。
 */
export default function MobileHeader() {
  const section = useReaderUi((s) => s.section)
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectView = useReaderUi((s) => s.selectView)
  const selectFeed = useReaderUi((s) => s.selectFeed)
  const selectEntry = useReaderUi((s) => s.selectEntry)

  const feeds = useFeeds()
  const feedTitle =
    selectedFeedUrl === null
      ? null
      : (feeds.data?.find((feed) => feed.feedUrl === selectedFeedUrl)?.title ??
        null)

  const readerOpen = selectedEntryRef !== null

  // 首页动态 scope：feed 标题 > view 标签
  const homeTitle = feedTitle ?? VIEW_LABELS[view]
  const SECTION_TITLES = {
    home: homeTitle,
    subscriptions: '订阅',
    search: '搜索',
    favorites: '收藏',
  } as const

  return (
    <MobilePageHeader
      title={readerOpen ? '阅读' : SECTION_TITLES[section]}
      subtitle={readerOpen ? homeTitle : section === 'home' && feedTitle ? 'LumiRSS' : undefined}
      left={
        readerOpen ? (
          // 图标按钮：Header 左列固定 44px（保证标题居中），图标+文字
          // 会被挤压换行成竖排——改纯 chevron，语义由 aria-label 承载
          <button
            type="button"
            onClick={() => selectEntry(null)}
            aria-label="返回文章列表"
            className="flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-accent)] transition-colors hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <ChevronLeft aria-hidden className="size-5" />
          </button>
        ) : undefined
      }
      right={
        !readerOpen && section === 'home' ? (
          // 首页真实过滤入口：全部/未读切换（复用 view 语义）
          <button
            type="button"
            onClick={() => {
              selectView(view === 'unread' ? 'all' : 'unread')
              selectFeed(null)
            }}
            aria-pressed={view === 'unread'}
            className="flex min-h-9 min-w-9 items-center justify-center rounded-[var(--lumi-radius-md)] px-1.5 text-xs transition-colors hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            style={view === 'unread' ? { color: 'var(--lumi-accent)' } : undefined}
          >
            {view === 'unread' ? '未读' : '全部'}
          </button>
        ) : undefined
      }
    />
  )
}
