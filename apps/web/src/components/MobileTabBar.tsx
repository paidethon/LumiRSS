/** MobileTabBar — <768px 底部导航岛（0011 Gate 1，四入口重构）。
 *
 * 四个一级入口（Spec §设计规格，替代 0010 的 时间线/收藏/设置 三 tab）：
 *   首页（AppSection home）/ 订阅（subscriptions）/ 搜索（search）/ 收藏（favorites）
 *
 * 导航岛形态（参考图 05-home 意图，非像素复刻）：
 * - 悬浮圆角容器：左右响应式 inset + 底部 safe-area 计入；
 * - 轻边框 + 克制阴影 + 实色表面（半透明/blur 仅点缀；无 backdrop-blur
 *   依赖，实色降级即默认态）；
 * - 触摸目标 ≥44px；图标与文字垂直排列；active 不只靠颜色（图标
 *   fill + 字重）+ aria-current="page"；
 * - 页面内容需自行预留底部 padding（App 层动态注入），最后一条不被遮挡。
 *
 * 设置不在底栏（Spec 硬性要求）：统一在侧边栏品牌区右上角
 * （SidebarHeader），移动端开 MobileSettingsScreen、桌面开 SettingsModal。
 * Reader 打开（selectedEntryRef != null）时隐藏（全屏阅读）。
 *
 * 仅 <768px 渲染；768–1023 保持 Drawer + list/detail（用户已确认）。 */

import { Home, Rss, Search, Star } from 'lucide-react'
import { useReaderUi, type AppSection } from '../store/reader-ui'
import { cx } from './ui/cx'

export default function MobileTabBar() {
  const section = useReaderUi((s) => s.section)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectSection = useReaderUi((s) => s.selectSection)

  // Reader 打开 → 底栏隐藏（全屏阅读）
  const readerOpen = selectedEntryRef !== null

  const tabs: { key: AppSection; label: string; icon: React.ReactNode }[] = [
    { key: 'home', label: '首页', icon: <Home aria-hidden className="size-5" /> },
    { key: 'subscriptions', label: '订阅', icon: <Rss aria-hidden className="size-5" /> },
    { key: 'search', label: '搜索', icon: <Search aria-hidden className="size-5" /> },
    { key: 'favorites', label: '收藏', icon: <Star aria-hidden className="size-5" /> },
  ]

  if (readerOpen) return null

  return (
    <nav aria-label="底部导航" className="px-3 pb-2 md:hidden" style={{ paddingBottom: 'calc(var(--safe-bottom) + 0.5rem)' }}>
      <div
        className={cx(
          'flex rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)]',
          'bg-[var(--lumi-elevated)] shadow-[var(--lumi-shadow-floating)]',
        )}
      >
        {tabs.map((tab) => {
          const active = section === tab.key
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => selectSection(tab.key)}
              aria-current={active ? 'page' : undefined}
              className={cx(
                'flex min-h-12 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5',
                'transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                active
                  ? 'text-[var(--lumi-accent)] [&_svg]:fill-[var(--lumi-accent-soft)]'
                  : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
              )}
            >
              {tab.icon}
              <span className={cx('text-[11px] leading-none', active && 'font-semibold')}>
                {tab.label}
              </span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
