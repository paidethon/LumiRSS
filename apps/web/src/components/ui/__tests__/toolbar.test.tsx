/** Toolbar — 溢出与分派守卫（R3 契约 §2：窄屏溢出收进「更多」）。
 *
 * jsdom 无 matchMedia → useIsMobile=true（窄屏语义，项目既有约定）；
 * 桌面档用 matchMedia stub 显式模拟。 */

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Toolbar } from '../Toolbar'

function stubDesktop(): void {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: query === '(min-width: 64rem)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function setup(count = 3) {
  const onSelect = vi.fn()
  const actions = Array.from({ length: count }, (_, i) => ({
    id: `a${i}`,
    label: `动作${i}`,
    onSelect: () => onSelect(`a${i}`),
  }))
  return { onSelect, actions }
}

describe('Toolbar（窄屏，jsdom 默认）', () => {
  it('默认只保留 1 个内联动作，其余收进「更多」菜单', async () => {
    const { onSelect, actions } = setup()
    render(<Toolbar aria-label="工具" actions={actions} />)

    expect(screen.getByRole('button', { name: '动作0' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '动作1' })).toBeNull()
    expect(screen.queryByRole('button', { name: '动作2' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /更多/ }))
    const menu = await screen.findByRole('menu')
    expect(menu).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '动作1' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '动作2' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('menuitem', { name: '动作2' }))
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith('a2'))
  })

  it('maxInlineOnNarrow 控制内联数量', () => {
    const { actions } = setup(3)
    render(<Toolbar aria-label="工具" actions={actions} maxInlineOnNarrow={2} />)
    expect(screen.getByRole('button', { name: '动作0' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '动作1' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '动作2' })).toBeNull()
  })

  it('segmented 插槽常驻内联', () => {
    const { actions } = setup(2)
    render(
      <Toolbar
        aria-label="工具"
        segmented={<div data-testid="seg">分段</div>}
        actions={actions}
      />,
    )
    expect(screen.getByTestId('seg')).toBeInTheDocument()
  })
})

describe('Toolbar（桌面档）', () => {
  it('全部动作内联，不渲染「更多」', () => {
    stubDesktop()
    const { actions } = setup(3)
    render(<Toolbar aria-label="工具" actions={actions} />)
    expect(screen.getByRole('button', { name: '动作0' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '动作1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '动作2' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /更多/ })).toBeNull()
  })

  it('点击内联动作触发回调', () => {
    stubDesktop()
    const { onSelect, actions } = setup()
    render(<Toolbar aria-label="工具" actions={actions} />)
    fireEvent.click(screen.getByRole('button', { name: '动作1' }))
    expect(onSelect).toHaveBeenCalledWith('a1')
  })
})
