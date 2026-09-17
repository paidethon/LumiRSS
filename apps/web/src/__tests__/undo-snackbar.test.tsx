/** F20 撤销条 — 推送/过期/核对拒绝/撤销执行。 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import UndoSnackbar from '../components/UndoSnackbar'
import { useUndo } from '../store/undo'

function pushCurrent(overrides?: { check?: () => Promise<boolean>; undo?: () => Promise<void> }) {
  act(() => {
    useUndo.getState().push({
      label: '已收藏',
      check: overrides?.check ?? (async () => true),
      undo: overrides?.undo ?? (async () => {}),
    })
  })
}

describe('UndoSnackbar（F20）', () => {
  it('无可撤销动作时零渲染', () => {
    const { container } = render(<UndoSnackbar />)
    expect(container.querySelector('[data-undo-snackbar]')).toBeNull()
  })

  it('推送后可见；撤销执行逆操作并清空', async () => {
    const undo = vi.fn(async () => {})
    let serverState = true
    render(<UndoSnackbar />)
    pushCurrent({
      check: async () => serverState,
      undo,
    })
    expect(screen.getByText('已收藏')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await waitFor(() => expect(undo).toHaveBeenCalledTimes(1))
    expect(useUndo.getState().current).toBeNull()
  })

  it('服务器状态已变化（check=false）→ 拒绝撤销并如实提示', async () => {
    const undo = vi.fn(async () => {})
    render(<UndoSnackbar />)
    pushCurrent({
      check: async () => false, // 另一设备已改动
      undo,
    })
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await screen.findByText('状态已变化，未执行撤销。')
    expect(undo).not.toHaveBeenCalled()
    // 确认后清空
    fireEvent.click(screen.getByRole('button', { name: '知道了' }))
    expect(useUndo.getState().current).toBeNull()
  })
})
