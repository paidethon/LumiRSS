/** R02 — SidebarCollapsedRail 收编 nav-registry（契约 §3：入口数据唯一真源）。
 *
 * 折叠 rail 与展开态 Sidebar 消费同一份 navGroupsForSidebar()：
 * - 分组 aria-label 用 NAV_GROUP_LABELS（阅读/内容来源/工具）；
 * - 入口集合 = sidebar 表面全集（含此前 rail 缺失的 来源/搜索/工作区）；
 * - settings 深链入口（API 来源/邮件简报/RAG 索引）派发 settings-bridge
 *   事件且不带 active 高亮；
 * - §10：RSS icon 点击 = scope 全部 RSS，不展开 tree。
 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import SidebarCollapsedRail from '../components/SidebarCollapsedRail'
import { useReaderUi } from '../store/reader-ui'
import { ALL_SCOPE } from '../store/reader-ui'
import { navGroupsForSidebar } from '../lib/nav-registry'
import { onOpenSettingsRequest } from '../components/settings/settings-bridge'

beforeEach(() => {
  useReaderUi.setState({
    section: 'home',
    scope: { kind: 'all' },
    view: 'all',
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

describe('折叠 rail 与 nav-registry 同源（R02 收编）', () => {
  it('分组与入口集合 = navGroupsForSidebar() 全集（含此前缺失的 来源/搜索/工作区）', () => {
    render(<SidebarCollapsedRail />)
    for (const group of navGroupsForSidebar()) {
      const groupEl = screen.getByRole('group', { name: group.label })
      for (const entry of group.entries) {
        // 每个注册表入口都有一个 icon-only 按钮（可访问名称 = 入口 label）
        expect(
          within(groupEl).getByRole('button', { name: entry.label }),
        ).toBeInTheDocument()
      }
    }
    // 三个此前折叠态缺失的入口现在与展开侧栏一致
    expect(screen.getByRole('button', { name: '来源' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '搜索' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '工作区' })).toBeInTheDocument()
  })

  it('settings 深链入口派发 settings-bridge 事件；section 入口导航且高亮', () => {
    const opened: Array<string | undefined> = []
    const off = onOpenSettingsRequest((detail) => opened.push(detail.category))
    render(<SidebarCollapsedRail />)
    fireEvent.click(screen.getByRole('button', { name: 'API 来源' }))
    fireEvent.click(screen.getByRole('button', { name: '邮件简报' }))
    fireEvent.click(screen.getByRole('button', { name: 'RAG 索引' }))
    expect(opened).toEqual(['api-sources', 'mail', 'ai'])
    off()

    fireEvent.click(screen.getByRole('button', { name: '收件箱' }))
    expect(useReaderUi.getState().section).toBe('inbox')
    expect(
      screen.getByRole('button', { name: '收件箱' }).getAttribute('aria-current'),
    ).toBe('true')
  })

  it('§10：RSS icon 点击 = home + scope 全部 RSS + all 视图（不展开 tree）', () => {
    render(<SidebarCollapsedRail />)
    fireEvent.click(screen.getByRole('button', { name: 'RSS 订阅' }))
    const state = useReaderUi.getState()
    expect(state.section).toBe('home')
    expect(state.scope).toEqual({ kind: 'rss' })
    expect(state.view).toBe('all')

    // home 视图入口：点击 = home + ALL_SCOPE + 对应 view
    fireEvent.click(screen.getByRole('button', { name: '稍后读' }))
    const after = useReaderUi.getState()
    expect(after.section).toBe('home')
    expect(after.scope).toEqual(ALL_SCOPE)
    expect(after.view).toBe('read-later')
  })
})
