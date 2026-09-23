/** N054 阅读标尺增强测试 — 宽度/深浅三档持久化、键盘操作（↑↓ 逐行、
 * [ ] 宽度、- = 深浅、Esc 关闭）、指针跟随仍生效、纯覆盖层不动正文 DOM。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingRuler, {
  readRulerEnabled,
  readRulerShade,
  readRulerWidth,
  rulerLineStep,
  READING_RULER_SHADE_KEY,
  READING_RULER_WIDTH_KEY,
} from '../components/ReadingRuler'

function mountArticle(): HTMLElement {
  const div = document.createElement('div')
  div.className = 'lumi-reader-article'
  div.innerHTML = '<p>正文内容，用于断言 DOM 不被辅助线修改。</p>'
  document.body.appendChild(div)
  return div
}

beforeEach(() => {
  localStorage.clear()
  // rAF 同步化：pointermove 的节流回调立即执行
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    cb(0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
})

function enableRuler(container: HTMLElement) {
  fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))
  fireEvent.pointerMove(container, { clientY: 120 })
  const ruler = document.querySelector('[data-lumi-reading-ruler]') as HTMLElement | null
  expect(ruler).not.toBeNull()
  return ruler!
}

describe('宽度/深浅档位（持久化）', () => {
  it('缺省 = 中等宽度 / 中档深浅', () => {
    expect(readRulerWidth()).toBe('medium')
    expect(readRulerShade()).toBe(2)
  })

  it('损坏值回退默认', () => {
    localStorage.setItem(READING_RULER_WIDTH_KEY, 'huge')
    localStorage.setItem(READING_RULER_SHADE_KEY, '9')
    expect(readRulerWidth()).toBe('medium')
    expect(readRulerShade()).toBe(2)
  })
})

describe('键盘操作（开启时）', () => {
  it('ArrowUp/ArrowDown 按行高步进移动辅助线；未显示时从视口中部出现', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))
    expect(document.querySelector('[data-lumi-reading-ruler]')).toBeNull()

    // jsdom：fontSize 16px，行距变量缺省 → 步进 16 × 1.75 = 28
    expect(rulerLineStep(container)).toBe(28)
    const initialY = window.innerHeight / 2
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    let ruler = document.querySelector('[data-lumi-reading-ruler]') as HTMLElement
    expect(ruler.style.top).toBe(`${initialY + 28 - 9}px`)
    fireEvent.keyDown(window, { key: 'ArrowUp' })
    ruler = document.querySelector('[data-lumi-reading-ruler]') as HTMLElement
    expect(ruler.style.top).toBe(`${initialY - 9}px`)
  })

  it('指针跟随仍生效，与键盘移动可交替', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    const ruler = enableRuler(container)
    expect(ruler.style.top).toBe('111px')
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    expect(
      (document.querySelector('[data-lumi-reading-ruler]') as HTMLElement).style.top,
    ).toBe(`${120 + 28 - 9}px`)
  })

  it('[ / ] 调宽度（窄 60% / 中 80% / 宽 100%），并持久化', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    const ruler = enableRuler(container)
    expect(ruler.style.width).toBe('80%')

    fireEvent.keyDown(window, { key: '[' })
    expect(
      (document.querySelector('[data-lumi-reading-ruler]') as HTMLElement).style.width,
    ).toBe('60%')
    expect(readRulerWidth()).toBe('narrow')
    // 已是窄档，继续 [ 不越界
    fireEvent.keyDown(window, { key: '[' })
    expect(readRulerWidth()).toBe('narrow')

    fireEvent.keyDown(window, { key: ']' })
    fireEvent.keyDown(window, { key: ']' })
    expect(readRulerWidth()).toBe('wide')
    expect(
      (document.querySelector('[data-lumi-reading-ruler]') as HTMLElement).style.width,
    ).toBe('100%')
  })

  it('- / = 调深浅（1–3 级不透明度），并持久化；档位不越界', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    const ruler = enableRuler(container)
    expect(ruler.dataset.lumiReadingRulerShade).toBe('2')

    fireEvent.keyDown(window, { key: '=' })
    expect(readRulerShade()).toBe(3)
    fireEvent.keyDown(window, { key: '=' })
    expect(readRulerShade()).toBe(3) // 不越界
    fireEvent.keyDown(window, { key: '-' })
    fireEvent.keyDown(window, { key: '-' })
    fireEvent.keyDown(window, { key: '-' })
    expect(readRulerShade()).toBe(1)
    const current = document.querySelector('[data-lumi-reading-ruler]') as HTMLElement
    expect(current.dataset.lumiReadingRulerShade).toBe('1')
    // 深浅 = 主线不透明度档位（浅档 0.35）
    const line = current.children[1] as HTMLElement
    expect(line.style.opacity).toBe('0.35')
  })

  it('Esc 关闭辅助线（持久化为关；覆盖层卸载）', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    enableRuler(container)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(document.querySelector('[data-lumi-reading-ruler]')).toBeNull()
    expect(readRulerEnabled()).toBe(false)
    expect(screen.getByRole('button', { name: '行辅助线' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('文本输入目标中的按键不调辅助线', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    enableRuler(container)
    const input = document.createElement('input')
    document.body.appendChild(input)
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    // 位置未变（仍是指针所在 120）
    expect(
      (document.querySelector('[data-lumi-reading-ruler]') as HTMLElement).style.top,
    ).toBe('111px')
    input.remove()
  })

  it('关闭后完整还原：覆盖层移除、设置保留（再次开启用持久化档位）', () => {
    const container = mountArticle()
    render(<ReadingRuler />)
    enableRuler(container)
    fireEvent.keyDown(window, { key: '[' })
    fireEvent.keyDown(window, { key: '=' })
    fireEvent.click(screen.getByRole('button', { name: '关闭行辅助线' }))
    expect(document.querySelector('[data-lumi-reading-ruler]')).toBeNull()
    expect(readRulerWidth()).toBe('narrow')
    expect(readRulerShade()).toBe(3)
  })
})

describe('纯覆盖层（不改正文 DOM）', () => {
  it('开启 + 移动 + 调整期间，正文 innerHTML 逐字节不变', () => {
    const container = mountArticle()
    const before = container.innerHTML
    render(<ReadingRuler />)
    enableRuler(container)
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    fireEvent.keyDown(window, { key: '[' })
    fireEvent.keyDown(window, { key: '=' })
    fireEvent.pointerMove(container, { clientY: 300 })
    expect(container.innerHTML).toBe(before)
    // 覆盖层是 body 下的 fixed portal，不在正文容器内
    expect(container.querySelector('[data-lumi-reading-ruler]')).toBeNull()
  })
})
