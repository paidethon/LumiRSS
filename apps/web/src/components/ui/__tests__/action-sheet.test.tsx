/** ActionSheet — 底部面板结构守卫（标题/关闭/footer/safe-area）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ActionSheet } from '../ActionSheet'

function Harness({
  onClose,
  withFooter = true,
}: {
  onClose: () => void
  withFooter?: boolean
}) {
  return (
    <ActionSheet
      open
      onClose={onClose}
      title="整理文章"
      footer={withFooter ? <button type="button">完成</button> : undefined}
    >
      <button type="button">标记已读</button>
      <p data-testid="sheet-body">面板内容</p>
    </ActionSheet>
  )
}

/** MobileNavigationDrawer 同款：Sheet 模块动态加载（bundle guard），
 * 测试里先等 dialog 出现再断言。 */
async function renderAndAwait(ui: React.ReactElement) {
  const view = render(ui)
  await screen.findByRole('dialog')
  return view
}

describe('ActionSheet', () => {
  it('渲染可见标题、正文与 footer；标题同时是 accessible name', async () => {
    await renderAndAwait(<Harness onClose={vi.fn()} />)
    const dialog = screen.getByRole('dialog', { name: '整理文章' })
    expect(dialog).toBeInTheDocument()
    expect(screen.getByTestId('sheet-body')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '完成' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '标记已读' })).toBeInTheDocument()
  })

  it('关闭按钮触发 onClose', async () => {
    const onClose = vi.fn()
    await renderAndAwait(<Harness onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('Escape 关闭（Base UI Drawer 语义）', async () => {
    const onClose = vi.fn()
    await renderAndAwait(<Harness onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
  })

  it('无 footer 时正文区自带底部安全区 padding（safe-area-inset-bottom）', async () => {
    await renderAndAwait(<Harness onClose={vi.fn()} withFooter={false} />)
    const body = screen.getByTestId('sheet-body').parentElement
    expect(body?.style.paddingBottom).toBe('max(0.75rem, var(--safe-bottom))')
  })

  it('受控关闭：onClose 翻转 open 后面板卸载', async () => {
    function Controlled() {
      const [open, setOpen] = useState(true)
      return (
        <ActionSheet open={open} onClose={() => setOpen(false)} title="受控">
          <p>内容</p>
        </ActionSheet>
      )
    }
    render(<Controlled />)
    await screen.findByRole('dialog')
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
