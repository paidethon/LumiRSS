/** MobilePageHeader — 移动端共用页面 Header（0011 Gate 1，参考图矩阵）。
 *
 * 三列 grid（44px 左操作 | 1fr 居中标题 | 44px 右操作）保证标题真正
 * 居中：左右列固定等宽，标题列弹性收缩。
 *
 * - 左侧默认菜单（打开导航抽屉）；Reader 等沉浸场景可传返回；
 * - 右侧仅放当前页面真实可用的操作；没有功能时传等宽占位（不放假按钮）；
 * - 不渲染系统状态栏（参考图中的 9:41 等不属于应用）。
 */

import type { ReactNode } from 'react'
import { useReaderUi } from '../store/reader-ui'

export default function MobilePageHeader({
  title,
  subtitle,
  left,
  right,
}: {
  title: string
  /** 可选副标题（如首页动态 scope 的来源），超长自动截断 */
  subtitle?: string
  /** 左侧操作；缺省渲染打开导航的菜单按钮 */
  left?: ReactNode
  /** 右侧操作；缺省渲染等宽不可聚焦占位（保持标题居中） */
  right?: ReactNode
}) {
  const openMobileSidebar = useReaderUi((s) => s.openMobileSidebar)
  const mobileSidebarOpen = useReaderUi((s) => s.mobileSidebarOpen)

  return (
    <header
      className="grid grid-cols-[44px_minmax(0,1fr)_44px] items-center gap-2 border-b border-[var(--lumi-separator)] bg-[var(--lumi-surface)] px-2 py-2 lg:hidden"
      style={{ paddingTop: 'var(--safe-top)' }}
    >
      <div className="flex min-h-11 items-center">
        {left ?? (
          <button
            type="button"
            onClick={openMobileSidebar}
            aria-expanded={mobileSidebarOpen}
            aria-controls="mobile-navigation-drawer"
            aria-label="打开导航"
            className="flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18" fill="none">
              <path d="M2 4h14M2 9h14M2 14h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      <div className="min-w-0 text-center">
        <h1 className="truncate text-[15px] font-semibold leading-tight text-[var(--lumi-text-primary)]">
          {title}
        </h1>
        {subtitle !== undefined && (
          <p className="truncate text-xs leading-tight text-[var(--lumi-text-tertiary)]">
            {subtitle}
          </p>
        )}
      </div>

      <div className="flex min-h-11 items-center justify-end">{right ?? null}</div>
    </header>
  )
}
