/** N067 触控操作预览（手势练习区）— 设置入口 + 练习浮层（jsdom）。
 *
 * 覆盖：滑动达阈值在台账记录练习动作（与 card-swipe 同一调度器语义：
 * 80px 阈值 / 纵向让出 / 左缘 24px 让位）；无任何真实 API 调用（fetch
 * 间谍零调用）；台账与浮层退出还原；cardSwipeAction='none' 时滑动不
 * 提交动作（与真实卡片一致）。 */

import { act, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import GesturePracticeSettings, {
  GesturePracticeOverlay,
} from '../components/GesturePracticeSettings'
import { SWIPE_ACTION_LABELS, swipeShouldCommit, swipeStartAllowed } from '../lib/card-swipe'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  // 练习区绝不发起真实请求：fetch 间谍全局在位
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function swipeCard(index: number, startX: number, endX: number, startY = 100, endY = startY): void {
  const card = document.querySelector(`[data-testid="practice-card-${index}"]`) as HTMLElement
  fireEvent.touchStart(card, { touches: [{ clientX: startX, clientY: startY }] })
  fireEvent.touchMove(card, { touches: [{ clientX: endX, clientY: endY }] })
  fireEvent.touchEnd(card, { changedTouches: [{ clientX: endX, clientY: endY }] })
}

describe('N067 手势练习区', () => {
  it('设置入口打开练习区：3 张示例卡片 + 空台账', () => {
    render(withProviders(<GesturePracticeSettings />))
    expect(screen.queryByTestId('practice-ledger')).toBeNull()
    fireEvent.click(screen.getByTestId('open-gesture-practice'))
    expect(screen.getByRole('dialog', { name: '手势练习区' })).toBeInTheDocument()
    expect(document.querySelector('[data-testid="practice-card-1"]')).not.toBeNull()
    expect(document.querySelector('[data-testid="practice-card-2"]')).not.toBeNull()
    expect(document.querySelector('[data-testid="practice-card-3"]')).not.toBeNull()
    expect(screen.getByText('还没有动作。在上方卡片上滑动 / 长按 / 双击试试。')).toBeInTheDocument()
  })

  it('滑动达阈值：台账记录练习动作（同 card-swipe 语义），无真实 API 调用', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    useAppSettings.getState().update({ cardSwipeAction: 'read' })
    render(withProviders(<GesturePracticeOverlay onClose={() => {}} />))

    // 与 EntryCard 相同的调度器契约：80px 提交阈值（导入同一模块校验）
    expect(swipeShouldCommit(80, 0)).toBe(true)
    expect(swipeShouldCommit(79, 0)).toBe(false)

    swipeCard(1, 100, 200) // dx=100 ≥ 80 → 提交
    const logs = document.querySelectorAll('[data-practice-log]')
    expect(logs).toHaveLength(1)
    expect(logs[0]!.getAttribute('data-practice-log')).toBe('触发:标为已读(练习)')
    expect(screen.getByText('触发:标为已读(练习)')).toBeInTheDocument()

    // 未达阈值不记账
    swipeCard(2, 100, 160) // dx=60
    expect(document.querySelectorAll('[data-practice-log]')).toHaveLength(1)
    // 纵向让出不记账（dy > dx，即使 |dx| ≥ 80）
    swipeCard(3, 100, 220, 100, 300)
    expect(document.querySelectorAll('[data-practice-log]')).toHaveLength(1)

    // 练习全程零真实请求
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('同一调度器：左缘 24px 起点不提交（与 EntryCard 相同的让位规则）', () => {
    useAppSettings.getState().update({ cardSwipeAction: 'star' })
    render(withProviders(<GesturePracticeOverlay onClose={() => {}} />))
    // 调度器契约本身（同一导入）
    expect(swipeStartAllowed(24)).toBe(false)
    expect(swipeStartAllowed(25)).toBe(true)
    // 练习卡片遵守：起点 clientX=10 的手势不触发动作
    swipeCard(1, 10, 200)
    expect(document.querySelectorAll('[data-practice-log]')).toHaveLength(0)
    // 正常起点提交收藏动作
    swipeCard(1, 100, 220)
    expect(document.querySelector('[data-practice-log="触发:收藏(练习)"]')).not.toBeNull()
  })

  it('长按与双击练习记账；cardSwipeAction=none 时滑动不提交（无动作语义一致）', () => {
    vi.useFakeTimers()
    try {
      useAppSettings.getState().update({ cardSwipeAction: 'none' })
      const { unmount } = render(withProviders(<GesturePracticeOverlay onClose={() => {}} />))
      // none：滑动不记账（与真实卡片不接手势一致）
      swipeCard(1, 100, 220)
      expect(document.querySelectorAll('[data-practice-log]')).toHaveLength(0)

      // 长按 600ms 记账（长按与动作开关无关）
      const card = document.querySelector('[data-testid="practice-card-2"]') as HTMLElement
      fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
      act(() => {
        vi.advanceTimersByTime(700)
      })
      expect(document.querySelector('[data-practice-log="触发:长按(练习)"]')).not.toBeNull()
      // 长按后本次触摸不再提交滑动
      fireEvent.touchEnd(card, { changedTouches: [{ clientX: 300, clientY: 100 }] })
      expect(document.querySelectorAll('[data-practice-log]')).toHaveLength(1)
      unmount()
    } finally {
      vi.useRealTimers()
    }

    // 双击：300ms 内两次轻点（练习手势独立于动作开关）
    useAppSettings.getState().update({ cardSwipeAction: 'none' })
    render(withProviders(<GesturePracticeOverlay onClose={() => {}} />))
    const card = document.querySelector('[data-testid="practice-card-3"]') as HTMLElement
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 100, clientY: 100 }] })
    expect(document.querySelector('[data-practice-log="触发:双击(练习)"]')).not.toBeNull()
  })

  it('动作标签与设置联动；退出还原（浮层关闭卸载，无残留状态）', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    useAppSettings.getState().update({ cardSwipeAction: 'readLater' })
    expect(SWIPE_ACTION_LABELS.readLater).toBe('加入稍后读')
    render(withProviders(<GesturePracticeSettings />))
    fireEvent.click(screen.getByTestId('open-gesture-practice'))
    swipeCard(1, 100, 200)
    expect(screen.getByText('触发:加入稍后读(练习)')).toBeInTheDocument()

    // 退出：点击「退出练习区」→ 浮层随设置入口状态卸载；台账随之消失；
    // 没有任何持久化（无练习键落 localStorage），零真实请求
    fireEvent.click(screen.getByRole('button', { name: '退出练习区' }))
    expect(document.querySelector('[data-practice-card]')).toBeNull()
    expect(document.querySelector('[data-testid="practice-ledger"]')).toBeNull()
    expect(window.localStorage.getItem('lumirss-practice')).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
