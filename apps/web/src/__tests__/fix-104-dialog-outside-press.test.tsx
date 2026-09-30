/** FIX-104 — 弹窗内部控件点击不得误触发「外点关闭」（冒泡路径核查）。
 *
 * 裁决：BASELINE_OK。Base UI Dialog 的外点关闭走 document 级监听 + DOM
 * 包含性判定（popup.contains(event.target)），与 React 合成冒泡无关：
 * 面板内任何控件（内容/底部动作区）的点击都不会被判为外点；只有
 * pointerdown 落在面板之外（遮罩/Viewport 空白/页面其它区域）才关闭。
 * 本组用例即证据：
 *   A. 面板内容区按钮点击 → 弹窗保持打开（无 onClose 调用）；
 *   B. 底部动作区按钮点击 → 仅由按钮自身 onClose 路径关闭（不误关）；
 *   C. Viewport 空白处（面板外）点击 → 外点关闭生效；
 *   D. pointerdown 在面板内、pointerup 在面板外的拖拽序列 → 不误关
 *      （Base UI 以按下起点为准，拖选文本不会把弹窗拖没）。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Dialog } from '../components/ui/Dialog'

function Harness(props: { onClosed?: () => void }) {
  const [open, setOpen] = useState(true)
  const close = () => {
    setOpen(false)
    props.onClosed?.()
  }
  return (
    <>
      <button type="button" data-testid="page-outside">
        页面背景按钮
      </button>
      <Dialog
        open={open}
        onClose={close}
        title="确认操作"
        footer={
          <button type="button" data-testid="footer-apply" onClick={close}>
            应用
          </button>
        }
      >
        <p>说明文字</p>
        <button type="button" data-testid="content-button">
          内容区按钮
        </button>
      </Dialog>
    </>
  )
}

describe('FIX-104: 弹窗内部点击不触发外点关闭', () => {
  it('A. 内容区控件点击后弹窗保持打开', () => {
    render(<Harness />)
    fireEvent.click(screen.getByTestId('content-button'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('B. 底部动作区按钮点击 → 由自身 onClose 关闭，而非误判外点', async () => {
    const onClosed = vi.fn()
    render(<Harness onClosed={onClosed} />)
    fireEvent.click(screen.getByTestId('footer-apply'))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(onClosed).toHaveBeenCalledTimes(1)
  })

  it('C. Viewport 空白处（面板之外）点击 → 外点关闭生效', async () => {
    render(<Harness />)
    const popup = screen.getByRole('dialog')
    // Viewport = Popup 的父层（fixed inset-0 flex 居中容器）；点在容器
    // 自身 = 点在面板之外。
    fireEvent.click(popup.parentElement!)
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('D. pointerdown 在面板内 + pointerup/ click 在面板外 → 不误关（按下起点判定）', async () => {
    render(<Harness />)
    const popup = screen.getByRole('dialog')
    const button = screen.getByTestId('content-button')
    fireEvent.mouseDown(button)
    // 拖出面板后松开（如拖选文本到遮罩上释放）
    fireEvent.mouseUp(popup.parentElement!)
    fireEvent.click(popup.parentElement!)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
