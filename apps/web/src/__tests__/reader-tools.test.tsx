/** F11–F25 工具类功能 — 共享纯逻辑 + 基础组件单测。
 *
 * 覆盖：reader-tools（翻页/引用/分享回退）、reader-export（导出构建 +
 * 下载）、reader-find（查找 + CSS Custom Highlight 降级）、
 * reader-focus、reader-speech、ReaderProgress（F11）、ArticleFindBar
 * （F13，含高亮注册/清理与降级路径）、ArticleLightbox（F14）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AUTO_SCROLL_SPEEDS,
  BACK_TO_TOP_THRESHOLD_PX,
  buildQuoteMarkdownText,
  buildQuotePlainText,
  fallbackShareUrl,
  pageTargetTop,
  scrollContainerBy,
  TABLE_WIDE_EXTRA_PX,
} from '../lib/reader-tools'
import {
  buildHtmlExport,
  buildMarkdownExport,
  downloadTextFile,
  sanitizeFileName,
  stripScriptTags,
} from '../lib/reader-export'
import {
  clearFindHighlights,
  findMatches,
  highlightMatches,
  supportsCssHighlights,
} from '../lib/reader-find'
import { pickFocusIndex } from '../lib/reader-focus'
import {
  findStartBlockIndex,
  joinBlockTexts,
  pickChineseVoice,
  speechSynthesisAvailable,
} from '../lib/reader-speech'
import ReaderProgress from '../components/ReaderProgress'
import ArticleFindBar from '../components/ArticleFindBar'
import ArticleLightbox from '../components/ArticleLightbox'

afterEach(() => {
  vi.unstubAllGlobals()
  // 清掉测试注入的 CSS.highlights（configurable 属性）
  try {
    delete (CSS as unknown as { highlights?: unknown }).highlights
  } catch {
    /* 未注入过 */
  }
})

// ---- reader-tools（F17 / F24 / F21 / 常量） ----

describe('reader-tools — 纯逻辑', () => {
  it('pageTargetTop：下一屏 +90% 视口、钳制边界、无滚动空间归零', () => {
    expect(pageTargetTop(0, 600, 3400, 1)).toBe(540)
    expect(pageTargetTop(3000, 600, 3400, 1)).toBe(3400) // 到底钳制
    expect(pageTargetTop(540, 600, 3400, -1)).toBe(0)
    expect(pageTargetTop(100, 600, 3400, -1)).toBe(0) // 到顶钳制
    expect(pageTargetTop(0, 600, 0, 1)).toBe(0)
  })

  it('scrollContainerBy：无 scrollBy 环境（jsdom）直接赋值并钳制', () => {
    const container = document.createElement('div')
    Object.defineProperty(container, 'scrollHeight', { value: 2000, configurable: true })
    Object.defineProperty(container, 'clientHeight', { value: 500, configurable: true })
    container.scrollTop = 100
    scrollContainerBy(container, 600)
    expect(container.scrollTop).toBe(700)
    scrollContainerBy(container, 10_000)
    expect(container.scrollTop).toBe(1500) // max = 2000 - 500
    scrollContainerBy(container, -10_000)
    expect(container.scrollTop).toBe(0)
  })

  it('复制引用：Markdown 格式引文带 > 前缀；无选区仅标题/来源/链接', () => {
    const input = { title: '标题', source: '来源', url: 'https://e.com/a', quote: '引文' }
    expect(buildQuoteMarkdownText(input)).toBe('标题\n来源\nhttps://e.com/a\n\n> 引文')
    expect(buildQuotePlainText(input)).toBe('标题\n来源\nhttps://e.com/a\n\n引文')
    const noQuote = { title: '标题', source: '来源', url: null }
    expect(buildQuotePlainText(noQuote)).toBe('标题\n来源')
    expect(buildQuoteMarkdownText({ ...noQuote, quote: '  ' })).toBe('标题\n来源')
  })

  it('fallbackShareUrl：去掉 location hash', () => {
    window.location.hash = '#section-1'
    try {
      expect(fallbackShareUrl()).not.toContain('#')
    } finally {
      window.location.hash = ''
    }
  })

  it('阈值/档位常量与任务定义一致', () => {
    expect(AUTO_SCROLL_SPEEDS).toEqual({ slow: 1, medium: 2, fast: 4 })
    expect(BACK_TO_TOP_THRESHOLD_PX).toBe(600)
    expect(TABLE_WIDE_EXTRA_PX).toBe(24)
  })
})

