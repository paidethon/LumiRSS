/** MobileTabBar — <768px 底部 Tab 导航（0010 Gate D，Folo 同款模式）。
 *
 * 三个 Tab（Folo 移动端验证过的拇指可达模式）：
 *   时间线（列表页）/ 收藏（Starred 视图）/ 设置（全屏设置页）
 *
 * 行为：
 * - 触摸目标 ≥44px + safe-bottom 计入（硬边界 9）；
 * - Reader 打开时（selectedEntryRef != null）Tab 栏隐藏（全屏阅读）；
 * - 时间线/收藏切换 view（复用既有 store 语义），设置 Tab 打开全屏设置页
 *   （非 Modal——手机屏幕小，Modal 装不下设置中心）；
 * - 仅 <768px 渲染（768–1023 仍是 Drawer + list/detail，硬边界 16）。 */

import { Inbox, Settings, Star } from 'lucide-react'
import { useState } from 'react'
import { useReaderUi } from '../store/reader-ui'
import MobileSettingsScreen from './MobileSettingsScreen'
import { cx } from './ui/cx'

type TabKey = 'timeline' | 'starred' | 'settings'

export default function MobileTabBar() {
  const view = useReaderUi((s) => s.view)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectView = useReaderUi((s) => s.selectView)
  const selectFeed = useReaderUi((s) => s.selectFeed)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Reader 打开 → Tab 隐藏（但设置页打开时仍要渲染 MobileSettingsScreen）
  const readerOpen = selectedEntryRef !== null

  const activeTab: TabKey = settingsOpen ? 'settings' : view === 'starred' ? 'starred' : 'timeline'

  const tabs: { key: TabKey; label: string; icon: React.ReactNode; onClick: () => void }[] = [
    {
      key: 'timeline',
      label: '时间线',
      icon: <Inbox aria-hidden className="size-5" />,
      onClick: () => {
        selectView('all')
        selectFeed(null)
      },
    },
    {
      key: 'starred',
      label: '收藏',
      icon: <Star aria-hidden className="size-5" />,
      onClick: () => {
        selectView('starred')
        selectFeed(null)
      },
    },
    {
      key: 'settings',
      label: '设置',
      icon: <Settings aria-hidden className="size-5" />,
      onClick: () => setSettingsOpen(true),
    },
  ]

  return (
    <>
      {/* 全屏设置页（0010a Gate E：Folo 移动端模式，非 Modal） */}
      <MobileSettingsScreen
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      {!readerOpen && (
        <nav
          aria-label="底部导航"
          className="flex border-t border-[var(--lumi-separator)] bg-[var(--lumi-surface)] md:hidden"
          style={{ paddingBottom: 'var(--safe-bottom)' }}
        >
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={tab.onClick}
              aria-current={activeTab === tab.key ? 'true' : undefined}
              className={cx(
                'flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 px-2 py-1',
                'transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                activeTab === tab.key
                  ? 'text-[var(--lumi-accent)]'
                  : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
              )}
            >
              {tab.icon}
              <span className="text-[11px] leading-none">{tab.label}</span>
            </button>
          ))}
        </nav>
      )}
    </>
  )
}
