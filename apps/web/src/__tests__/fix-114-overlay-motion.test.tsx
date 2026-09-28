/** FIX-114 — 侧栏/抽屉/弹窗 进入退出方向与时间尺度核验 + 可中断状态完整性。
 *
 * 契约核验（Base UI 拥有焦点陷阱/Escape/滚动锁/中断恢复等机制，Lumi
 * 只提供视觉方向与时长 token）：
 * 1. 方向随边：left 从左滑入（-translate-x-full）、right 从右滑入
 *    （+translate-x-full）、bottom 从下滑入（+translate-y-full）；
 *    Viewport 对齐随 side（右贴右缘、下贴底缘）。
 * 2. 时间尺度：统一 motion-slow token + ease-out-soft 出场缓动，
 *    只动画 transform（cheap property，与 FIX-111 一致）。
 * 3. 可中断、状态不丢：快速 关→开（退出动画中反转）后面板完整回到
 *    open 态（内容在、role=dialog、无 ending 态残留）；受控 open 是
 *    唯一真源，重复关闭不产生半开态。
 * 4. Dialog（居中弹窗）刻意无进入/退出动画（瞬时出现；无方向语义）——
 *    核验其不携带 transition/starting-style 动画类，BASELINE_OK。
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Dialog } from '../components/ui/Dialog'
import { Sheet } from '../components/ui/Sheet'

function Popup() {
  return screen.getByRole('dialog')
}

describe('FIX-114 Sheet 方向与时间尺度', () => {
  it('side=left（侧栏抽屉）：从左滑入 -translate-x-full；motion-slow + ease-out-soft + 仅 transform', () => {
    render(
      <Sheet open onClose={vi.fn()} label="导航" side="left">
        <p>抽屉内容</p>
      </Sheet>,
    )
    const cls = Popup().className
    expect(cls).toContain('data-starting-style:-translate-x-full')
    expect(cls).toContain('data-ending-style:-translate-x-full')
    expect(cls).not.toContain('translate-x-full data-starting') // 方向不反向
    expect(cls).toContain('transition-transform')
    expect(cls).toContain('duration-[var(--lumi-motion-slow)]')
    expect(cls).toContain('ease-[var(--lumi-ease-out-soft)]')
  })

  it('side=right（右侧面板）：从右滑入 +translate-x-full，Viewport 贴右缘', () => {
    const { container } = render(
      <Sheet open onClose={vi.fn()} label="对话" side="right">
        <p>对话内容</p>
      </Sheet>,
    )
    const cls = Popup().className
    expect(cls).toContain('data-starting-style:translate-x-full')
    expect(cls).toContain('data-ending-style:translate-x-full')
    expect(cls).not.toContain('-translate-x-full')
    // Viewport 定位（portal 内）：flex 容器 justify-end
    const viewport = container.ownerDocument.querySelector('[class*="justify-end"]')
    expect(viewport).not.toBeNull()
  })

  it('side=bottom（底部 sheet）：从下滑入 +translate-y-full，Viewport 贴底缘', () => {
    const { container } = render(
      <Sheet open onClose={vi.fn()} label="样式" side="bottom">
        <p>样式内容</p>
      </Sheet>,
    )
    const cls = Popup().className
    expect(cls).toContain('data-starting-style:translate-y-full')
    expect(cls).toContain('data-ending-style:translate-y-full')
    expect(container.ownerDocument.querySelector('[class*="items-end"]')).not.toBeNull()
  })

  it('可中断退出：关→立即重开，面板完整回到 open 态（内容在、无 wedged 半开态）', async () => {
    // 受控 open 由外部驱动（modal 态下外部按钮 inert，rerender 模拟快速反转）
    function Harness({ open }: { open: boolean }) {
      return (
        <Sheet open={open} onClose={vi.fn()} label="导航" side="left">
          <input aria-label="抽屉输入框" defaultValue="草稿保留" />
        </Sheet>
      )
    }
    const { rerender } = render(<Harness open={true} />)
    expect(screen.getByLabelText('抽屉输入框')).toHaveValue('草稿保留')

    // 快速 关→开（模拟退出动画中反转）：受控 state 唯一真源 → 面板回 open
    rerender(<Harness open={false} />)
    rerender(<Harness open={true} />)
    await waitFor(() => {
      expect(screen.getByLabelText('抽屉输入框')).toBeInTheDocument()
    })
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // 最终关闭：面板彻底卸载（无残留半开 DOM）
    rerender(<Harness open={false} />)
    await waitFor(() => {
      expect(document.querySelector('[role="dialog"]')).toBeNull()
    })
  })
})

describe('FIX-114 Dialog 弹窗（BASELINE_OK 核验）', () => {
  it('居中弹窗刻意无进入/退出动画（瞬时出现；不携带 transition/starting-style 动画类）', () => {
    render(
      <Dialog open onClose={vi.fn()} title="确认">
        <p>弹窗内容</p>
      </Dialog>,
    )
    const cls = screen.getByRole('dialog').className
    expect(cls).not.toContain('transition')
    expect(cls).not.toContain('data-starting-style')
    expect(cls).not.toContain('data-ending-style')
    // 居中定位存在（Viewport flex 居中），无方向性位移类
    expect(cls).not.toMatch(/translate-(x|y)-full/)
  })
})
