/** R05 阅读行辅助线测试 — 开关持久化 + 渲染/卸载 + 指针跟随。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingRuler, {
  readRulerEnabled,
  writeRulerEnabled,
  READING_RULER_STORAGE_KEY,
} from '../components/ReadingRuler'

function mountArticle(): HTMLElement {
  const div = document.createElement('div')
  div.className = 'lumi-reader-article'
  div.innerHTML = '<p>正文内容。</p>'
  document.body.appendChild(div)
  return div
}

beforeEach(() => {
  localStorage.clear()
  // rAF 同步化：pointermove 的节流回调立即执行，测试无需等帧
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    cb(0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
  // 只移除本测试自建的文章容器（非 React 托管）；React 门户节点交给
  // setup.ts 的 cleanup() 卸载（清空 body.innerHTML 会撕裂 React 卸载）
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
})

describe('readRulerEnabled / writeRulerEnabled（默认关）', () => {
  it('无 key / 损坏值 → 默认关', () => {
    expect(readRulerEnabled()).toBe(false)
    localStorage.setItem(READING_RULER_STORAGE_KEY, '0')
    expect(readRulerEnabled()).toBe(false)
  })

  it('writeRulerEnabled(true) → key 为 1；false → 0（明确覆盖不删 key）', () => {
    writeRulerEnabled(true)
    expect(localStorage.getItem(READING_RULER_STORAGE_KEY)).toBe('1')
    expect(readRulerEnabled()).toBe(true)
    writeRulerEnabled(false)
    expect(localStorage.getItem(READING_RULER_STORAGE_KEY)).toBe('0')
    expect(readRulerEnabled()).toBe(false)
  })
})

describe('ReadingRuler 组件（自包含挂载）', () => {
  it('默认关：渲染开关按钮但无辅助线；开启后持久化并出现开关说明', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    const btn = screen.getByRole('button', { name: '行辅助线' })
    expect(btn).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByLabelText('行辅助线说明')).toBeNull()

    fireEvent.click(btn)
    expect(screen.getByRole('button', { name: '关闭行辅助线' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByLabelText('行辅助线说明')).toBeInTheDocument()
    expect(localStorage.getItem(READING_RULER_STORAGE_KEY)).toBe('1')
    // 未有指针前不渲染辅助线本体
    expect(container.querySelector('[data-lumi-reading-ruler]')).toBeNull()
    void container
  })

  it('pointermove：辅助线跟随 Y（top = clientY - 9，2px 线 + 上下 8px 渐隐）；pointerleave 隐藏', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))

    fireEvent.pointerMove(container, { clientY: 120 })
    let ruler = document.querySelector('[data-lumi-reading-ruler]') as HTMLElement | null
    expect(ruler).not.toBeNull()
    expect(ruler!.style.top).toBe('111px')
    expect(ruler!.style.height).toBe('18px')

    fireEvent.pointerMove(container, { clientY: 300 })
    ruler = document.querySelector('[data-lumi-reading-ruler]') as HTMLElement | null
    expect(ruler!.style.top).toBe('291px')

    fireEvent.pointerLeave(container)
    expect(document.querySelector('[data-lumi-reading-ruler]')).toBeNull()
  })

  it('再次点击关闭：辅助线卸载 + 持久化为关', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))
    fireEvent.pointerMove(container, { clientY: 50 })
    expect(document.querySelector('[data-lumi-reading-ruler]')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '关闭行辅助线' }))
    expect(document.querySelector('[data-lumi-reading-ruler]')).toBeNull()
    expect(localStorage.getItem(READING_RULER_STORAGE_KEY)).toBe('0')
    expect(screen.getByRole('button', { name: '行辅助线' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('容器晚于组件挂载（Reader 异步渲染）：观察 DOM 后自包含挂上', async () => {
    render(<ReadingRuler />)
    const container = mountArticle()
    // MutationObserver 回调是微任务：flush 后组件才拿到容器
    await new Promise((resolve) => setTimeout(resolve, 20))
    fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))
    fireEvent.pointerMove(container, { clientY: 88 })
    await waitFor(
      () => {
        expect(document.querySelector('[data-lumi-reading-ruler]')).not.toBeNull()
      },
      { timeout: 3000 },
    )
  })

  it('卸载：监听与辅助线一并清理（不残留覆盖层）', () => {
    const container = mountArticle()
    const { unmount } = render(<ReadingRuler />)
    fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))
    fireEvent.pointerMove(container, { clientY: 60 })
    expect(document.querySelector('[data-lumi-reading-ruler]')).not.toBeNull()
    unmount()
    expect(document.querySelector('[data-lumi-reading-ruler]')).toBeNull()
  })
})
