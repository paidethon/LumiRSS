import { ChevronLeft } from 'lucide-react'
import { useFeeds } from '../api/queries'
import type { UiView } from '../lib/read-later'
import { scopeTitle } from '../lib/navigation'
import { useReaderUi } from '../store/reader-ui'
import MobilePageHeader from './MobilePageHeader'

const VIEW_LABELS: Record<UiView, string> = {
  all: '全部信息源',
  unread: '未读',
  starred: '收藏',
  'read-later': '稍后读',
}

/** MobileHeader — <1024px 顶栏控制器（0011 重构 + 阻断修复 §23）。
 *
 * 基于 MobilePageHeader 三列 grid（标题真正居中），一行式：
 *   ☰   当前 Scope（全部信息源 / RSS 订阅 / 分类名 / Feed 名）   全部
 * - Reader 打开时左侧变返回（selectEntry(null)，Query cache 直接恢复）；
 * - feed scope 标题用 feeds 数据补全真实 feed 名；
 * - 首页右侧为真实的全部/未读过滤入口。 */
export default function MobileHeader() {
  const section = useReaderUi((s) => s.section)
  const scope = useReaderUi((s) => s.scope)
  const view = useReaderUi((s) => s.view)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectView = useReaderUi((s) => s.selectView)
  const selectEntry = useReaderUi((s) => s.selectEntry)

  const feeds = useFeeds()
  const feedTitle =
    scope.kind === 'rss-feed'
      ? (feeds.data?.find((feed) => feed.feedUrl === scope.feedUrl)?.title ?? '订阅源')
      : null

  const readerOpen = selectedEntryRef !== null

  // scope 标题：feed 名 > scope 名（§23 示例：FreshRSS releases / 技术 / RSS 订阅）
  const scopeLabel = feedTitle ?? scopeTitle(scope)
  const homeTitle = view === 'all' || view === 'unread' ? scopeLabel : VIEW_LABELS[view]
  const SECTION_TITLES = {
    home: homeTitle,
    subscriptions: '订阅',
    search: '搜索',
    favorites: '收藏',
  } as const

  return (
    <MobilePageHeader
      title={readerOpen ? '阅读' : SECTION_TITLES[section]}
      subtitle={readerOpen ? homeTitle : section === 'home' && feedTitle ? 'RSS 订阅' : undefined}
      left={
        readerOpen ? (
          // 图标按钮：Header 左列固定 44px（保证标题居中），图标+文字
          // 会被挤压换行成竖排——纯 chevron，语义由 aria-label 承载
          <button
            type="button"
            onClick={() => selectEntry(null)}
            aria-label="返回文章列表"
            className="flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-accent-text)] transition-colors hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
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
            onClick={() => selectView(view === 'unread' ? 'all' : 'unread')}
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
