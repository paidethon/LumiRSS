/** P0-2 正文读到底自动已读 — 状态机单元回归（2026-09-18 移动端专项）。
 *
 * 覆盖 §2.4 判定规则与 §2.5 相关矩阵（状态机部分）：
 * - 首轮 observer / 程序恢复位置 / 图片加载位移（程序窗口）/ 上滑
 *   不构成读完证据；
 * - 主动向下推进 + 末尾稳定可见 ≥ DWELL_MS + 前台 → 恰好一次派发；
 * - 停留期间滚离末尾 / 切文章 / 进后台 → 取消，不误作用到下一篇文章；
 * - 失败释放重试；成功后不重复派发；
 * - 手动未读（read true→false）→ 本次访问暂停自动判定；
 * - 短文 → 不自动判定，「读完了」按钮显式确认；
 * - 开关关闭 → 全部路径不派发。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'
import {
  FINISH_READ_DWELL_MS,
  FINISH_READ_MIN_PROGRESS_PX,
  FINISH_READ_PROGRAMMATIC_WINDOW_MS,
  requiredProgressFor,
  resetFinishReadSessionForTests,
  shouldDwell,
  useFinishRead,
  type FinishReadController,
} from '../lib/finish-read'

// ---- 纯函数 ----

describe('shouldDwell / requiredProgressFor 纯决策', () => {
  const base = {
    enabled: true,
    read: false,
    suspended: false,
    endVisible: true,
    pageVisible: true,
    progressPx: FINISH_READ_MIN_PROGRESS_PX,
    scrollRangePx: 2000,
  }
  it('全部条件齐备才判定；任一缺失（关闭/已读/暂停/末尾不可见/后台/推进不足）都不判定', () => {
    expect(shouldDwell(base)).toBe(true)
    expect(shouldDwell({ ...base, enabled: false })).toBe(false)
    expect(shouldDwell({ ...base, read: true })).toBe(false)
    expect(shouldDwell({ ...base, suspended: true })).toBe(false)
    expect(shouldDwell({ ...base, endVisible: false })).toBe(false)
    expect(shouldDwell({ ...base, pageVisible: false })).toBe(false)
    expect(shouldDwell({ ...base, progressPx: FINISH_READ_MIN_PROGRESS_PX - 1 })).toBe(false)
  })
  it('微小滚动余量按余量一半取阈值（至少 8px）；零余量永不可达（短文走按钮）', () => {
    expect(requiredProgressFor(2000)).toBe(FINISH_READ_MIN_PROGRESS_PX)
    expect(requiredProgressFor(60)).toBe(30)
    expect(requiredProgressFor(10)).toBe(8)
    expect(shouldDwell({ ...base, scrollRangePx: 0, progressPx: 999 })).toBe(false)
    expect(shouldDwell({ ...base, scrollRangePx: 60, progressPx: 30 })).toBe(true)
  })
})

// ---- Hook 状态机 ----

type Record_ = IntersectionObserverEntry

class MockIO {
  static instances: MockIO[] = []
  cb: IntersectionObserverCallback
  root: Document | Element | null
  targets = new Set<Element>()
  constructor(cb: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.cb = cb
    this.root = options?.root ?? null
    MockIO.instances.push(this)
  }
  observe(el: Element) {
    this.targets.add(el)
  }
  unobserve(el: Element) {
    this.targets.delete(el)
  }
  disconnect() {
    this.targets.clear()
  }
  trigger(el: Element, isIntersecting: boolean) {
    this.cb(
      [{ target: el, isIntersecting } as unknown as Record_],
      this as unknown as IntersectionObserver,
    )
  }
}

let controller: FinishReadController
let markRead: (ref: string) => Promise<unknown>

function Harness(props: {
  enabled: boolean
  entryRef: string | null
  read: boolean
}) {
  markRead = markRead ?? vi.fn(() => Promise.resolve())
  const c = useFinishRead({
    enabled: props.enabled,
    entryRef: props.entryRef,
    read: props.read,
    markRead: (ref) => markRead(ref),
  })
  controller = c
  return (
    <div ref={c.setContainer} data-testid="reader-container" data-reader-container="">
      <p>正文占位</p>
      <div ref={c.sentinelRef} data-testid="finish-sentinel" data-finish-sentinel="" />
    </div>
  )
}

let container: HTMLDivElement
let sentinel: HTMLElement

function setup(props: { enabled?: boolean; entryRef?: string | null; read?: boolean } = {}) {
  // 先用 boot ref 挂载（jsdom 默认 scrollHeight=0），再注入布局尺寸，
  // 然后切到目标文章——切换路径会重新测量容器。
  const view = render(<Harness enabled={props.enabled ?? true} entryRef="e-boot" read={false} />)
  container = view.getByTestId('reader-container') as HTMLDivElement
  sentinel = view.getByTestId('finish-sentinel')
  Object.defineProperty(container, 'scrollHeight', { value: 2000, configurable: true })
  Object.defineProperty(container, 'clientHeight', { value: 600, configurable: true })
  // jsdom scrollTop 赋值后读回恒为 0（无布局）：覆盖为普通可写属性。
  Object.defineProperty(container, 'scrollTop', { value: 0, writable: true, configurable: true })
  view.rerender(
    <Harness enabled={props.enabled ?? true} entryRef={props.entryRef ?? 'e1'} read={props.read ?? false} />,
  )
  return view
}

/** 模拟用户滚动（scrollTop 赋值 + scroll 事件）。 */
function userScrollTo(top: number) {
  act(() => {
    container.scrollTop = top
    container.dispatchEvent(new Event('scroll'))
  })
}

