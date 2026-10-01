/** SidebarCollapsedRail — 桌面侧栏折叠态图标栏（0011 修正补充 §3–§10）。
 *
 * 入口数据唯一真源：lib/nav-registry 的 navGroupsForSidebar()——与展开
 * 态 Sidebar 同源同序同分组（R3 契约 §3 收编，不再维护第二份入口表）。
 * 由此折叠 rail 与展开侧栏的入口集合一致（此前 rail 少了 来源/搜索/
 * 工作区 三个入口）；渲染层只保留 icon-only 形态：
 * - tooltip（hover / focus；native title + aria-label，aria-label 为主）；
 * - active state（subtle background + accent icon，§9）；
 * - ≥40×40 点击区域、icon 居中、零横向溢出（§7）。
 *
 * RSS 折叠态行为（§10）：点击 icon = scope 全部 RSS（等价展开态点
 * 「RSS 订阅」主按钮），不展开 tree——选 feed 需先展开侧栏。
 * P0-12 a11y：真 disabled button（可浏览、语义明确）替代不可聚焦 div。
 * fix-095/fix-292 锚点：`alwaysVisible ? 'flex' : 'hidden lg:flex'` 与
 * `iconCls = 'size-4 shrink-0'` 为既有测试的源码锚，勿改名。 */

import { PanelLeft } from 'lucide-react'
import { useReaderUi, ALL_SCOPE } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import {
  navGroupsForSidebar,
  navTargetOf,
  settingsCategoryOf,
} from '../lib/nav-registry'
import type { NavEntry } from '../lib/nav-registry'
import { requestOpenSettings } from './settings/settings-bridge'
import SettingsButton from './SettingsButton'
import { cx } from './ui/cx'

const iconCls = 'size-4 shrink-0'

/** 折叠态图标行：44×40 可点击区域，icon 水平居中（§7）。 */
function RailItem({
  icon,
  label,
  active,
  disabled,
  note,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  active?: boolean
  disabled?: boolean
  /** 禁用原因（诚实描述）。 */
  note?: string
  onClick?: () => void
}) {
  const cls = cx(
    'flex size-10 items-center justify-center rounded-[var(--lumi-radius-md)]',
    'transition-colors duration-[var(--lumi-motion-fast)]',
    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
    active
      ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent-text)]'
      : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
    disabled && 'cursor-default text-[var(--lumi-text-tertiary)] opacity-70 hover:bg-transparent hover:text-[var(--lumi-text-tertiary)]',
  )
  if (disabled) {
    return (
      <button
        type="button"
        disabled
        aria-disabled="true"
        title={note ?? `${label}（当前不可用）`}
        aria-label={`${label}（当前不可用）`}
        className={cls}
      >
        {icon}
      </button>
    )
  }
  return (
    <button type="button" onClick={onClick} title={label} aria-label={label} aria-current={active ? 'true' : undefined} className={cls}>
      {icon}
    </button>
  )
}

/** 注册表入口的折叠态渲染：active/导航语义与 Sidebar.SidebarEntryRow
 * 同构（home 视图入口只看 view；RSS scope 行额外要求 scope 命中；
 * 纯 section 行只看 section；settings 行深链不参与高亮）。 */
function RailEntry({ entry }: { entry: NavEntry }) {
  const view = useReaderUi((s) => s.view)
  const scope = useReaderUi((s) => s.scope)
  const section = useReaderUi((s) => s.section)
  const selectView = useReaderUi((s) => s.selectView)
  const selectScope = useReaderUi((s) => s.selectScope)
  const selectSection = useReaderUi((s) => s.selectSection)

  const category = settingsCategoryOf(entry.id)
  const target = navTargetOf(entry)
  const Icon = entry.icon

  if (category !== null) {
    return (
      <RailItem
        icon={<Icon aria-hidden className={iconCls} />}
        label={entry.label}
        onClick={() => requestOpenSettings(category)}
      />
    )
  }

  const goHome = (nextView: Parameters<typeof selectView>[0]) => {
    selectSection('home')
    selectScope(ALL_SCOPE)
    selectView(nextView)
  }

  if (entry.id === 'home') {
    return (
      <RailItem
        icon={<Icon aria-hidden className={iconCls} />}
        label={entry.label}
        active={scope.kind === 'all' && view === 'all'}
        onClick={() => goHome('all')}
      />
    )
  }
  if (entry.id === 'source:rss') {
    return (
      <RailItem
        icon={<Icon aria-hidden className={iconCls} />}
        label={entry.label}
        active={scope.kind === 'rss' && view === 'all'}
        onClick={() => {
          // §10：折叠态点击 RSS icon = scope 全部 RSS（不展开 tree）
          selectSection('home')
          selectScope({ kind: 'rss' })
          selectView('all')
        }}
      />
    )
  }

  const isViewEntry = target.view !== undefined
  return (
    <RailItem
      icon={<Icon aria-hidden className={iconCls} />}
      label={entry.label}
      active={
        isViewEntry
          ? view === target.view
          : target.section === section
      }
      onClick={() => {
        if (target.view !== undefined) {
          goHome(target.view)
          return
        }
        selectSection(target.section)
        if (target.scope !== undefined) selectScope(target.scope)
      }}
    />
  )
}

/** P03：平板层复用——`alwaysVisible` 让折叠 rail 不依赖 lg: 媒体查询
 * （tablet 档 <1024，lg: 恒不激活，由 App 的 tier 判定负责挂载）；
 * `onExpand` 覆盖展开动作（平板层的展开/收起是会话内方向默认，
 * 不写持久化设置，避免方向切换泄漏到桌面档）。缺省行为完全不变。 */
interface SidebarCollapsedRailProps {
  alwaysVisible?: boolean
  onExpand?: () => void
}

export default function SidebarCollapsedRail({ alwaysVisible = false, onExpand }: SidebarCollapsedRailProps) {
  const update = useAppSettings((s) => s.update)

  return (
    <nav
      aria-label="主导航（已折叠）"
      className={cx(
        'shrink-0 flex-col items-center gap-1 bg-[var(--lumi-sidebar)] px-1.5 py-2',
        alwaysVisible ? 'flex' : 'hidden lg:flex',
      )}
      style={{ width: '3.5rem' }}
    >
      {/* 展开（折叠控制保留在顶部，§6） */}
      <button
        type="button"
        onClick={onExpand ?? (() => update({ sidebarCollapsed: false }))}
        aria-label="展开侧栏"
        title="展开侧栏"
        className="flex size-10 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <PanelLeft aria-hidden className={iconCls} />
      </button>

      {/* 注册表分组（阅读 → 内容来源 → 工具；与展开态侧栏同源同序） */}
      {navGroupsForSidebar().map((group, i) => (
        <div
          key={group.group}
          role="group"
          aria-label={group.label}
          className={cx('flex flex-col items-center gap-1', i > 0 && 'mt-2')}
        >
          {group.entries.map((entry) => (
            <RailEntry key={entry.id} entry={entry} />
          ))}
        </div>
      ))}

      {/* 设置（§6：折叠态保留设置 icon，同一语义位置） */}
      <div className="mt-auto">
        <SettingsButton collapsed />
      </div>
    </nav>
  )
}
