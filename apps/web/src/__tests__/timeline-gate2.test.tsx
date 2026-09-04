/** Gate 2 视觉重建测试 — Sidebar 分类色 / EntryRow 状态语义 / Shell token 化。
 *
 * 既有 shell.test 覆盖行为；这里补 0009 特有的视觉语义断言。
 * 0011 修正补充：EntryRow 重构为 div[role=row] + 标题区 button +
 * EntryActionButtons（Clock/Star）——断言适配新结构（行根不再是
 * button；星标改为可点击按钮 aria-label「收藏/取消收藏」）。 */

import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it } from 'vitest'
import type { EntryListItem } from '../api/types'
import EntryRow from '../components/EntryRow'
import { useReadLater } from '../store/read-later'

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

/** EntryActionButtons 内含 mutation hook（useQueryClient）——需要 Provider */
function renderRow(item: EntryListItem, selected: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <EntryRow item={item} selected={selected} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useReadLater.setState({ items: [] })
})

describe('EntryRow — 状态语义（AC10；0011 结构适配）', () => {
  it('未读：标题 font-medium + accent 圆点存在', () => {
    const { container } = renderRow(makeItem({ read: false }), false)
    const title = screen.getByText('标题')
    expect(title.className).toContain('font-medium')
    const dot = container.querySelector('span[aria-hidden="true"].rounded-full')
    expect(dot).not.toBeNull()
  })

  it('已读：标题 font-normal + 圆点透明（不只靠颜色：字重差异可见）', () => {
    const { container } = renderRow(makeItem({ read: true }), false)
    expect(screen.getByText('标题').className).toContain('font-normal')
    const dot = container.querySelector('span[aria-hidden="true"].rounded-full') as HTMLElement
    expect(dot.className).toContain('bg-transparent')
  })

  it('已收藏：星形动作按钮 aria-label「取消收藏」（可点击写入，0011 §15）', () => {
    renderRow(makeItem({ starred: true }), false)
    expect(screen.getByRole('button', { name: '取消收藏' })).toBeInTheDocument()
  })

  it('未收藏：星形动作按钮 aria-label「收藏」', () => {
    renderRow(makeItem({ starred: false }), false)
    expect(screen.getByRole('button', { name: '收藏' })).toBeInTheDocument()
  })

  it('稍后读动作按钮存在（Clock 语义，aria-label 加入稍后读）', () => {
    renderRow(makeItem(), false)
    expect(screen.getByRole('button', { name: '加入稍后读' })).toBeInTheDocument()
  })

  it('选中：selected surface（行根 div，非浓色边框/填充）', () => {
    const { container } = renderRow(makeItem(), true)
    const row = container.querySelector('[data-entry-ref]') as HTMLElement
    expect(row.className).toContain('bg-[var(--lumi-surface-selected)]')
    expect(row.className).not.toContain('border-l-2')
  })

  it('未选中：hover surface 而非选中 surface', () => {
    const { container } = renderRow(makeItem(), false)
    expect(container.querySelector('[data-entry-ref]')!.className).toContain(
      'hover:bg-[var(--lumi-surface-hover)]',
    )
  })

  it('作者仅在桌面行内显示（hidden lg:inline）', () => {
    renderRow(makeItem({ author: '作者甲' }), false)
    expect(screen.getByText(/作者甲/).className).toContain('lg:inline')
  })

  it('无硬编码 Tailwind 调色板类（AC3 迁移验证）', () => {
    const { container } = renderRow(makeItem({ read: true, starred: true }), true)
    const all = container.innerHTML
    expect(all).not.toMatch(/(?:bg|text|border)-(?:blue|gray|amber|red)-\d/)
  })
})
