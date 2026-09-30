/**
 * FIX-279 — iOS 橡皮筋（overscroll）不虚增/不提前触发「读到底自动已读」。
 *
 * 修复前：finish-read 的滚动推进读数直接取 container.scrollTop——
 * 橡皮筋在顶部回弹时 scrollTop 为负；若此刻正是基线采样点（挂载/
 * 换容器/切文章），负基线会虚增 progressPx（真实只读了 10px 也能
 * 达标提前判完成）；底部越界峰值同理污染 maxTop。
 * 修复后：基线与滚动读数统一夹取到 [0, scrollRange]——只依据有效
 * 阅读容器进度，越界读数不参与完成判定。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render } from '@testing-library/react'

import {
  FINISH_READ_DWELL_MS,
  resetFinishReadSessionForTests,
  useFinishRead,
  type FinishReadController,
} from '../lib/finish-read'

type Record_ = IntersectionObserverEntry

class MockIO {
  static instances: MockIO[] = []
  cb: IntersectionObserverCallback
  targets = new Set<Element>()
  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb
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
    this.cb([{ target: el, isIntersecting } as unknown as Record_], this as unknown as IntersectionObserver)
  }
}

let controller: FinishReadController
let markRead: (ref: string) => Promise<unknown>

function Harness({ entryRef, read }: { entryRef: string; read: boolean }) {
  const c = useFinishRead({
    enabled: true,
    entryRef,
    read,
    markRead: (ref) => markRead(ref),
  })
  controller = c
  return (
    <div ref={c.setContainer} data-testid="reader-container">
      <p>正文占位</p>
      <div ref={c.sentinelRef} data-testid="finish-sentinel" />
    </div>
  )
}

let container: HTMLDivElement
let sentinel: HTMLElement
let view: ReturnType<typeof render>

/** boot → 注入几何 → 切目标文章（与 finish-read.test.tsx 同一套路）。 */
function setup(): void {
  view = render(<Harness entryRef="e-boot" read={false} />)
  container = view.getByTestId('reader-container') as HTMLDivElement
  sentinel = view.getByTestId('finish-sentinel')
  Object.defineProperty(container, 'scrollHeight', { value: 2000, configurable: true })
  Object.defineProperty(container, 'clientHeight', { value: 600, configurable: true })
  Object.defineProperty(container, 'scrollTop', { value: 0, writable: true, configurable: true })
  view.rerender(<Harness entryRef="e1" read={false} />)
}

function userScrollTo(top: number) {
  act(() => {
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
  view?.unmount()
})

describe('FIX-279: 橡皮筋越界读数不参与完成判定', () => {
  it('顶部回弹中切文章 → 负基线被夹取：真实推进 10px 不判完成，读到 40px 才判', () => {
    setup()
    // 挂载/切文瞬间容器处于顶部橡皮筋偏移（scrollTop=-40）
    act(() => {
      container.scrollTop = -40
    })
    view.rerender(<Harness entryRef="e2" read={false} />)
    sentinelVisible(true)
    // 真实只向下推进 10px（< FINISH_READ_MIN_PROGRESS_PX）——修复前
    // 负基线把进度虚增为 50px，会在这里提前起 dwell。
    userScrollTo(10)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).not.toHaveBeenCalled()

    // 真实推进达到下限（10 → 60，推进 50 ≥ 40）→ 正常判定恰好一次
    userScrollTo(60)
    expect(controller.isDwelling).toBe(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS)
    })
    expect(markRead).toHaveBeenCalledTimes(1)
    expect(markRead).toHaveBeenCalledWith('e2')
  })

  it('底部越界峰值（scrollTop > 滚动余量）夹取到余量：判定一次，回弹后不重复', () => {
    setup()
    // 余量 = 2000 - 600 = 1400；橡皮筋把 scrollTop 推到 1500（越界）
    userScrollTo(1400)
    userScrollTo(1500) // overscroll 峰值
    userScrollTo(1350) // 回弹落回
    sentinelVisible(true)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS)
    })
    expect(markRead).toHaveBeenCalledTimes(1)

    // 回弹稳定后再次越界（真实场景：底部反复橡皮筋）——不重复派发
    sentinelVisible(false)
    sentinelVisible(true)
    userScrollTo(1520)
    userScrollTo(1380)
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS * 3)
    })
    expect(markRead).toHaveBeenCalledTimes(1)
  })
})
