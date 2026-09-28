/** FIX-117 — Toast 不覆盖关键底栏、可暂停读取、不重复堆积。
 *
 * 1. VersionUpdateToast（含草稿保护确认态）：位置从 bottom-4（与移动
 *    底栏 tab bar 岛重叠）上移到 safe-bottom + 4.5rem（tab bar 顶缘
 *    之上，与 InstallHint 同式）；桌面 ≥1024（底栏隐藏）恢复 bottom-6。
 * 2. UndoSnackbar：悬停/聚焦暂停倒计时（可暂停读取），离开续起剩余
 *    时长；离开后再过原剩余时长才消失。
 * 3. 不堆积：撤销条单槽（新动作覆盖旧动作）、版本 toast 单实例
 *    （App 层单 state）——store 契约断言。
 */

import { act, fireEvent, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import VersionUpdateToast from '../components/VersionUpdateToast'
import UndoSnackbar from '../components/UndoSnackbar'
import { useUndo } from '../store/undo'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  useUndo.getState().clear()
})

describe('FIX-117 VersionUpdateToast 位置', () => {
  it('确认态：位于移动底栏之上（safe-bottom+4.5rem），桌面恢复 bottom-6', () => {
    render(<VersionUpdateToast newVersion="20260928.1" />)
    const toast = screen.getByTestId('version-update-toast')
    expect(toast.className).toContain('bottom-[calc(var(--safe-bottom)+4.5rem)]')
    expect(toast.className).toContain('lg:bottom-6')
    expect(toast.className).not.toContain('bottom-4')
  })

  it('草稿保护确认态同样上移', () => {
    // 草稿分支由 lib/version-check 的 applyUpdate 返回 'confirm-draft' 驱动；
    // 此处直接核验源码契约：两个变体（toast/草稿确认）共用同一 bottom 值。
    const src = readFileSync(join(process.cwd(), 'src/components/VersionUpdateToast.tsx'), 'utf8')
    expect(src.match(/bottom-\[calc\(var\(--safe-bottom\)\+4\.5rem\)\]/g)?.length).toBe(2)
    expect(src).not.toMatch(/className="fixed bottom-4 /)
  })
})

describe('FIX-117 UndoSnackbar 可暂停读取', () => {
  function pushCurrent() {
    act(() => {
      useUndo.getState().push({
        label: '已收藏',
        check: async () => true,
        undo: async () => {},
      })
    })
  }

  it('悬停暂停：9 秒后仍可见；移出后续起剩余时长并过期', () => {
    render(<UndoSnackbar />)
    pushCurrent()
    expect(screen.getByText('已收藏')).toBeInTheDocument()

    // 悬停 → 停表：推过原 8s 窗口 + 余量，条仍在
    const snackbar = document.querySelector('[data-undo-snackbar]')
    expect(snackbar).not.toBeNull()
    fireEvent.mouseEnter(snackbar!)
    act(() => {
      vi.advanceTimersByTime(9000)
    })
    expect(useUndo.getState().current).not.toBeNull()
    expect(screen.getByText('已收藏')).toBeInTheDocument()

    // 移出 → 续起剩余时长（悬停起点时剩余 ≤8s）→ 再推 10s 必过期
    fireEvent.mouseLeave(screen.getByRole('status'))
    act(() => {
      vi.advanceTimersByTime(10000)
    })
    expect(useUndo.getState().current).toBeNull()
  })

  it('聚焦暂停（键盘可达性）：焦点进入停表，失焦续起', () => {
    render(<UndoSnackbar />)
    pushCurrent()
    const status = screen.getByRole('status')
    fireEvent.focus(status)
    act(() => {
      vi.advanceTimersByTime(9000)
    })
    expect(useUndo.getState().current).not.toBeNull()
    fireEvent.blur(status)
    act(() => {
      vi.advanceTimersByTime(10000)
    })
    expect(useUndo.getState().current).toBeNull()
  })

  it('不堆积：撤销条单槽——新动作覆盖旧动作（恒一个 current）', () => {
    render(<UndoSnackbar />)
    act(() => {
      useUndo.getState().push({ label: '第一条', check: async () => true, undo: async () => {} })
    })
    act(() => {
      useUndo.getState().push({ label: '第二条', check: async () => true, undo: async () => {} })
    })
    expect(screen.queryByText('第一条')).toBeNull()
    expect(screen.getByText('第二条')).toBeInTheDocument()
    expect(useUndo.getState().current?.label).toBe('第二条')
  })
})
