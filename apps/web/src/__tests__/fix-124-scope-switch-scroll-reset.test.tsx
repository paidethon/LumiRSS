/** FIX-124 回归 — 来源/分类切换后，旧滚动位置不得带入新列表。
 *
 * 缺陷：列表滚动容器是同一个 DOM 节点；切换 scope/view 后
 * useListScrollAnchor 对「无锚点」的范围直接 return，上一个范围的
 * scrollTop 原样保留——新列表内容就位后被浏览器钳位在旧位置，
 * 用户看到的是新范围的「中间/底部」而不是顶部（旧位置 × 新内容错位）。
 *
 * 修复契约：
 * - 无锚点（该 section|view|scope 本次会话从未滚动过）→ 显式回顶；
 * - 有锚点 → 仍恢复该范围自己的锚点位置（打开文章→返回原位置不受影响）。
 *
 * 数据面说明：entries 查询 key 含 scope（useEntries），切换范围不可能
 * 渲染另一范围的缓存条目（shell.test Test J 已覆盖 feedUrl 请求与内容
 * 分离）；本缺陷只在滚动位置维度。
 */

import { act, render, waitFor } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useListScrollAnchor } from '../components/EntryList'
import { resetListAnchorsForTests, saveListAnchor } from '../lib/list-anchor'

function Harness({ anchorKey }: { anchorKey: string }) {
  const ref = useRef<HTMLDivElement | null>(null)
  useListScrollAnchor(ref, anchorKey, 1)
  return <div ref={ref} data-testid="scroll-container" />
}

/** jsdom 无布局：注入可写的 scrollTop / 固定 scrollHeight。 */
function makeScrollable(el: HTMLElement) {
  Object.defineProperty(el, 'scrollHeight', { value: 2000, configurable: true })
  Object.defineProperty(el, 'scrollTop', { value: 0, writable: true, configurable: true })
}

beforeEach(() => {
  resetListAnchorsForTests()
})

afterEach(() => {
  resetListAnchorsForTests()
})

describe('FIX-124 — 范围切换的滚动位置接管', () => {
  it('切到从未访问的范围（无锚点）→ 旧位置被重置回顶部', async () => {
    const view = render(<Harness anchorKey="home|all|old-scope" />)
    const el = view.getByTestId('scroll-container')
    makeScrollable(el)
    // 模拟上一个范围留下的滚动位置（同一容器节点）。
    act(() => {
      el.scrollTop = 600
    })

    view.rerender(<Harness anchorKey="home|all|new-scope" />)
    await waitFor(() => expect(el.scrollTop).toBe(0))
    view.unmount()
  })

  it('切回有锚点的范围 → 恢复该范围自己的锚点位置（回归保护）', async () => {
    saveListAnchor('home|all|deep-scope', 800)
    const view = render(<Harness anchorKey="home|all|deep-scope" />)
    const el = view.getByTestId('scroll-container')
    makeScrollable(el)
    await waitFor(() => expect(el.scrollTop).toBe(800))
    view.unmount()
  })
})
