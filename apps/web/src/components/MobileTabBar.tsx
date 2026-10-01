/** MobileTabBar — <768px 底部导航岛（0011 Gate 1，四入口重构；P04 调整）。
 *
 * 四个一级入口（Spec §设计规格，替代 0010 的 时间线/收藏/设置 三 tab）：
 *   首页（AppSection home）/ 来源（sources）/ 搜索（search）/ 收藏（favorites）
 *
 * R3 契约 §3：入口数据（成员、顺序、图标、紧凑标签）唯一真源是
 * lib/nav-registry（tabbar 表面 + shortLabel），本组件只保留渲染层。
 * 首页 tab 的注册表 label 是「全部信息源」，底栏用注册表 shortLabel
 * 「首页」（sidebar 同一入口保持全称）。
 *
 * P04：原「订阅」tab 升级为「来源」（统一来源管理页）——RSS 订阅仍
 * 可达（来源页 RSS 组深链 + 侧栏 RSS 订阅行 / 订阅中心 section）。 *
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
 * 0020 AUDIT-016：<1024px 渲染（此前仅 <768）。768–1023 的中间/平板
 * 宽度仍是移动 section 布局（section 页面为 lg:hidden），但 Drawer 里的
 * Sidebar 只能导航到 home，导致「订阅/搜索」无法进入。把底栏 section
 * 切换器延伸到整个 <1024 区间即修复该缺口（沿用既有响应式系统，
 * 不重新设计导航）。 */

import { useReaderUi } from '../store/reader-ui'
import { navEntriesForSurface, navTargetOf } from '../lib/nav-registry'
import { cx } from './ui/cx'

export default function MobileTabBar() {
  const section = useReaderUi((s) => s.section)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectSection = useReaderUi((s) => s.selectSection)

  // Reader 打开 → 底栏隐藏（全屏阅读）
  const readerOpen = selectedEntryRef !== null

  // 入口数据来自导航注册表（tabbar 表面按 order 排列）
  const tabs = navEntriesForSurface('tabbar')

  if (readerOpen) return null

  return (
    <nav aria-label="底部导航" className="px-3 pb-2 lg:hidden" style={{ paddingBottom: 'calc(var(--safe-bottom) + 0.5rem)' }}>
      <div
        className={cx(
          'lumi-glass flex rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)]',
          'shadow-[var(--lumi-shadow-floating)]',
        )}
      >
        {tabs.map((tab) => {
          const target = navTargetOf(tab)
          const active = section === target.section
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => selectSection(target.section)}
              aria-current={active ? 'page' : undefined}
              className={cx(
                'flex min-h-12 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5',
                'transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                active
                  ? 'text-[var(--lumi-accent-text)] [&_svg]:fill-[var(--lumi-accent-soft)]'
                  : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
              )}
            >
              <Icon aria-hidden className="size-5" />
              <span className={cx('text-[11px] leading-tight', active && 'font-semibold')}>
                {tab.shortLabel ?? tab.label}
              </span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
