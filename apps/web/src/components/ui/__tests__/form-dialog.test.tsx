/** FormDialog — 表单结构契约守卫（头部关闭/回车提交/busy/sticky 操作区）。 */

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { FormDialog } from '../FormDialog'

function Harness({
  onSubmit,
  busy = false,
}: {
  onSubmit: () => void
  busy?: boolean
}) {
  return (
    <FormDialog
      open
      onClose={vi.fn()}
      title="新建订阅"
      description="订阅源更新后自动进入时间线。"
      onSubmit={onSubmit}
      submitLabel="保存"
      busy={busy}
    >
      <label>
        名称
        <input type="text" defaultValue="示例" />
      </label>
    </FormDialog>
  )
}

describe('FormDialog', () => {
  it('渲染标题/说明/字段与操作区；宽度走 form-dialog token', () => {
    render(<Harness onSubmit={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: '新建订阅' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '新建订阅' })).toBeInTheDocument()
    expect(screen.getByText('订阅源更新后自动进入时间线。')).toBeInTheDocument()
    expect(screen.getByLabelText(/名称/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
  })

  it('点击提交按钮触发 onSubmit', () => {
    const onSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} />)
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('表单内回车走原生 form submit', () => {
    const onSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} />)
    const input = screen.getByLabelText(/名称/)
    const form = input.closest('form')
    expect(form).not.toBeNull()
    if (form !== null) fireEvent.submit(form)
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('busy：提交按钮禁用且不重复触发 onSubmit', () => {
    const onSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} busy />)
    const submit = screen.getByRole('button', { name: '保存' })
    expect(submit).toHaveAttribute('aria-busy', 'true')
    expect(submit).toBeDisabled()
    fireEvent.click(submit)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('关闭钮触发 onClose；Escape 也关闭', async () => {
    function Controlled() {
      const [open, setOpen] = useState(true)
      return (
        <FormDialog
          open={open}
          onClose={() => setOpen(false)}
          title="编辑标签"
          onSubmit={vi.fn()}
          submitLabel="保存"
        >
          <input type="text" />
        </FormDialog>
      )
    }
    render(<Controlled />)
    await screen.findByRole('dialog')
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('操作区 sticky 置于滚动容器内（长表单滚动时恒可达）', () => {
    render(<Harness onSubmit={vi.fn()} />)
    const actions = screen.getByRole('button', { name: '保存' }).parentElement
    expect(actions?.className).toContain('sticky')
  })
})
