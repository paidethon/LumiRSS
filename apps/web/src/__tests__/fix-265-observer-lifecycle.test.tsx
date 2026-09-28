/** FIX-265 — 懒加载观察器生命周期（阅读区无泄漏验证）。
 *
 * 现状核实（诚实基线）：
 * - 正文图片的「懒加载/省流」是【属性摘除】机制（lib/article-images
 *   deferImages / lib/media-policy deferMedia / lib/remote-images
 *   blockRemoteImages），渲染前后都不使用 IntersectionObserver——
 *   不存在会跨文章泄漏的图片观察器；
 * - 阅读区唯一的 IntersectionObserver 是 finish-read 的文末哨兵：
 *   attachObserver 重挂前先 disconnect，卸载 effect 也 disconnect。
 *
 * 本文件把两条事实钉进回归：
 * 1. 切换多篇图片文章 → IntersectionObserver 构造次数为 0，省流状态
 *    按文章重置（新文章重新摘 src，旧文章 DOM 不残留）；
 * 2. 切文章 / 卸载 → 旧哨兵 observer 必然 disconnect（不观察已移除
 *    节点）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { useFinishRead, type FinishReadController } from '../lib/finish-read'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

function imageDetail(entryRef: string, marker: string): EntryDetail {
  return {
    entryRef,
    title: `图文章 ${marker}`,
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: `<p>${marker}</p><img src="https://img.example.com/${marker}.png" alt="${marker}">`,
    contentText: marker,
  } as unknown as EntryDetail
}

describe('FIX-265：图片文章切换不构造任何 IntersectionObserver，省流状态按文章重置', () => {
  let constructed = 0
  class CountingIO {
    constructor() {
      constructed += 1
    }
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }

  beforeEach(() => {
    constructed = 0
    vi.stubGlobal('IntersectionObserver', CountingIO as unknown as typeof IntersectionObserver)
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, readerImageMode: 'hidden' },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('A → B → A 来回切换：零 observer 构造；B 的图片重新 defer、A 的 DOM 不残留', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const view = render(
      <QueryClientProvider client={qc}>
        <ArticleContent detail={imageDetail('e1.a', 'A')} />
      </QueryClientProvider>,
    )
    // 首帧同步路径（sanitize + memo defer）即已摘除 src。
    expect(view.container.querySelector('img[data-lumi-src="https://img.example.com/A.png"]')).not.toBeNull()

    // 管线是异步的：切换后等 B 的内容进入 DOM。
    view.rerender(
      <QueryClientProvider client={qc}>
        <ArticleContent detail={imageDetail('e2.b', 'B')} />
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(view.container.querySelector('img[data-lumi-src="https://img.example.com/B.png"]')).not.toBeNull(),
    )
    expect(view.container.querySelector('img[data-lumi-src*="A.png"]')).toBeNull()

    view.rerender(
      <QueryClientProvider client={qc}>
        <ArticleContent detail={imageDetail('e1.a', 'A')} />
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(view.container.querySelector('img[data-lumi-src="https://img.example.com/A.png"]')).not.toBeNull(),
    )
    expect(view.container.querySelector('img[data-lumi-src*="B.png"]')).toBeNull()

    // 全程没有任何 IntersectionObserver 被构造——不存在可泄漏的图片观察器。
    expect(constructed).toBe(0)
    // 覆盖状态随 entryRef 重置（切走再切回，「加载本文图片」不残留）。
    expect(view.container.querySelector('img[src]')).toBeNull()
  })
})

// ---- finish-read 哨兵 observer：切文章 / 卸载必然 disconnect ----

class MockIO {
  static instances: MockIO[] = []
  disconnectCount = 0
  targets = new Set<Element>()
  cb: IntersectionObserverCallback
  opts?: IntersectionObserverInit
  constructor(cb: IntersectionObserverCallback, opts?: IntersectionObserverInit) {
    this.cb = cb
    this.opts = opts
    MockIO.instances.push(this)
  }
  observe(el: Element): void {
    this.targets.add(el)
  }
  unobserve(el: Element): void {
    this.targets.delete(el)
  }
  disconnect(): void {
    this.disconnectCount += 1
    this.targets.clear()
  }
}

function Harness(props: { entryRef: string; sentinelKey?: string }) {
  const c: FinishReadController = useFinishRead({
    enabled: true,
    entryRef: props.entryRef,
    read: false,
    markRead: () => Promise.resolve(),
  })
  return (
    <div ref={c.setContainer} data-testid="reader-container">
      <p>正文占位</p>
      {/* 正文换血 = 哨兵节点重建（真实应用里 Reader 按 entryRef 重挂载）。
          key 变化让 ref 回调以新节点再触发，attachObserver 必须先断开旧
          observer——否则旧 observer 一直观察已移除的节点。 */}
      <div key={props.sentinelKey ?? 's1'} ref={c.sentinelRef} data-testid="finish-sentinel" />
    </div>
  )
}

describe('FIX-265：finish-read 哨兵 observer 不跨文章泄漏', () => {
  let container: HTMLDivElement

  function setupLayout(view: ReturnType<typeof render>): void {
    container = view.getByTestId('reader-container') as HTMLDivElement
    Object.defineProperty(container, 'scrollHeight', { value: 2000, configurable: true })
    Object.defineProperty(container, 'clientHeight', { value: 600, configurable: true })
    Object.defineProperty(container, 'scrollTop', { value: 0, writable: true, configurable: true })
  }

  beforeEach(() => {
    MockIO.instances = []
    vi.stubGlobal('IntersectionObserver', MockIO as unknown as typeof IntersectionObserver)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('哨兵节点随文章重建：旧 observer disconnect 且不再观察已移除节点', () => {
    const view = render(<Harness entryRef="e1" sentinelKey="s1" />)
    setupLayout(view)
    expect(MockIO.instances.length).toBe(1)
    const oldObserver = MockIO.instances[0]!
    expect(oldObserver.targets.size).toBe(1)

    // 切文章：哨兵 key 变化 → 节点重建。
    view.rerender(<Harness entryRef="e2" sentinelKey="s2" />)
    expect(MockIO.instances.length).toBeGreaterThanOrEqual(2)
    // 旧 observer 已被 disconnect，不再持有（已移除的）节点。
    expect(oldObserver.disconnectCount).toBeGreaterThanOrEqual(1)
    expect(oldObserver.targets.size).toBe(0)
    // 在场 observer 中仍持有目标的，持有的都是当前 DOM 里的哨兵。
    const currentSentinel = view.getByTestId('finish-sentinel')
    for (const io of MockIO.instances) {
      for (const target of io.targets) {
        expect(target).toBe(currentSentinel)
      }
    }
  })

  it('卸载：最后一个 observer disconnect（不再观察已移除的哨兵）', () => {
    const view = render(<Harness entryRef="e-boot" />)
    setupLayout(view)
    view.rerender(<Harness entryRef="e1" />)
    expect(MockIO.instances.length).toBeGreaterThanOrEqual(1)
    const before = MockIO.instances.reduce((sum, io) => sum + io.disconnectCount, 0)
    view.unmount()
    const after = MockIO.instances.reduce((sum, io) => sum + io.disconnectCount, 0)
    expect(after).toBeGreaterThan(before)
    for (const io of MockIO.instances) {
      expect(io.targets.size).toBe(0)
    }
  })
})
