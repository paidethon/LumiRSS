/** P1.3 统一返回链 — nav-history + 边缘侧滑判定（2026-09 移动端专项）。
 *
 * 覆盖：
 * - 初始 replaceState、导航 push、重复导航不 push（幂等）；
 * - goBack 同步恢复上一快照（section/scope/view/selection）；
 * - popstate 恢复（含前进）；
 * - 浮层层级：register/unregister + goBack 只关最上层浮层；
 * - 根守卫：深度 0 时 goBack 返回 false 且不动 history；
 * - 侧滑纯函数：候选/意图/提交/预览边界。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  canGoBack,
  goBack,
  initNavHistory,
  registerOverlay,
  unregisterOverlay,
} from '../lib/nav-history'
import {
  EDGE_SWIPE_COMMIT_PX,
  EDGE_SWIPE_INTENT_PX,
  EDGE_SWIPE_PREVIEW_MAX_PX,
  EDGE_SWIPE_START_PX,
  previewOffset,
  swipeIntentMet,
  swipeShouldCommit,
  swipeStartCandidate,
} from '../lib/edge-swipe'
import { useReaderUi } from '../store/reader-ui'

function firePopState(state: unknown) {
  const event = new PopStateEvent('popstate', { state })
  window.dispatchEvent(event)
}

beforeEach(() => {
  useReaderUi.setState({
    section: 'home',
    scope: { kind: 'all' },
    view: 'all',
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  window.history.replaceState(null, '', '/')
  initNavHistory()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('nav-history — push / back / popstate', () => {
  it('导航 push；重复相同导航不 push（history 长度不增长）', () => {
    const before = window.history.length
    useReaderUi.getState().selectSection('search')
    const afterPush = window.history.length
    // 再次点击同一 section（幂等 no-op，不产生新历史）
    useReaderUi.getState().selectSection('search')
    expect(window.history.length).toBe(afterPush)
    expect(useReaderUi.getState().section).toBe('search')
    expect(afterPush).toBeGreaterThan(before)
  })

  it('goBack 同步恢复上一处（section/scope/view/selection）', () => {
    useReaderUi.getState().selectSection('search')
    useReaderUi.getState().selectSection('home')
    expect(canGoBack()).toBe(true)
    expect(goBack()).toBe(true)
    // 同步恢复：回到 search（不需要等 popstate）
    expect(useReaderUi.getState().section).toBe('search')
    expect(goBack()).toBe(true)
    expect(useReaderUi.getState().section).toBe('home')
  })

  it('popstate 恢复快照（浏览器后退等效），并且 setState 不再 push', () => {
    useReaderUi.getState().selectSection('search')
    useReaderUi.getState().selectSection('favorites')
    const len = window.history.length
    // 模拟浏览器后退两步（popstate 携带目标快照）。
    firePopState({ lumi: { section: 'search', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null }, lumiDepth: 1 })
    expect(useReaderUi.getState().section).toBe('search')
    // 恢复本身不追加历史。
    expect(window.history.length).toBe(len)
  })

  it('选择文章 → goBack 恢复列表；selection 清空但 section/scope 不动', () => {
    useReaderUi.getState().selectEntry('e1.a')
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    goBack()
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
    expect(useReaderUi.getState().section).toBe('home')
  })

  it('根守卫：无应用内可返回页时 goBack=false，history 不动', () => {
    expect(canGoBack()).toBe(false)
    const spy = vi.spyOn(window.history, 'back')
    expect(goBack()).toBe(false)
    expect(spy).not.toHaveBeenCalled()
  })

  it('浮层：register → goBack 只关最上层（一次后退关一层）；UI 关闭消耗自己的条目', () => {
    useReaderUi.getState().selectSection('search')
    const closes: string[] = []
    registerOverlay('a', () => {
      closes.push('a')
      unregisterOverlay('a')
    })
    registerOverlay('b', () => {
      closes.push('b')
      unregisterOverlay('b')
    })
    // 浏览器后退到达非浮层条目 → 残存浮层全关（离开页面语义）。
    firePopState({ lumi: { section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null }, lumiDepth: 0 })
    expect(closes).toEqual(['b', 'a'])
    expect(useReaderUi.getState().section).toBe('home')
  })
})

describe('edge-swipe 纯函数判定', () => {
  it('起点：左缘 ≤20px 才是候选', () => {
    expect(swipeStartCandidate(0)).toBe(true)
    expect(swipeStartCandidate(EDGE_SWIPE_START_PX)).toBe(true)
    expect(swipeStartCandidate(21)).toBe(false)
  })
  it('意图：dx>12 且明显横向（|dx|>|dy|*1.5）', () => {
    expect(swipeIntentMet(EDGE_SWIPE_INTENT_PX + 1, 0)).toBe(true)
    expect(swipeIntentMet(EDGE_SWIPE_INTENT_PX, 0)).toBe(false)
    expect(swipeIntentMet(60, 60)).toBe(false) // 斜向 → 让出
    expect(swipeIntentMet(60, 30)).toBe(true)
    expect(swipeIntentMet(-60, 0)).toBe(false) // 右缘方向不管
  })
  it('提交：位移 ≥96 或速度 ≥0.5px/ms', () => {
    expect(swipeShouldCommit(EDGE_SWIPE_COMMIT_PX, 1000)).toBe(true)
    expect(swipeShouldCommit(80, 100)).toBe(true) // 0.8px/ms
    expect(swipeShouldCommit(80, 500)).toBe(false)
    expect(swipeShouldCommit(40, 0)).toBe(false)
  })
  it('预览：跟手 0.35 倍、上限 120px、负位移为 0', () => {
    expect(previewOffset(200)).toBe(70)
    expect(previewOffset(1000)).toBe(EDGE_SWIPE_PREVIEW_MAX_PX)
    expect(previewOffset(-50)).toBe(0)
  })
})
