/** NEW-354 移动批量整理模式 — 纯逻辑 + 范围条（jsdom）。
 *
 * 覆盖：范围/计数行文案（视图标签、超限诚实标注）；进入条件（仅 home
 * 且已加载 >0）；范围条组件（展示 + 退出回调；退出即全清由 EntryList
 * 的 exitSelectMode 承担——本测试用 spy 断言调用）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import MobileOrganizeBar from '../components/new351/MobileOrganizeBar'
import {
  ORGANIZE_EXIT_CLEARS,
  ORGANIZE_VIEW_LABELS,
  canEnterOrganizeMode,
  organizeCountLine,
  organizeScopeLine,
} from '../lib/list-organize'

describe('NEW-354 整理模式纯逻辑', () => {
  it('视图标签全集（与 UiView 一一对应）', () => {
    expect(Object.keys(ORGANIZE_VIEW_LABELS).sort()).toEqual(
      ['all', 'read-later', 'starred', 'unread'].sort(),
    )
    expect(ORGANIZE_VIEW_LABELS.unread).toBe('未读')
    expect(ORGANIZE_VIEW_LABELS['read-later']).toBe('稍后读')
  })

  it('范围行 / 计数行文案', () => {
    expect(
      organizeScopeLine({ view: 'unread', scopeLabel: '全部信息源', loadedCount: 40, selectedCount: 3 }),
    ).toBe('视图：未读 · 范围：全部信息源')
    expect(
      organizeCountLine({ view: 'unread', scopeLabel: '全部信息源', loadedCount: 40, selectedCount: 3 }, 100),
    ).toBe('本页已加载 40 篇 · 已选 3 条')
    expect(
      organizeCountLine({ view: 'all', scopeLabel: '某订阅源', loadedCount: 120, selectedCount: 101 }, 100),
    ).toContain('超过一次可处理上限 100')
  })

  it('进入条件：仅列表页且已加载 >0', () => {
    expect(canEnterOrganizeMode('home', 10)).toBe(true)
    expect(canEnterOrganizeMode('home', 0)).toBe(false)
    expect(canEnterOrganizeMode('favorites', 10)).toBe(false)
  })

  it('退出清理口径：选择 / 批量失败清单 / 运行标志全部在内', () => {
    expect(ORGANIZE_EXIT_CLEARS).toEqual(['selection', 'batch-failures', 'running-flag'])
  })
})

describe('NEW-354 整理范围条', () => {
  it('展示整理模式 / 范围 / 计数；退出按钮触发回调', () => {
    const onExit = vi.fn()
    render(
      <MobileOrganizeBar
        scope={{ view: 'unread', scopeLabel: '全部信息源', loadedCount: 40, selectedCount: 5 }}
        batchLimit={100}
        onExit={onExit}
      />,
    )
    expect(screen.getByText(/整理模式/)).toBeTruthy()
    expect(screen.getByText(/视图：未读 · 范围：全部信息源/)).toBeTruthy()
    expect(screen.getByText(/本页已加载 40 篇 · 已选 5 条/)).toBeTruthy()
    fireEvent.click(screen.getByTestId('n354-exit-organize'))
    expect(onExit).toHaveBeenCalledTimes(1)
  })
})
