/** DetailDrawer — 双形态分派守卫。
 *
 * jsdom 无 matchMedia → useIsMobile=true（移动形态，项目既有约定）；
 * 桌面形态用 matchMedia stub 显式模拟（use-viewport-tier 的
 * '(min-width: 64rem)' 查询）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DetailDrawer } from '../DetailDrawer'

function stubViewport(tier: 'mobile' | 'desktop'): void {
  const desktop = tier === 'desktop'
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: desktop
        ? query === '(min-width: 64rem)'
        : query === '(max-width: 47.99rem)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function Harness({ onClose }: { onClose: () => void }) {
  return (
    <DetailDrawer
      open
      onClose={onClose}
      title="文章详情"
      footer={<button type="button">存档</button>}
    >
      <p data-testid="drawer-body">详情内容</p>
    </DetailDrawer>
  )
}

describe('DetailDrawer（移动 <1024）', () => {
  it('渲染为全宽底部面板（ActionSheet 形态）：标题/正文/footer 齐备', async () => {
    stubViewport('mobile')
    render(<Harness onClose={vi.fn()} />)
    const dialog = await screen.findByRole('dialog', { name: '文章详情' })
    expect(dialog).toBeInTheDocument()
    expect(screen.getByTestId('drawer-body')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '存档' })).toBeInTheDocument()
    // 底部面板形态标记（Sheet side=bottom 的玻璃面板类）
    expect(dialog.className).toContain('lumi-glass')
  })

  it('Escape 关闭', async () => {
    const onClose = vi.fn()
    stubViewport('mobile')
    render(<Harness onClose={onClose} />)
    await screen.findByRole('dialog')
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })
})

describe('DetailDrawer（桌面 ≥1024）', () => {
  it('渲染为右侧抽屉：token 宽度覆盖 Sheet 默认 max-w-md', async () => {
    stubViewport('desktop')
    render(<Harness onClose={vi.fn()} />)
    const dialog = await screen.findByRole('dialog', { name: '文章详情' })
    expect(dialog).toBeInTheDocument()
    // 右抽屉形态标记 + token 宽度（26rem，400–440px 契约区间）
    expect(dialog.className).toContain('border-l')
    expect(dialog.className).toContain('max-w-[var(--lumi-width-detail-drawer)]!')
    expect(screen.getByTestId('drawer-body')).toBeInTheDocument()
  })

  it('Escape 与关闭钮都触发 onClose', async () => {
    const onClose = vi.fn()
    stubViewport('desktop')
    render(<Harness onClose={onClose} />)
    await screen.findByRole('dialog')
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))

    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(2))
  })
})
