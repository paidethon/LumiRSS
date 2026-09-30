/**
 * FIX-271 / FIX-272 — 三栏分隔条拖拽释放与选区抑制（运行时验证）。
 *
 * FIX-271：拖拽释放不只靠 pointerup——pointercancel（来电/系统手势/
 * 触摸重置）同样必须移除 window pointermove 监听并复位 dragging。
 * 修复前：取消后 dragging 恒为 true、监听器泄漏，分隔条在无按键的
 * 后续 pointermove 里继续改宽（界面锁进拖拽态）。
 * FIX-272：拖拽期间根元素挂 lumi-pane-dragging（user-select:none，
 * index.css 提供），跨过正文拖动不产生选区；pointerup/pointercancel
 * 后摘除，恢复正常复制。
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PaneSeparator } from '../components/ui/PaneSeparator'

function setup() {
  const onChange = vi.fn()
  const onReset = vi.fn()
  render(
    <PaneSeparator
      value={400}
      min={360}
      max={460}
      onChange={onChange}
      onReset={onReset}
      label="文章列表宽度"
    />,
  )
  const separator = screen.getByRole('separator', { name: '文章列表宽度' })
  return { onChange, onReset, separator }
}

const draggingClass = () => document.documentElement.classList.contains('lumi-pane-dragging')

afterEach(() => {
  // 兜底：任何用例遗留的抑制类/监听不跨用例污染。
  document.documentElement.classList.remove('lumi-pane-dragging')
})

describe('FIX-271: pointercancel 后释放拖拽锁', () => {
  it('pointerup 正常结束：宽度更新生效，结束后 pointermove 不再改宽', () => {
    const { onChange, separator } = setup()
    fireEvent.pointerDown(separator, { clientX: 100 })
    fireEvent.pointerMove(window, { clientX: 130 })
    expect(onChange).toHaveBeenLastCalledWith(430)
    onChange.mockClear()
    fireEvent.pointerUp(window)
    fireEvent.pointerMove(window, { clientX: 180 })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('pointercancel（来电/系统手势）：立即解锁，后续 pointermove 不再改宽', () => {
    const { onChange, separator } = setup()
    fireEvent.pointerDown(separator, { clientX: 100 })
    fireEvent.pointerMove(window, { clientX: 120 })
    expect(onChange).toHaveBeenCalled()
    onChange.mockClear()
    fireEvent.pointerCancel(window)
    // 取消后无按键的鼠标移动不得继续拖拽（修复前：继续改宽 + 永久泄漏）。
    fireEvent.pointerMove(window, { clientX: 200 })
    fireEvent.pointerMove(window, { clientX: 260 })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('pointercancel 复位后可以开始新拖拽（不会因旧状态拒真）', () => {
    const { onChange, separator } = setup()
    fireEvent.pointerDown(separator, { clientX: 100 })
    fireEvent.pointerCancel(window)
    fireEvent.pointerDown(separator, { clientX: 100 })
    fireEvent.pointerMove(window, { clientX: 140 })
    expect(onChange).toHaveBeenLastCalledWith(440)
  })
})

describe('FIX-272: 拖拽期间抑制选区', () => {
  it('pointerdown 挂 lumi-pane-dragging；pointerup / pointercancel 摘除', () => {
    const { separator } = setup()
    expect(draggingClass()).toBe(false)
    fireEvent.pointerDown(separator, { clientX: 100 })
    expect(draggingClass()).toBe(true)
    fireEvent.pointerUp(window)
    expect(draggingClass()).toBe(false)

    fireEvent.pointerDown(separator, { clientX: 100 })
    expect(draggingClass()).toBe(true)
    fireEvent.pointerCancel(window)
    expect(draggingClass()).toBe(false)
  })

  it('拖拽中途组件卸载：监听与抑制类一并释放（无全局残留）', () => {
    const onChange = vi.fn()
    const view = render(
      <PaneSeparator
        value={400}
        min={360}
        max={460}
        onChange={onChange}
        onReset={vi.fn()}
        label="侧栏宽度"
      />,
    )
    const separator = screen.getByRole('separator', { name: '侧栏宽度' })
    fireEvent.pointerDown(separator, { clientX: 100 })
    expect(draggingClass()).toBe(true)
    view.unmount()
    expect(draggingClass()).toBe(false)
    // 卸载后残留监听已摘：window pointermove 不再触达 onChange。
    fireEvent.pointerMove(window, { clientX: 180 })
    expect(onChange).not.toHaveBeenCalled()
  })
})