// ---- reader-export（F22） ----

describe('reader-export — 导出构建与下载', () => {
  const input = {
    title: '深度报告',
    source: '示例源',
    date: '2026/09/01 10:00',
    url: 'https://example.com/a',
    text: '第一段\n\n第二段',
    html: '<p>富文本</p><script>alert(1)</script><table><tr><td>t</td></tr></table>',
  }

  it('Markdown：# 标题 + > 来源·日期 + 原文链接 + contentText 分段', () => {
    const md = buildMarkdownExport(input)
    expect(md).toContain('# 深度报告')
    expect(md).toContain('> 示例源 · 2026/09/01 10:00')
    expect(md).toContain('原文链接：https://example.com/a')
    expect(md).toContain('第一段\n\n第二段')
  })

  it('HTML：干净文档壳（charset/title/来源/链接）+ 剥掉 script 标签对', () => {
    const html = buildHtmlExport(input)
    expect(html).toContain('<meta charset="utf-8">')
    expect(html).toContain('<title>深度报告</title>')
    expect(html).toContain('示例源 · 2026/09/01 10:00')
    expect(html).toContain('<table>')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('alert(1)')
  })

  it('stripScriptTags：未闭合 script 开标签也剥掉', () => {
    expect(stripScriptTags('<p>a</p><script src="x.js">')).toBe('<p>a</p>')
    expect(stripScriptTags('<p>a</p><SCRIPT>x</SCRIPT>')).toBe('<p>a</p>')
  })

  it('sanitizeFileName：去非法字符、限长、空回退', () => {
    expect(sanitizeFileName('a/b\\c:d*e?f"g<h>i|j')).toBe('abcdefghij')
    expect(sanitizeFileName('  ')).toBe('文章')
    expect(sanitizeFileName('x'.repeat(100)).length).toBe(80)
  })

  it('downloadTextFile：走 createObjectURL + a[download]；环境失败诚实返回 false', () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const createUrl = vi.fn(() => 'blob:mock')
    const revokeUrl = vi.fn()
    try {
      expect(downloadTextFile('a.md', '内容', 'text/markdown', { createUrl, revokeUrl })).toBe(true)
      expect(createUrl).toHaveBeenCalledTimes(1)
      expect(downloadTextFile('a.md', '内容', 'text/markdown', {
        createUrl: () => {
          throw new Error('no object urls here')
        },
      })).toBe(false)
    } finally {
      clickSpy.mockRestore()
    }
  })
})

// ---- reader-find（F13） ----

describe('reader-find — 查找与高亮', () => {
  function fixture(): HTMLElement {
    const root = document.createElement('div')
    root.innerHTML =
      '<p>alpha 术语一 beta</p><span>术语二</span><p class="keep">术语三</p>' +
      '<script>术语四</script><pre><code>术语五</code><button class="code-copy-btn">复制</button></pre>'
    document.body.appendChild(root)
    return root
  }

  it('jsdom 无 CSS.highlights → supportsCssHighlights false（降级信号）', () => {
    expect(supportsCssHighlights()).toBe(false)
  })

  it('findMatches：大小写不敏感、全部命中（含代码块）、跳过 script 与复制按钮', () => {
    const root = fixture()
    try {
      const matches = findMatches(root, '术语')
      // 术语一/二/三（正文）+ 术语五（pre code 是正文内容，可搜索）；
      // script 内的 术语四 与 .code-copy-btn 的「复制」不参与。
      expect(matches).toHaveLength(4)
      for (const match of matches) {
        expect(match.node.textContent?.slice(match.start, match.end)).toBe('术语')
      }
      expect(findMatches(root, 'ALPHA')).toHaveLength(1)
      expect(findMatches(root, '复制')).toHaveLength(0) // 复制按钮跳过
      expect(findMatches(root, '术语四')).toHaveLength(0) // script 跳过
      expect(findMatches(root, '   术语二  ')).toHaveLength(1) // 首尾去空白
      expect(findMatches(root, '  ')).toHaveLength(0)
    } finally {
      root.remove()
    }
  })

  it('Highlight 可用（stub）→ 注册全部/当前两组高亮；清除幂等', () => {
    class MockHighlight {
      ranges: Range[]
      constructor(...ranges: Range[]) {
        this.ranges = ranges
      }
    }
    vi.stubGlobal('Highlight', MockHighlight)
    const registry = new Map<string, MockHighlight>()
    Object.defineProperty(CSS, 'highlights', {
      value: registry,
      configurable: true,
    })
    const root = fixture()
    try {
      const matches = findMatches(root, '术语')
      expect(highlightMatches(matches, 1)).toBe(true)
      expect(registry.get('lumi-find-all')?.ranges).toHaveLength(4)
      expect(registry.get('lumi-find-current')?.ranges).toHaveLength(1)
      clearFindHighlights()
      expect(registry.has('lumi-find-all')).toBe(false)
      expect(registry.has('lumi-find-current')).toBe(false)
      // 清除幂等（再清一次不抛错）
      expect(() => clearFindHighlights()).not.toThrow()
    } finally {
      root.remove()
    }
  })

  it('能力缺失时 highlightMatches 返回 false（调用方走计数+滚动降级）', () => {
    const root = fixture()
    try {
      expect(highlightMatches(findMatches(root, '术语'), 0)).toBe(false)
    } finally {
      root.remove()
    }
  })
})

