/** FIX-115 — 按钮 loading 契约：宽度不塌陷、文字不消失、可访问反馈。
 *
 * 缺陷（审计类）：多处 `{pending ? <Spinner/> : '保存'}` 把按钮标签整个
 * 换成 spinner —— 点击瞬间宽度塌陷（布局跳变）、文字消失、且无
 * aria-busy 等可访问忙碌反馈。
 *
 * 契约（ui/Button 的 loading prop）：
 * 1. 标签文字恒在（spinner 内联渲染在标签之前，不替换 children）；
 * 2. loading 时 aria-busy="true"（读屏可感知）+ disabled（防重复提交）；
 * 3. 未 loading 时无 aria-busy、spinner 不渲染（无多余 DOM）；
 * 4. loading 与显式 disabled 独立组合（输入为空禁用 ∨ 加载禁用）。
 *
 * 突变注入验证：把 loading 分支改回「spinner 替换 children」→
 * 标签存在性断言变红；去掉 aria-busy → 可访问反馈断言变红。
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Button } from '../components/ui/Button'

describe('FIX-115 Button loading 契约', () => {
  it('loading：标签保留 + 内联 spinner + aria-busy + disabled', () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        保存
      </Button>,
    )
    const button = screen.getByRole('button', { name: '保存' })
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button).toBeDisabled()
    // spinner 存在且对读屏隐藏
    expect(button.querySelector('[data-loading-spinner]')).not.toBeNull()
    expect(button.querySelector('[data-loading-spinner]')).toHaveAttribute('aria-hidden', 'true')
    // 标签文字未消失（宽度不塌陷的根因修复）
    expect(screen.getByText('保存')).toBeInTheDocument()
  })

  it('非 loading：无 aria-busy、无 spinner、可点击', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>保存</Button>)
    const button = screen.getByRole('button', { name: '保存' })
    expect(button).not.toHaveAttribute('aria-busy')
    expect(button.querySelector('[data-loading-spinner]')).toBeNull()
    expect(button).toBeEnabled()
  })

  it('loading + 显式 disabled 条件独立组合（输入空 ∨ 加载中任一即禁用）', () => {
    const { rerender } = render(<Button loading disabled>试跑</Button>)
    expect(screen.getByRole('button', { name: '试跑' })).toBeDisabled()
    rerender(<Button loading={false} disabled>试跑</Button>)
    expect(screen.getByRole('button', { name: '试跑' })).toBeDisabled()
    rerender(<Button loading={false} disabled={false}>试跑</Button>)
    expect(screen.getByRole('button', { name: '试跑' })).toBeEnabled()
  })
})
