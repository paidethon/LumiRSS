/** Slider primitive 测试 — 0017 Reader Power UX 连续控件。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Slider } from '../components/ui/Slider'

afterEach(() => {
  vi.clearAllMocks()
})

describe('Slider — 连续 range 控件（0017）', () => {
  it('label/output 关联 + 值格式化显示', () => {
    render(
      <Slider
        label="字号"
        value={17}
        min={12}
        max={28}
        step={1}
        onChange={() => {}}
        formatValue={(v) => `${v}px`}
      />,
    )
    const slider = screen.getByRole('slider', { name: '字号' })
    expect(slider).toHaveAttribute('min', '12')
    expect(slider).toHaveAttribute('max', '28')
    expect(slider).toHaveAttribute('step', '1')
    expect(slider).toHaveValue('17')
    // output 显示当前值
    expect(screen.getByText('17px')).toBeInTheDocument()
    expect(slider).toHaveAttribute('aria-valuetext', '17px')
  })

  it('拖动 input → onChange 收到数字（WYSIWYG 逐帧）', () => {
    const onChange = vi.fn()
    render(
      <Slider label="行距" value={1.85} min={1.2} max={2.4} step={0.05} onChange={onChange} />,
    )
    fireEvent.change(screen.getByRole('slider', { name: '行距' }), {
      target: { value: '2.0' },
    })
    expect(onChange).toHaveBeenCalledWith(2.0)
  })

  it('A− / A+ 步进按钮按 step 微调并钳制在 [min,max]', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <Slider
        label="字号"
        value={17}
        min={12}
        max={28}
        step={1}
        onChange={onChange}
        formatValue={(v) => `${v}px`}
        steppers
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '字号增大' }))
    expect(onChange).toHaveBeenLastCalledWith(18)
    fireEvent.click(screen.getByRole('button', { name: '字号减小' }))
    expect(onChange).toHaveBeenLastCalledWith(16)

    // 上限：A+ 禁用
    rerender(
      <Slider
        label="字号"
        value={28}
        min={12}
        max={28}
        step={1}
        onChange={onChange}
        formatValue={(v) => `${v}px`}
        steppers
      />,
    )
    expect(screen.getByRole('button', { name: '字号增大' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '字号减小' })).toBeEnabled()

    // 下限：A− 禁用
    rerender(
      <Slider
        label="字号"
        value={12}
        min={12}
        max={28}
        step={1}
        onChange={onChange}
        formatValue={(v) => `${v}px`}
        steppers
      />,
    )
    expect(screen.getByRole('button', { name: '字号减小' })).toBeDisabled()
  })

  it('无 steppers 时不渲染 A−/A+ 按钮', () => {
    render(
      <Slider label="段距" value={0.85} min={0} max={2.0} step={0.05} onChange={() => {}} />,
    )
    expect(screen.queryByRole('button', { name: '段距增大' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '段距减小' })).not.toBeInTheDocument()
  })
})