/** 模拟程序性滚动（恢复位置 / 自动滚屏）。 */
function programmaticScrollTo(top: number) {
  act(() => {
    controller.noteProgrammaticScroll()
    container.scrollTop = top
    container.dispatchEvent(new Event('scroll'))
  })
}

function sentinelVisible(v: boolean) {
  act(() => {
    for (const io of MockIO.instances) {
      if (io.targets.has(sentinel)) io.trigger(sentinel, v)
    }
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  MockIO.instances = []
  markRead = vi.fn(() => Promise.resolve())
  resetFinishReadSessionForTests()
  vi.stubGlobal('IntersectionObserver', MockIO as unknown as typeof IntersectionObserver)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useFinishRead 状态机', () => {
  it('打开文章首轮 observer（末尾可见但零推进）不派发', () => {
    const view = setup()
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    expect(controller.isDwelling).toBe(false)
    view.unmount()
  })

  it('程序恢复到旧位置不算主动推进；不派发', () => {
    const view = setup()
    programmaticScrollTo(1300) // 恢复到接近底部
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    view.unmount()
  })

  it('主动向下推进 + 末尾稳定可见 ≥ DWELL_MS → 恰好一次派发；重复停留不二次派发', async () => {
    const view = setup()
    sentinelVisible(false)
    userScrollTo(500)
    userScrollTo(1200)
    sentinelVisible(true)
    expect(controller.isDwelling).toBe(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS - 1)
    })
    expect(markRead).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    expect(markRead).toHaveBeenCalledWith('e1')
    // 成功后再次满足条件也不重复派发。
    userScrollTo(1300)
    sentinelVisible(false)
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    view.unmount()
  })

  it('主动推进后程序回顶：推进保留（已读过的深度不丢），但末尾不可见（真实几何）不派发', () => {
    const view = setup()
    userScrollTo(1200)
    programmaticScrollTo(0) // 程序回顶：不新增推进，也不清空已积累推进
    sentinelVisible(false) // 回到顶部 → 末尾不可见
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    view.unmount()
  })

  it('停留期间滚离末尾（图片加载/译文展开把哨兵推出视口）→ 取消', () => {
    const view = setup()
    userScrollTo(1200)
    sentinelVisible(true)
    expect(controller.isDwelling).toBe(true)
    sentinelVisible(false)
    expect(controller.isDwelling).toBe(false)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    view.unmount()
  })

  it('程序窗口过期后的位移重新计入（窗口只是短暂豁免）', () => {
    const view = setup()
    act(() => {
      controller.noteProgrammaticScroll()
      vi.advanceTimersByTime(FINISH_READ_PROGRAMMATIC_WINDOW_MS + 50)
      container.scrollTop = 1000
      container.dispatchEvent(new Event('scroll'))
    })
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS)
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    view.unmount()
  })

  it('切文章取消未完成判定；推进量不带入下一篇（不误作用）', () => {
    const view = setup({ entryRef: 'e1' })
    userScrollTo(1200)
    sentinelVisible(true)
    expect(controller.isDwelling).toBe(true)
    view.rerender(<Harness enabled={true} entryRef="e2" read={false} />)
    expect(controller.isDwelling).toBe(false)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    // 新文章：首轮 observer 末尾可见 + 零推进 → 不派发。
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    view.unmount()
  })

  it('进入后台取消计时；回前台重新评估（新停留窗口）', () => {
    const view = setup()
    userScrollTo(1200)
    sentinelVisible(true)
    expect(controller.isDwelling).toBe(true)
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(controller.isDwelling).toBe(false)
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(controller.isDwelling).toBe(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS)
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    view.unmount()
  })

  it('服务端失败释放重试：错误可见，retry() 再次派发且成功', async () => {
    markRead = vi.fn(
      () => Promise.reject(new Error('网络中断')),
    )
    const view = setup()
    userScrollTo(1200)
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS)
    })
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    expect(controller.autoError).toContain('网络中断')
    // 失败后自动路径可再次触发（未进永久已处理集合）。
    markRead = vi.fn(() => Promise.resolve())
    act(() => {
      controller.retry()
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    view.unmount()
  })

  it('手动未读（read true→false）→ 本次访问暂停自动判定', () => {
    const view = setup({ read: false })
    view.rerender(<Harness enabled={true} entryRef="e1" read={true} />)
    view.rerender(<Harness enabled={true} entryRef="e1" read={false} />)
    userScrollTo(1200)
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    view.unmount()
  })

  it('短文（无滚动空间）→ 不自动判定；「读完了」按钮显式确认派发', () => {
    const view = setup()
    Object.defineProperty(container, 'scrollHeight', { value: 600, configurable: true })
    act(() => {
      // 触发 remeasure 路径：切换文章重测
      view.rerender(<Harness enabled={true} entryRef="e-short" read={false} />)
    })
    expect(controller.needsExplicitConfirm).toBe(true)
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    act(() => {
      controller.confirmFinished()
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    expect(markRead).toHaveBeenCalledWith('e-short')
    view.unmount()
  })

  it('开关关闭 → 任何路径（自动/短文按钮）都不显示且不派发', () => {
    const view = setup({ enabled: false })
    userScrollTo(1200)
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()
    expect(controller.needsExplicitConfirm).toBe(false)
    view.unmount()
  })
})

describe('observer root 约束', () => {
  it('哨兵 observer 以 Reader 滚动容器为 root（不使用视口/window）', () => {
    const view = setup()
    const withSentinel = MockIO.instances.filter((io) => io.targets.has(sentinel))
    expect(withSentinel.length).toBeGreaterThan(0)
    for (const io of withSentinel) {
      expect(io.root).toBe(container)
    }
    view.unmount()
  })
})
