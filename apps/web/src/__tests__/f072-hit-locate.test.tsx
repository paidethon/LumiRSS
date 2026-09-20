/** F072 命中定位 — 偏移定位纯函数（定位正确/词不匹配降级/超范围降级）
 * + chip 组件：命中 N 处、下一处循环、原文已变化降级、无命中不渲染。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  collectHitRanges,
  stashSearchHits,
  takeSearchHits,
} from '../lib/search-hit-locate'
import { SearchHitsChip } from '../components/SearchHitsChip'

describe('F072 collectHitRanges 定位', () => {
  it('F072: offset 正确定位到文本节点并校验词；词不匹配/超范围 → missed', () => {
    const root = document.createElement('div')
    const p1 = document.createElement('p')
    p1.textContent = '前缀文字 alpha 中段'
    const p2 = document.createElement('p')
    p2.textContent = '第二段 alpha 再次命中'
    root.append(p1, p2)

    const text = root.textContent ?? ''
    const offsets = [
      text.indexOf('alpha'),
      text.indexOf('alpha', text.indexOf('alpha') + 1),
    ]
    const hits = [
      { offset: offsets[0], term: 'alpha' },
      { offset: offsets[1], term: 'alpha' },
    ]
    const { ranges, missed } = collectHitRanges(root, hits)
    expect(missed).toBe(0)
    expect(ranges).toHaveLength(2)
    expect(ranges[0].toString()).toBe('alpha')
    expect(ranges[1].toString()).toBe('alpha')

    // 词不匹配（正文已变化）→ 全部 missed
    const changed = collectHitRanges(
      document.createElement('div'), // 空 root
      [{ offset: 0, term: 'alpha' }],
    )
    expect(changed.ranges).toHaveLength(0)
    expect(changed.missed).toBe(1)

    // 超出正文长度（内容被截短）→ missed
    const shortRoot = document.createElement('div')
    shortRoot.textContent = '短'
    const short = collectHitRanges(shortRoot, [{ offset: 50, term: 'alpha' }])
    expect(short.missed).toBe(1)
  })

  it('F072: 暂存/取用（读取即清除）', () => {
    stashSearchHits('e1.a', [{ offset: 3, term: '词' }])
    expect(takeSearchHits('e1.a')).toEqual([{ offset: 3, term: '词' }])
    expect(takeSearchHits('e1.a')).toEqual([]) // 已清除
  })
})

function renderChip(props: {
  entryRef: string | null
  root: Element | null
  detailReady?: boolean
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <SearchHitsChip
        entryRef={props.entryRef}
        getRoot={() => props.root}
        detailReady={props.detailReady ?? true}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  window.getSelection()?.removeAllRanges()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F072 命中定位 chip', () => {
  it('F072: 命中 N 处 chip + 下一处循环跳转（选区移动）', async () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>第一处 alpha 命中</p><p>第二处 alpha 命中</p>'
    document.body.append(root)
    stashSearchHits('e1.a', [
      { offset: 4, term: 'alpha' },
      { offset: root.textContent.indexOf('alpha', 5), term: 'alpha' },
    ])
    renderChip({ entryRef: 'e1.a', root })

    // 定位完成后 chip 渲染
    const chip = await screen.findByText(/命中 2 处/)
    expect(chip).toBeInTheDocument()

    // 下一处 → 选区变化（循环）
    const selection = window.getSelection()
    const firstStart = selection?.rangeCount ? selection.getRangeAt(0).startContainer : null
    fireEvent.click(screen.getByRole('button', { name: '下一处命中' }))
    expect(selection?.rangeCount).toBeGreaterThan(0)
    const secondStart = selection?.rangeCount ? selection.getRangeAt(0).startContainer : null
    expect(firstStart).not.toBe(secondStart)
    root.remove()
  })

  it('F072: 正文已变化 → 降级 chip 且不设置选区；无命中 → 不渲染', async () => {
    const root = document.createElement('div')
    root.textContent = '正文已被编辑，命中的词不存在了'
    document.body.append(root)
    stashSearchHits('e1.b', [{ offset: 0, term: 'alpha' }])
    renderChip({ entryRef: 'e1.b', root })
    expect(await screen.findByText(/原文已变化，无法定位命中位置/)).toBeInTheDocument()
    expect(window.getSelection()?.rangeCount ?? 0).toBe(0)
    root.remove()

    // 无命中（仅标题命中）→ 不渲染定位条
    const root2 = document.createElement('div')
    root2.textContent = '正文'
    renderChip({ entryRef: 'e1.c', root: root2, detailReady: true })
    expect(screen.queryByLabelText('下一处命中')).toBeNull()
  })
})
