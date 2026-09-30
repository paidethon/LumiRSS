/**
 * FIX-275 — 手势练习/训练台账的 live region 不再整张列表反复朗读。
 *
 * 修复前：练习区（N067）与训练页（NEW-351）的台账是
 * `<ul aria-live="polite">`（容量 20）——每次练习动作都在 live region
 * 顶部插入新 li，整个区域内容变化 → 屏幕阅读器把「整张列表」从头
 * 重新朗读一遍；练习越多次，每次播报越长。
 *
 * 修复后：台账列表退为普通（非 live）可视列表；新增一个常驻的单节点
 * polite live region，textContent 只承载「本次操作结果」（最新一条）。
 * 连续快速动作在同一个节点上合并——播报始终是最新状态，不回放历史。
 */

import { fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import GesturePracticeSettings from '../components/GesturePracticeSettings'
import { ReadingGestureTraining } from '../components/new351/ReadingGestureTraining'
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
  // 练习/训练区绝不发起真实请求
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function swipePracticeCard(index: number, startX: number, endX: number): void {
  const card = document.querySelector(`[data-testid="practice-card-${index}"]`) as HTMLElement
  fireEvent.touchStart(card, { touches: [{ clientX: startX, clientY: 100 }] })
  fireEvent.touchMove(card, { touches: [{ clientX: endX, clientY: 100 }] })
  fireEvent.touchEnd(card, { changedTouches: [{ clientX: endX, clientY: 100 }] })
}

function swipeTrainingCard(endX: number): void {
  // 左缘起点（≤20px）才是返回手势候选（与 edge-swipe 同一判定）
  const startX = 10
  const card = document.querySelector('[data-testid="n351-edge-swipe-practice"]') as HTMLElement
  fireEvent.touchStart(card, { touches: [{ clientX: startX, clientY: 100 }] })
  fireEvent.touchMove(card, { touches: [{ clientX: endX, clientY: 100 }] })
  fireEvent.touchEnd(card, { changedTouches: [{ clientX: endX, clientY: 100 }] })
}

describe('FIX-275: 练习台账 live region 只播报本次操作', () => {
  it('台账 ul 不再是 live region；最新动作由单一 status 节点播报', () => {
    useAppSettings.getState().update({ cardSwipeAction: 'read' })
    render(withProviders(<GesturePracticeSettings />))
    fireEvent.click(document.querySelector('[data-testid="open-gesture-practice"]') as HTMLElement)

    // 第一次动作前，常驻 live 节点已存在（内容为空，不播报历史）
    const status = document.querySelector('[data-practice-latest]') as HTMLElement
    expect(status).not.toBeNull()
    expect(status.getAttribute('aria-live')).toBe('polite')

    swipePracticeCard(1, 100, 200) // → 触发:标为已读(练习)
    // live 节点只承载最新一条
    expect(status.textContent).toBe('触发:标为已读(练习)')
    // 台账本体已不是 live region（屏幕阅读器按需阅读，不再自动回放）
    const ledger = document.querySelector('[data-testid="practice-ledger"] ul') as HTMLUListElement
    expect(ledger).not.toBeNull()
    expect(ledger.getAttribute('aria-live')).toBeNull()

    // 第二次动作：live 节点仍是「只有最新一条」，不叠加历史
    swipePracticeCard(2, 100, 220) // → 触发:标为已读(练习)（同文案）
    swipePracticeCard(3, 100, 200)
    const logs = document.querySelectorAll('[data-practice-log]')
    expect(logs).toHaveLength(3)
    expect(status.textContent).toBe('触发:标为已读(练习)')
    // 播报载荷里没有第二条历史（整列表回放已消除）
    expect((status.textContent ?? '').split('\n')).toHaveLength(1)
  })
})

describe('FIX-275: 训练台账 live region 只播报本次操作', () => {
  it('ul 退出 live region；单节点只播报最新判定', () => {
    render(withProviders(<ReadingGestureTraining />))
    fireEvent.click(document.querySelector('[data-testid="n351-open-training"]') as HTMLElement)

    const status = document.querySelector('[data-n351-training-latest]') as HTMLElement
    expect(status).not.toBeNull()
    expect(status.getAttribute('aria-live')).toBe('polite')
    expect(status.textContent).toBe('')

    swipeTrainingCard(130) // → 触发:左缘侧滑返回(练习)
    expect(status.textContent).toBe('触发:左缘侧滑返回(练习)')

    // 未达提交阈值的第二次滑动 → 台账记预览行，live 节点只更新为该行。
    // fake timers 拉长手势时长，避开速度提交路径（40px/600ms < 0.5px/ms）。
    vi.useFakeTimers()
    try {
      swipeTrainingCard(50)
    } finally {
      vi.useRealTimers()
    }
    const ledger = document.querySelector('[data-testid="n351-training-ledger"] ul') as HTMLUListElement
    expect(ledger).not.toBeNull()
    expect(ledger.getAttribute('aria-live')).toBeNull()
    const logs = document.querySelectorAll('[data-n351-training-log]')
    expect(logs).toHaveLength(2)
    expect(status.textContent).toBe(logs[0]!.textContent)
    expect((status.textContent ?? '').includes('触发:左缘侧滑返回(练习)')).toBe(false)
  })
})