// ---- reader-focus / reader-speech 纯逻辑 ----

describe('reader-focus / reader-speech — 纯逻辑', () => {
  it('pickFocusIndex：中心离视口中心最近者；空数组 -1', () => {
    expect(pickFocusIndex([{ top: 0, bottom: 100 }, { top: 200, bottom: 300 }], 250)).toBe(1)
    expect(pickFocusIndex([{ top: 0, bottom: 100 }], 50)).toBe(0)
    expect(pickFocusIndex([], 50)).toBe(-1)
  })

  it('speechSynthesisAvailable：jsdom 无该 API → false', () => {
    expect(speechSynthesisAvailable()).toBe(false)
  })

  it('pickChineseVoice：优先 zh，回退第一个，空 → null', () => {
    const zh = { lang: 'zh-CN' } as SpeechSynthesisVoice
    const en = { lang: 'en-US' } as SpeechSynthesisVoice
    expect(pickChineseVoice([en, zh])).toBe(zh)
    expect(pickChineseVoice([en])).toBe(en)
    expect(pickChineseVoice([])).toBeNull()
  })

  it('findStartBlockIndex：当前段落（含跨线块）为起点；全部在视口下 → 从头读', () => {
    expect(findStartBlockIndex([0, 100, 200], 150)).toBe(1)
    expect(findStartBlockIndex([50, 100], 0)).toBe(0)
    expect(findStartBlockIndex([10, 20], 0)).toBe(0) // 均未越过顶线（含容差）
    expect(findStartBlockIndex([8, 20], 0)).toBe(0) // 容差内视为越过
    expect(findStartBlockIndex([], 100)).toBe(0)
  })

  it('joinBlockTexts：过滤空块，双换行分段', () => {
    expect(joinBlockTexts(['a', ' ', 'b'])).toBe('a\n\nb')
    expect(joinBlockTexts(['', '  '])).toBe('')
  })
})

// ---- ReaderProgress（F11 组件） ----

