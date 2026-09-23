/** SidebarCollapsedRail — 桌面侧栏折叠态图标栏（0011 修正补充 §3–§10）。
 *
 * 修正的问题：折叠态此前只渲染一个「展开侧栏」按钮——文字隐藏成功，
 * 但导航 icons 也一起消失（空 rail）。本组件保留现有 collapse 行为，
 * 只让 icon 在折叠态继续渲染，并补齐 icon-only 导航所需的：
 * - tooltip（hover / focus；native title + aria-label，aria-label 为主）；
 * - active state（subtle background + accent icon，§9）；
 * - disabled state（Phase 2 项，aria-disabled + opacity）；
 * - ≥40×40 点击区域、icon 居中、零横向溢出（§7）。
 *
 * 单一导航数据：与 Sidebar 共享同一组 items 定义（§4 不复制两套菜单）。
 * RSS 折叠态行为（§10）：点击 icon = scope 全部 RSS（等价展开态点
 * 「RSS 订阅」主按钮），不展开 tree——选 feed 需先展开侧栏。 */

import {
  Archive,
  Bot,
  Bookmark,
  Clock,
  FileText,
  Globe,
  Inbox,
  Link2,
  Mail,
  PanelLeft,
  Rss,
  Star,
  Tags,
  Zap,
} from 'lucide-react'
import { useReaderUi, ALL_SCOPE } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { requestOpenSettings } from './settings/settings-bridge'
import SettingsButton from './SettingsButton'
import { cx } from './ui/cx'

const iconCls = 'size-4 shrink-0'

/** 折叠态图标行：44×40 可点击区域，icon 水平居中（§7）。
 * P0-12 a11y：禁用项改用真 disabled button（可浏览、语义明确），
 * 不再用不可聚焦 div + aria-disabled。 */
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
  /** 禁用原因（P0-12：诚实描述，不再统一说「Phase 2 规划」）。 */
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

/** P03：平板层复用——`alwaysVisible` 让折叠 rail 不依赖 lg: 媒体查询
 * （tablet 档 <1024，lg: 恒不激活，由 App 的 tier 判定负责挂载）；
 * `onExpand` 覆盖展开动作（平板层的展开/收起是会话内方向默认，
 * 不写持久化设置，避免方向切换泄漏到桌面档）。缺省行为完全不变。 */
interface SidebarCollapsedRailProps {
  alwaysVisible?: boolean
  onExpand?: () => void
}

export default function SidebarCollapsedRail({ alwaysVisible = false, onExpand }: SidebarCollapsedRailProps) {
  const view = useReaderUi((s) => s.view)
  const scope = useReaderUi((s) => s.scope)
  const section = useReaderUi((s) => s.section)
  const selectView = useReaderUi((s) => s.selectView)
  const selectScope = useReaderUi((s) => s.selectScope)
  const selectSection = useReaderUi((s) => s.selectSection)
  const update = useAppSettings((s) => s.update)

  const goHome = (nextView: Parameters<typeof selectView>[0]) => () => {
    selectSection('home')
    selectScope(ALL_SCOPE)
    selectView(nextView)
  }

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
        <PanelLeft aria-hidden className="size-4" />
      </button>

      {/* 信息来源：icon only（active = scope 命中） */}
      <div className="flex flex-col items-center gap-1" role="group" aria-label="信息来源">
        <RailItem
          icon={<Inbox aria-hidden className={iconCls} />}
          label="全部信息流"
          active={scope.kind === 'all' && view === 'all'}
          onClick={goHome('all')}
        />
        <RailItem
          icon={<Rss aria-hidden className={iconCls} />}
          label="RSS 订阅"
          active={scope.kind === 'rss' && view === 'all'}
          onClick={() => {
            // §10：折叠态点击 RSS icon = scope 全部 RSS（不展开 tree）
            selectSection('home')
            selectScope({ kind: 'rss' })
            selectView('all')
          }}
        />
        {/* phase2 Gate 3：网页剪藏 / 网页快照（library 域）已可用 */}
        <RailItem
          icon={<Globe aria-hidden className={iconCls} />}
          label="网页剪藏"
          active={section === 'clips'}
          onClick={() => selectSection('clips')}
        />
        <RailItem
          icon={<Link2 aria-hidden className={iconCls} />}
          label="网页快照"
          active={section === 'snapshots'}
          onClick={() => selectSection('snapshots')}
        />
        {/* 0021：收件箱（推送式来源）已可用 */}
        <RailItem
          icon={<Archive aria-hidden className={iconCls} />}
          label="收件箱"
          active={section === 'inbox'}
          onClick={() => selectSection('inbox')}
        />
        {/* P0-12：API 来源 / 邮件简报真实可用 → 真实入口（设置深链）。 */}
        <RailItem
          icon={<FileText aria-hidden className={iconCls} />}
          label="API 来源"
          onClick={() => requestOpenSettings('api-sources')}
        />
        <RailItem
          icon={<Mail aria-hidden className={iconCls} />}
          label="邮件简报"
          onClick={() => requestOpenSettings('mail')}
        />
        {/* phase2 M1：书签（library 域）已可用 */}
        <RailItem
          icon={<Bookmark aria-hidden className={iconCls} />}
          label="书签"
          active={section === 'bookmarks'}
          onClick={() => selectSection('bookmarks')}
        />
        {/* phase2 G6：Obsidian 库（只读投影）已可用——section 导航。 */}
        <RailItem
          icon={<FileText aria-hidden className={iconCls} />}
          label="Obsidian 库"
          active={section === 'obsidian'}
          onClick={() => selectSection('obsidian')}
        />
      </div>

      {/* 工作区 */}
      <div className="mt-2 flex flex-col items-center gap-1" role="group" aria-label="工作区">
        <RailItem
          icon={<Clock aria-hidden className={iconCls} />}
          label="稍后读"
          active={view === 'read-later'}
          onClick={goHome('read-later')}
        />
        <RailItem
          icon={<Star aria-hidden className={iconCls} />}
          label="收藏"
          active={view === 'starred'}
          onClick={goHome('starred')}
        />
        {/* phase2 G7：Agent 工作台已可用。 */}
        <RailItem
          icon={<Bot aria-hidden className={iconCls} />}
          label="Agent 工作台"
          active={section === 'agent'}
          onClick={() => selectSection('agent')}
        />
        {/* P0-12 + Q-P2-24：RAG 管理入口已落地（设置 → AI）——不再诚实
            禁用+旧文案（「独立管理入口尚未提供」已不成立）。 */}
        <RailItem
          icon={<Zap aria-hidden className={iconCls} />}
          label="RAG 索引"
          onClick={() => requestOpenSettings('ai')}
        />
        {/* phase2 G8：标签 / 图谱已可用。 */}
        <RailItem
          icon={<Tags aria-hidden className={iconCls} />}
          label="标签 / 图谱"
          active={section === 'graph'}
          onClick={() => selectSection('graph')}
        />
      </div>

      {/* 设置（§6：折叠态保留设置 icon，同一语义位置） */}
      <div className="mt-auto">
        <SettingsButton collapsed />
      </div>
    </nav>
  )
}
