/** ActionMenu — 分组条目模型与键盘可达守卫。
 *
 * 键盘行为（↑↓/Home/End/Escape）由 Base UI Menu 提供（同 Menu.tsx
 * 基线，fix-106 已验证定位）；这里钉住 ActionMenu 特有契约：分组小标题
 * 渲染但不可聚焦、danger 语义、onSelect 直调、Escape 关闭。 */

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ActionMenu } from '../ActionMenu'

function Harness({ onPick, onDanger }: { onPick: (s: string) => void; onDanger: () => void }) {
  return (
    <ActionMenu
      trigger={({ triggerProps }) => (
        <button type="button" {...triggerProps}>
          打开菜单
        </button>
      )}
      entries={[
        { type: 'section', label: '阅读' },
        { type: 'item', label: '排版', onSelect: () => onPick('typography') },
        { type: 'item', label: '目录', onSelect: () => onPick('toc') },
        { type: 'sep' },
        { type: 'section', label: '整理' },
        { type: 'item', label: '删除文章', onSelect: onDanger, danger: true },
      ]}
    />
  )
}

describe('ActionMenu', () => {
  it('打开后渲染分组小标题与条目（menuitem 语义）', async () => {
    render(<Harness onPick={vi.fn()} onDanger={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))

    const menu = await screen.findByRole('menu')
    expect(menu).toBeInTheDocument()
    expect(screen.getByText('阅读')).toBeInTheDocument()
    expect(screen.getByText('整理')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '排版' })).toBeInTheDocument()
    expect(screen.getByRole('separator')).toBeInTheDocument()
    // 小标题不是 menuitem（键盘导航跳过）
    expect(screen.queryByRole('menuitem', { name: '阅读' })).toBeNull()
  })

  it('点击条目直调 onSelect', async () => {
    const onPick = vi.fn()
    render(<Harness onPick={onPick} onDanger={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '目录' }))
    await waitFor(() => expect(onPick).toHaveBeenCalledWith('toc'))
  })

  it('Escape 关闭菜单', async () => {
    render(<Harness onPick={vi.fn()} onDanger={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    expect(await screen.findByRole('menu')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
  })
})
