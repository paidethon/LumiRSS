/**
 * FIX-280 — 多触点（捏合缩放/图片双指）不被侧滑返回误判。
 *
 * 修复前：EdgeSwipeBack 只在 touchstart 检查单指——手势进行中第二指
 * 落下时，onMove 仍按 touches[0] 与起点的位移继续推进预览甚至提交
 * 返回，双指缩放被误判为导航。
 * 修复后：onMove 一旦发现 touches.length !== 1 立即放弃本次手势并
 * 回弹预览；touchend 不再提交。
 */

import { render, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { canGoBack, initNavHistory, pushNavHistory } from '../lib/nav-history'
import { useReaderUi } from '../store/reader-ui'
import { EdgeSwipeBack } from '../lib/edge-swipe'

function touchEvent(type: string, touches: Array<{ clientX: number; clientY: number }>) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.assign(event, { touches })
  return event
}

beforeEach(() => {
  window.localStorage.clear()
  useReaderUi.setState({ selectedEntryRef: null })
  document.body.innerHTML = ''
  const main = document.createElement('main')
  main.textContent = '内容'
  document.body.appendChild(main)
})

afterEach(() => {
  const cleanup = initNavHistory()
  cleanup()
  vi.restoreAllMocks()
})

describe('FIX-280: 手势进行中第二指落下 → 放弃返回', () => {
  it('单指预览中第二指落下：预览回弹、touchend 不提交返回', () => {
    const cleanup = initNavHistory()
    // 建立一条可返回历史（depth=1）
    useReaderUi.setState({ section: 'search' })
    pushNavHistory()
    expect(canGoBack()).toBe(true)

    const historyBack = vi.spyOn(window.history, 'back')
    const view = render(<EdgeSwipeBack />)

    // 单指从左缘进入并建立预览
    fireEvent(document, touchEvent('touchstart', [{ clientX: 10, clientY: 80 }]))
    fireEvent(document, touchEvent('touchmove', [{ clientX: 80, clientY: 84 }]))
    const main = document.querySelector('main') as HTMLElement
    expect(main.dataset.swiping).toBe('1')

    // 第二指落下（捏合缩放开始）
    fireEvent(
      document,
      touchEvent('touchmove', [
        { clientX: 90, clientY: 90 },
        { clientX: 200, clientY: 160 },
      ]),
    )
    // 预览立即回弹、swiping 标记清除
    expect(main.dataset.swiping).toBeUndefined()
    expect(main.style.transform).toBe('')

    // 抬手位移已过提交阈值——但手势已放弃，不得返回
    fireEvent(document, touchEvent('touchend', []))
    expect(historyBack).not.toHaveBeenCalled()

    view.unmount()
    cleanup()
  })

  it('双指同时起手（捏合直起）：从不进入候选，不拦截缩放', () => {
    const cleanup = initNavHistory()
    useReaderUi.setState({ section: 'search' })
    pushNavHistory()
    const historyBack = vi.spyOn(window.history, 'back')
    const view = render(<EdgeSwipeBack />)

    const main = document.querySelector('main') as HTMLElement
    fireEvent(
      document,
      touchEvent('touchstart', [
        { clientX: 8, clientY: 100 },
        { clientX: 60, clientY: 180 },
      ]),
    )
    fireEvent(
      document,
      touchEvent('touchmove', [
        { clientX: 60, clientY: 100 },
        { clientX: 20, clientY: 180 },
      ]),
    )
    expect(main.dataset.swiping).toBeUndefined()
    fireEvent(document, touchEvent('touchend', []))
    expect(historyBack).not.toHaveBeenCalled()

    view.unmount()
    cleanup()
  })
})