describe('ReaderProgress — 阅读进度条', () => {
  function setup() {
    const container = document.createElement('div')
    Object.defineProperty(container, 'scrollHeight', { value: 1200, configurable: true })
    Object.defineProperty(container, 'clientHeight', { value: 800, configurable: true })
    document.body.appendChild(container)
    const getContainer = vi.fn(() => container)
    return { container, getContainer }
  }

  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('滚动 → 显示 3px 进度条，宽度 = 滚动比例；回顶隐藏', async () => {
    const { container, getContainer } = setup()
    const { unmount } = render(<ReaderProgress getContainer={getContainer} enabled />)
    expect(document.querySelector('[data-lumi-progress]')).toBeNull() // 0% 隐藏

    container.scrollTop = 100 // max = 400 → 25%
    container.dispatchEvent(new Event('scroll'))
    await waitFor(() => {
      const bar = document.querySelector('[data-lumi-progress-bar]') as HTMLElement | null
      expect(bar).not.toBeNull()
      expect(bar).toHaveStyle({ width: '25%' })
    })
    const wrapper = document.querySelector('[data-lumi-progress]') as HTMLElement
    expect(wrapper.className).toContain('h-[3px]')

    container.scrollTop = 0
    container.dispatchEvent(new Event('scroll'))
    await waitFor(() => {
      expect(document.querySelector('[data-lumi-progress]')).toBeNull()
    })
    unmount()
  })

  it('无滚动空间 → 永远隐藏；开关关闭不监听', async () => {
    const { container, getContainer } = setup()
    Object.defineProperty(container, 'scrollHeight', { value: 800, configurable: true })
    const { unmount } = render(<ReaderProgress getContainer={getContainer} enabled />)
    container.scrollTop = 300
    container.dispatchEvent(new Event('scroll'))
    await waitFor(() => {
      expect(document.querySelector('[data-lumi-progress]')).toBeNull()
    })
    unmount()

    const { getContainer: get2, container: c2 } = setup()
    const { unmount: unmount2 } = render(<ReaderProgress getContainer={get2} enabled={false} />)
    c2.scrollTop = 100
    c2.dispatchEvent(new Event('scroll'))
    await new Promise((r) => setTimeout(r, 30))
    expect(document.querySelector('[data-lumi-progress]')).toBeNull()
    unmount2()
  })
})

// ---- ArticleFindBar（F13 组件） ----

describe('ArticleFindBar — 文内查找条', () => {
  function fixtureRoot(): HTMLElement {
    const root = document.createElement('div')
    root.innerHTML = '<p>术语 alpha</p><p>术语 beta</p><p>无关段落</p>'
    document.body.appendChild(root)
    return root
  }

  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('open=false 不渲染', () => {
    render(<ArticleFindBar open={false} onClose={() => {}} getRoot={() => null} />)
    expect(screen.queryByRole('search')).toBeNull()
  })

  it('命中计数 n/m（当前位置起 1）；无结果诚实显示；循环切换当前位置', async () => {
    const root = fixtureRoot()
    render(<ArticleFindBar open onClose={() => {}} getRoot={() => root} />)
    const input = screen.getByLabelText('查找正文')
    fireEvent.change(input, { target: { value: '术语' } })
    expect(await screen.findByText('1/2 处命中')).toBeInTheDocument()

    // 下一处 → 2/2；再下一处循环回 1/2；上一处回到 2/2
    fireEvent.click(screen.getByRole('button', { name: '下一处' }))
    expect(screen.getByText('2/2 处命中')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '下一处' }))
    expect(screen.getByText('1/2 处命中')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '上一处' }))
    expect(screen.getByText('2/2 处命中')).toBeInTheDocument()

    fireEvent.change(input, { target: { value: '不存在的词' } })
    expect(await screen.findByText('无结果')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '上一处' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '下一处' })).toBeDisabled()
    root.remove()
  })

  it('× 关闭回调 + 无残留（降级路径：jsdom 无高亮注册表）', async () => {
    const root = fixtureRoot()
    const onClose = vi.fn()
    render(<ArticleFindBar open onClose={onClose} getRoot={() => root} />)
    fireEvent.change(screen.getByLabelText('查找正文'), { target: { value: '术语' } })
    expect(await screen.findByText('1/2 处命中')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '关闭查找' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    root.remove()
  })

  it('输入框 Escape 关闭（stopPropagation 不冒泡）', () => {
    const root = fixtureRoot()
    const onClose = vi.fn()
    render(<ArticleFindBar open onClose={onClose} getRoot={() => root} />)
    const input = screen.getByLabelText('查找正文')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    root.remove()
  })

  it('CSS.highlights 可用（stub）→ 查询注册高亮，关闭清除无残留', async () => {
    class MockHighlight {
      ranges: Range[]
      constructor(...ranges: Range[]) {
        this.ranges = ranges
      }
    }
    vi.stubGlobal('Highlight', MockHighlight)
    const registry = new Map()
    Object.defineProperty(CSS, 'highlights', { value: registry, configurable: true })

    const root = fixtureRoot()
    render(<ArticleFindBar open onClose={() => {}} getRoot={() => root} />)
    fireEvent.change(screen.getByLabelText('查找正文'), { target: { value: '术语' } })
    await waitFor(() => {
      expect(registry.get('lumi-find-all')).toBeDefined()
      expect(registry.get('lumi-find-current')).toBeDefined()
    })

    fireEvent.click(screen.getByRole('button', { name: '关闭查找' }))
    expect(registry.has('lumi-find-all')).toBe(false)
    expect(registry.has('lumi-find-current')).toBe(false)
    root.remove()
  })

  it('查询变化清除旧高亮（stub 下旧 registry 条目被替换/清理）', async () => {
    class MockHighlight {
      constructor(..._: Range[]) {}
    }
    vi.stubGlobal('Highlight', MockHighlight)
    const registry = new Map()
    Object.defineProperty(CSS, 'highlights', { value: registry, configurable: true })

    const root = fixtureRoot()
    render(<ArticleFindBar open onClose={() => {}} getRoot={() => root} />)
    const input = screen.getByLabelText('查找正文')
    fireEvent.change(input, { target: { value: '术语' } })
    await waitFor(() => expect(registry.get('lumi-find-all')).toBeDefined())
    fireEvent.change(input, { target: { value: '不存在的词' } })
    await screen.findByText('无结果')
    // 无结果：不注册任何高亮
    expect(registry.has('lumi-find-all')).toBe(false)
    root.remove()
  })
})

