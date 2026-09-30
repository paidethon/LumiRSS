/** NEW-351 阅读手势训练页 — 设置入口 + 合成文章演练 + 启用偏好（jsdom）。
 *
 * 覆盖：合成文章上演练左缘侧滑（与 edge-swipe 同一阈值语义，台账只记
 * 「练习」绝不真实返回）；启用开关写设备本地偏好（lumirss-reading-
 * gesture-prefs）；卡片滑动动作经既有 cardSwipeAction 设置（无第二份
 * 存储）；无任何真实 API 调用（fetch 间谍零调用）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReadingGestureTraining, {
  ReadingGestureTrainingOverlay,
  edgeSwipeTrainingVerdict,
} from '../components/new351/ReadingGestureTraining'
import { READING_GESTURES } from '../lib/reading-gesture-training'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'

function withProviders(ui: ReactNode): ReactNode {
  return ui
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function swipePractice(startX: number, endX: number, startY = 100, endY = startY): void {
  const card = document.querySelector('[data-testid="n351-edge-swipe-practice"]') as HTMLElement
  fireEvent.touchStart(card, { touches: [{ clientX: startX, clientY: startY }] })
  fireEvent.touchMove(card, { touches: [{ clientX: endX, clientY: endY }] })
  fireEvent.touchEnd(card, { changedTouches: [{ clientX: endX, clientY: endY }] })
}

describe('NEW-351 阅读手势训练页', () => {
  it('纯判定：左缘起点 + 横向意图 + 达阈值 → 练习结论文案；非左缘/纵向 → null', () => {
    expect(edgeSwipeTrainingVerdict({ startX: 10, dx: 120, dy: 0, elapsedMs: 500 })).toBe(
      '触发:左缘侧滑返回(练习)',
    )
    // 非左缘起点（>20px）→ 不成手势
    expect(edgeSwipeTrainingVerdict({ startX: 80, dx: 120, dy: 0, elapsedMs: 500 })).toBeNull()
    // 纵向意图（滚动）→ 不成手势
    expect(edgeSwipeTrainingVerdict({ startX: 10, dx: 10, dy: 60, elapsedMs: 500 })).toBeNull()
    // 横向意图成立但位移不足 → 预览文案（不提交）
    const preview = edgeSwipeTrainingVerdict({ startX: 10, dx: 40, dy: 0, elapsedMs: 600 })
    expect(preview).not.toBeNull()
    expect(preview).toContain('预览中')
  })

  it('设置入口打开训练页：合成文章标注 + 空台账 + 手势启用行', () => {
    render(withProviders(<ReadingGestureTraining />))
    expect(screen.queryByTestId('n351-training-ledger')).toBeNull()
    fireEvent.click(screen.getByTestId('n351-open-training'))
    expect(screen.getByRole('dialog', { name: '阅读手势训练' })).toBeInTheDocument()
    expect(screen.getByText('练习用合成文章（非真实内容）')).toBeInTheDocument()
    expect(screen.getByText('还没有动作。在上方合成文章左缘向右滑试试。')).toBeInTheDocument()
    expect(screen.getByText('左缘侧滑返回')).toBeInTheDocument()
  })

  it('合成文章左缘滑动达阈值：台账记录练习动作，不调用 goBack、无 API 调用', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const backSpy = vi.fn()
    window.history.back = backSpy
    render(withProviders(<ReadingGestureTrainingOverlay onClose={() => {}} />))
    swipePractice(8, 140)
    // FIX-275：最新动作同时出现在 sr-only 播报节点与台账行——放宽为至少一份
    expect(screen.getAllByText('触发:左缘侧滑返回(练习)').length).toBeGreaterThanOrEqual(1)
    expect(backSpy).not.toHaveBeenCalled()
    expect(fetchSpy).not.toHaveBeenCalled()
    // 位移不足 → 只记预览（不提交）
    swipePractice(6, 30)
    expect(document.querySelector('[data-n351-training-log="触发:左缘侧滑返回(练习)"]')).not.toBeNull()
    const logs = document.querySelectorAll('[data-n351-training-log]')
    expect(logs.length).toBe(2)
  })

  it('关闭边缘返回开关 → 写既有 swipeBackGesture 设置（单一事实源，无第二份存储）', () => {
    expect(useAppSettings.getState().settings.swipeBackGesture).toBe(true)
    render(withProviders(<ReadingGestureTrainingOverlay onClose={() => {}} />))
    const switches = screen.getAllByRole('switch')
    expect(switches.length).toBe(1)
    fireEvent.click(switches[0])
    expect(switches[0].getAttribute('aria-checked')).toBe('false')
    // 与真实 EdgeSwipeBack 同一设置键（App.tsx 挂载条件）
    expect(useAppSettings.getState().settings.swipeBackGesture).toBe(false)
  })

  it('手势目录与训练页同源（目录键 = 既有设置键）', () => {
    expect(READING_GESTURES.map((g) => g.settingKey)).toEqual([
      'swipeBackGesture',
      'cardSwipeAction',
    ])
  })

  it('卡片滑动动作选择走既有 cardSwipeAction 设置（无第二份存储）', () => {
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, cardSwipeAction: 'none' },
    })
    render(withProviders(<ReadingGestureTrainingOverlay onClose={() => {}} />))
    const select = screen.getByTestId('n351-card-swipe-select') as HTMLSelectElement
    expect(select.value).toBe('none')
    fireEvent.change(select, { target: { value: 'star' } })
    expect(useAppSettings.getState().settings.cardSwipeAction).toBe('star')
    // 提示行出现（动作非「无」时）
    expect(document.querySelector('[data-n351-card-hint]')).not.toBeNull()
  })
})
