/** Gate 2 视觉重建测试 — Sidebar 分类色 / EntryRow 状态语义 / Shell token 化。
 *
 * 既有 shell.test 覆盖行为；这里补 0009 特有的视觉语义断言。 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { EntryListItem } from '../api/types'
import EntryRow from '../components/EntryRow'

/** EntryRow 直测（不经 App，mock store 依赖在模块内已由 zustand 真实 store 满足） */
function makeItem(over: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: 'e1.x',
    title: '标题',
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-08-29T10:00:00Z',
    read: false,
    starred: false,
    ...over,
  }
}

describe('EntryRow — 0009 Gate 2 状态语义（AC10）', () => {
  it('未读：标题 font-medium + accent 圆点存在', () => {
    const { container } = render(<EntryRow item={makeItem({ read: false })} selected={false} />)
    const title = screen.getByText('标题')
    expect(title.className).toContain('font-medium')
    // 圆点元素存在（aria-hidden 装饰）
    const dot = container.querySelector('span[aria-hidden="true"].rounded-full')
    expect(dot).not.toBeNull()
  })

  it('已读：标题 font-normal + 圆点透明（不只靠颜色：字重差异可见）', () => {
    const { container } = render(<EntryRow item={makeItem({ read: true })} selected={false} />)
    expect(screen.getByText('标题').className).toContain('font-normal')
    const dot = container.querySelector('span[aria-hidden="true"].rounded-full') as HTMLElement
    expect(dot.className).toContain('bg-transparent')
  })

  it('收藏：星形图标带 aria-label（可访问语义）', () => {
    render(<EntryRow item={makeItem({ starred: true })} selected={false} />)
    expect(screen.getByLabelText('已收藏')).toBeInTheDocument()
  })

  it('选中：selected surface（低透明度，非浓色边框/填充）', () => {
    render(<EntryRow item={makeItem()} selected />)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-[var(--lumi-surface-selected)]')
    // 旧实现的 border-l-2 高亮边已移除
    expect(btn.className).not.toContain('border-l-2')
  })

  it('未选中：hover surface 而非选中 surface', () => {
    render(<EntryRow item={makeItem()} selected={false} />)
    expect(screen.getByRole('button').className).toContain('hover:bg-[var(--lumi-surface-hover)]')
  })

  it('作者仅在桌面行内显示（hidden lg:inline）', () => {
    render(<EntryRow item={makeItem({ author: '作者甲' })} selected={false} />)
    expect(screen.getByText(/作者甲/).className).toContain('lg:inline')
  })

  it('无硬编码 Tailwind 调色板类（AC3 迁移验证）', () => {
    const { container } = render(
      <EntryRow item={makeItem({ read: true, starred: true })} selected />,
    )
    const all = container.innerHTML
    expect(all).not.toMatch(/(?:bg|text|border)-(?:blue|gray|amber|red)-\d/)
  })
})