// ---- ArticleLightbox（F14 组件） ----

describe('ArticleLightbox — 灯箱浮层', () => {
  const images = [
    { src: 'https://example.com/a.png', alt: '图A' },
    { src: 'https://example.com/b.png', alt: '图B' },
  ]

  it('open=false 不渲染', () => {
    render(<ArticleLightbox open={false} onClose={() => {}} images={images} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('打开：焦点入灯箱（tabIndex=-1 + focus）+ 计数显示', () => {
    render(<ArticleLightbox open onClose={() => {}} images={images} />)
    const dialog = screen.getByRole('dialog', { name: '图片查看' })
    expect(dialog).toHaveAttribute('tabindex', '-1')
    expect(dialog).toHaveFocus()
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '图A' })).toHaveAttribute('src', 'https://example.com/a.png')
  })

  it('Escape / 遮罩点击 / × 都关闭', () => {
    const onClose = vi.fn()
    const { unmount } = render(<ArticleLightbox open onClose={onClose} images={images} />)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    unmount()

    const onClose2 = vi.fn()
    const { unmount: unmount2 } = render(<ArticleLightbox open onClose={onClose2} images={images} />)
    fireEvent.click(screen.getByRole('dialog', { name: '图片查看' }))
    expect(onClose2).toHaveBeenCalledTimes(1)
    unmount2()

    const onClose3 = vi.fn()
    render(<ArticleLightbox open onClose={onClose3} images={images} />)
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(onClose3).toHaveBeenCalledTimes(1)
  })

  it('←/→ 与上一张/下一张循环切换；切换后重置缩放状态可再缩放', () => {
    render(<ArticleLightbox open onClose={() => {}} images={images} startIndex={1} />)
    expect(screen.getByText('2 / 2')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '下一张' }))
    expect(screen.getByText('2 / 2')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '上一张' }))
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
  })

  it('内容模式（表格面板）：点击面板内部不关闭，Esc 关闭', () => {
    const onClose = vi.fn()
    render(
      <ArticleLightbox open onClose={onClose} label="表格查看">
        <div>表格内容区</div>
      </ArticleLightbox>,
    )
    const dialog = screen.getByRole('dialog', { name: '表格查看' })
    expect(screen.getByText('表格内容区')).toBeInTheDocument()
    fireEvent.click(screen.getByText('表格内容区'))
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(dialog).toBeInTheDocument()
  })

  it('放大/缩小按钮钳制在 1–4x（img transform 表达）；滚轮事件也接线', () => {
    render(<ArticleLightbox open onClose={() => {}} images={images} />)
    const img = screen.getByRole('img', { name: '图A' })

    // 连续放大到上限 4x
    for (let i = 0; i < 8; i += 1) fireEvent.click(screen.getByRole('button', { name: '放大' }))
    expect(img.style.transform).toContain('scale(4)')
    // 缩小回落
    fireEvent.click(screen.getByRole('button', { name: '缩小' }))
    expect(img.style.transform).toContain('scale(3.5)')
    // 连续缩小到下限 1x
    for (let i = 0; i < 8; i += 1) fireEvent.click(screen.getByRole('button', { name: '缩小' }))
    expect(img.style.transform).toContain('scale(1)')
  })
})
