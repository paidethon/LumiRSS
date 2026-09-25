/** R5 批4 测试 — F065 跟随窗口宽度 / F066 排版一键重置 / F067 字号行距
 * 联动预设 / F075 剩余阅读时间 / F079 fixed 干扰媒体清理 / F077 原文
 * 分屏沙箱 / F078 重抓原文并排对比 / F061 分页迷你地图。 */

import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRef } from 'react'
import ArticleContent from '../components/ArticleContent'
import ReaderRemainingTime from '../components/ReaderRemainingTime'
import ReaderSplitOriginal from '../components/ReaderSplitOriginal'
import { ReaderPager } from '../components/ReaderPager'
import { ReaderTypographyControls } from '../components/settings/reader/ReaderTypographyControls'
import type { EntryDetail } from '../api/types'
import {
  DEFAULT_APP_SETTINGS,
  SETTINGS_STORAGE_KEY,
  normalizeSettings,
  readerTypographyVars,
  useAppSettings,
} from '../store/app-settings'
import { matchReaderSizePreset } from '../lib/reader-style'
import {
  DEFAULT_READING_SPEED,
  estimateRemainingMinutes,
} from '../lib/reading-time'
import { renderArticleHtml } from '../lib/article-pipeline'
import { clearArticleHtmlCaches } from '../lib/article-pipeline'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return { queryClient, ui: <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider> }
}

beforeEach(() => {
  localStorage.clear()
  clearArticleHtmlCaches()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.parentElement?.remove())
})

// ---- F065：正文宽度跟随窗口 ----

describe('F065 — 正文宽度「跟随窗口」档位', () => {
  it('默认固定 px；模式非法回退；百分比钳制 50–100', () => {
    const s = normalizeSettings({})
    expect(s.readerContentWidthMode).toBe('fixed')
    expect(s.readerContentWidthViewport).toBe(92)
    expect(normalizeSettings({ readerContentWidthMode: 'fluid' }).readerContentWidthMode).toBe('fixed')
    expect(normalizeSettings({ readerContentWidthViewport: 200 }).readerContentWidthViewport).toBe(100)
    expect(normalizeSettings({ readerContentWidthViewport: 10 }).readerContentWidthViewport).toBe(50)
  })

  it('CSS 变量：固定档输出 px；跟随窗口档输出 min(pct vw, 100%)', () => {
    const fixed = readerTypographyVars({ ...DEFAULT_APP_SETTINGS, readerContentWidth: 760 })
    expect(fixed['--lumi-reader-content-width']).toBe('760px')
    const viewport = readerTypographyVars({
      ...DEFAULT_APP_SETTINGS,
      readerContentWidthMode: 'viewport',
      readerContentWidthViewport: 92,
    })
    expect(viewport['--lumi-reader-content-width']).toBe('min(92vw, 100%)')
  })

  it('Aa 面板宽度模式切换 + 窗口占比滑杆直连 store', () => {
    render(withQueryClient(<ReaderTypographyControls />).ui)
    fireEvent.change(screen.getByLabelText('正文宽度模式'), { target: { value: 'viewport' } })
    expect(useAppSettings.getState().settings.readerContentWidthMode).toBe('viewport')
    fireEvent.change(screen.getByLabelText('窗口宽度占比'), { target: { value: '70' } })
    expect(useAppSettings.getState().settings.readerContentWidthViewport).toBe(70)
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerContentWidthMode).toBe('viewport')
    // 切回固定档 → px 滑杆回归
    fireEvent.change(screen.getByLabelText('正文宽度模式'), { target: { value: 'fixed' } })
    expect(screen.getByLabelText('正文宽度')).toBeInTheDocument()
  })
})

// ---- F066：阅读排版一键重置 ----

describe('F066 — 排版一键重置（仅排版字段）', () => {
  it('resetReaderTypography 还原排版键、保留非排版阅读设置', () => {
    const { update, resetReaderTypography } = useAppSettings.getState()
    update({
      // 排版字段（应被还原）
      readerFontSize: 24,
      readerLineHeight: 2.2,
      readerFontWeight: 700,
      readerImageMaxWidth: '60%',
      readerContentWidthMode: 'viewport',
      readerJustify: true,
      readerTextIndent: '2em',
      readerCodeFontSize: 'l',
      // 非排版阅读设置（应保留）
      readerBackground: 'sepia',
      readerCodeHighlight: 'off',
      readerChineseConversion: 's2t',
      readLaterSort: 'oldest',
      readerStripFixedMedia: false,
    })
    resetReaderTypography()
    const s = useAppSettings.getState().settings
    expect(s.readerFontSize).toBe(DEFAULT_APP_SETTINGS.readerFontSize)
    expect(s.readerLineHeight).toBe(DEFAULT_APP_SETTINGS.readerLineHeight)
    expect(s.readerFontWeight).toBe(DEFAULT_APP_SETTINGS.readerFontWeight)
    expect(s.readerImageMaxWidth).toBe('100%')
    expect(s.readerContentWidthMode).toBe('fixed')
    expect(s.readerJustify).toBe(false)
    expect(s.readerTextIndent).toBe('off')
    expect(s.readerCodeFontSize).toBe('m')
    // 非排版键不动
    expect(s.readerBackground).toBe('sepia')
    expect(s.readerCodeHighlight).toBe('off')
    expect(s.readerChineseConversion).toBe('s2t')
    expect(s.readLaterSort).toBe('oldest')
    expect(s.readerStripFixedMedia).toBe(false)
  })

  it('排版设置区按钮触发重置', () => {
    useAppSettings.getState().update({ readerFontSize: 26 })
    render(withQueryClient(<ReaderTypographyControls />).ui)
    fireEvent.click(screen.getByRole('button', { name: '恢复默认排版' }))
    expect(useAppSettings.getState().settings.readerFontSize).toBe(
      DEFAULT_APP_SETTINGS.readerFontSize,
    )
  })
})

// ---- F067：字号+行高联动预设 ----

describe('F067 — 字号+行高联动预设', () => {
  it('三档预设值匹配（小 15/1.7，中 17/1.85，大 20/2.05）；偏离返回 null', () => {
    expect(matchReaderSizePreset(17, 1.85)?.id).toBe('medium')
    expect(matchReaderSizePreset(15, 1.7)?.id).toBe('small')
    expect(matchReaderSizePreset(20, 2.05)?.id).toBe('large')
    expect(matchReaderSizePreset(18, 1.9)).toBeNull()
  })

  it('一键同时设置字号与行高；滑杆微调后预设去高亮', () => {
    render(withQueryClient(<ReaderTypographyControls />).ui)
    fireEvent.click(screen.getByTestId('size-preset-large'))
    const s = useAppSettings.getState().settings
    expect(s.readerFontSize).toBe(20)
    expect(s.readerLineHeight).toBe(2.05)
    expect(screen.getByTestId('size-preset-large')).toHaveAttribute('aria-pressed', 'true')
    // 单项微调 → 非预设值，高亮消失
    fireEvent.change(screen.getByLabelText('字号'), { target: { value: '19' } })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(19)
    expect(screen.getByTestId('size-preset-large')).toHaveAttribute('aria-pressed', 'false')
  })
})

// ---- F075：剩余阅读时间 ----

describe('F075 — 剩余阅读时间（默认速度 + 校准接口）', () => {
  const longText = '字'.repeat(3000) // 3000 CJK 字 → 默认 300字/分 = 10 分钟

  it('estimateRemainingMinutes：默认速度按比例折算；进度 1 → 0；非法进度按 0', () => {
    expect(estimateRemainingMinutes({ text: longText, ratio: 0 })).toBe(10)
    expect(estimateRemainingMinutes({ text: longText, ratio: 0.5 })).toBe(5)
    expect(estimateRemainingMinutes({ text: longText, ratio: 1 })).toBe(0)
    expect(estimateRemainingMinutes({ text: longText, ratio: Number.NaN })).toBe(10)
    // 不足 1 分钟余量向上取整
    expect(estimateRemainingMinutes({ text: longText, ratio: 0.99 })).toBe(1)
  })

  it('自定义速度可注入（F051 校准速度接口）', () => {
    expect(
      estimateRemainingMinutes({
        text: longText,
        ratio: 0.4,
        speed: { cjkPerMinute: 600, latinWordsPerMinute: 400 },
      }),
    ).toBe(3)
    expect(DEFAULT_READING_SPEED.cjkPerMinute).toBe(300)
  })

  it('进度条旁显示剩余时间 chip；未滚动/关闭时不渲染', () => {
    const container = document.createElement('div')
    Object.defineProperty(container, 'scrollHeight', { value: 4000, configurable: true })
    Object.defineProperty(container, 'clientHeight', { value: 600, configurable: true })
    Object.defineProperty(container, 'scrollTop', { value: 0, writable: true, configurable: true })
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', () => {})
    const { rerender } = render(
      <ReaderRemainingTime getContainer={() => container} text={longText} enabled />,
    )
    expect(screen.queryByLabelText('剩余阅读时间')).toBeNull()
    // 滚动到 50%
    container.scrollTop = 1700
    fireEvent.scroll(container)
    const chip = document.querySelector('[data-lumi-remaining-time]')
    expect(chip).not.toBeNull()
    expect(chip!.textContent).toBe('剩余约 5 分钟')
    // 关闭开关 → 不渲染
    rerender(
      <ReaderRemainingTime getContainer={() => container} text={longText} enabled={false} />,
    )
    expect(document.querySelector('[data-lumi-remaining-time]')).toBeNull()
  })
})

// ---- F079：fixed/sticky 干扰媒体清理 ----

describe('F079 — article pipeline 清理 fixed/sticky 非内容元素', () => {
  const OPTS = { conversion: 'off', bionic: false, codeTheme: null } as const

  it('摘除 inline position:fixed/sticky 的悬浮装饰（无块级内容）', async () => {
    const raw =
      '<div style="position:fixed;top:0" class="sharebar"><span>分享到</span><img src="https://x/i.png"></div>' +
      '<aside style="position:sticky;top:8px">广告条</aside>' +
      '<p>正文段落</p>'
    const out = await renderArticleHtml(raw, { ...OPTS, stripFixedMedia: true })
    expect(out).not.toContain('sharebar')
    expect(out).not.toContain('广告条')
    expect(out).toContain('<p>正文段落</p>')
  })

  it('保守保留：含块级正文内容的容器与非 fixed/sticky 元素', async () => {
    const raw =
      '<div style="position:sticky;top:0"><p>被 sticky 容器包裹的正文</p></div>' +
      '<div style="position:relative">相对定位不清理</div>'
    const out = await renderArticleHtml(raw, { ...OPTS, stripFixedMedia: true })
    expect(out).toContain('被 sticky 容器包裹的正文')
    expect(out).toContain('相对定位不清理')
  })

  it('开关关闭（默认关闭该清理路径时）与 DOMPurify 边界不变式', async () => {
    const raw = '<div style="position:fixed"><span>share</span></div><p>ok</p>'
    const out = await renderArticleHtml(raw, OPTS)
    expect(out).toContain('share')
    // 开启后 transform 只删除元素，不产生新标记；恶意内容仍被清洗
    const out2 = await renderArticleHtml(
      '<div style="position:fixed"><span>x</span></div><img src=y onerror="alert(1)">',
      { ...OPTS, stripFixedMedia: true },
    )
    expect(out2).not.toMatch(/onerror/i)
    expect(out2).not.toMatch(/position\s*:\s*fixed/i)
  })
})

// ---- F077：原文分屏（沙箱 iframe） ----

describe('F077 — 正文/原网页分屏', () => {
  it('iframe 严格沙箱：sandbox 为空（无脚本/无 same-origin）+ no-referrer', () => {
    render(<ReaderSplitOriginal url="https://example.com/a" onClose={() => {}} />)
    const frame = document.querySelector('iframe[data-lumi-split-frame]') as HTMLIFrameElement
    expect(frame).not.toBeNull()
    expect(frame.getAttribute('sandbox')).toBe('')
    expect(frame.getAttribute('referrerpolicy')).toBe('no-referrer')
    expect(frame.src).toBe('https://example.com/a')
  })

  it('原文不可得：诚实提示且不渲染 iframe', () => {
    render(<ReaderSplitOriginal url={null} onClose={() => {}} />)
    expect(document.querySelector('iframe')).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('没有可用的原文链接')
  })
})

// ---- F078：重抓原文并排对比 ----

describe('F078 — 重新抓取原文快照并排对比', () => {
  function detailFixture(): EntryDetail {
    return {
      entryRef: 'e1.a',
      title: '文章 A',
      feedTitle: '示例源',
      author: '作者甲',
      url: 'https://example.com/a',
      publishedAt: '2026-08-28T10:00:00Z',
      read: false,
      starred: false,
      contentText: '纯文本正文 A',
      contentHtml: '<p>富文本正文 <strong>A</strong></p>',
    }
  }

  function jsonResponse(body: unknown): Response {
    return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
  }

  it('入口 → 并排展示当前正文与重抓原文（均经 DOMPurify）', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/entries/e1.a?extractOnce=true') {
        return Promise.resolve(jsonResponse({ contentHtml: '<p>重抓的原文段落</p>', extractionFailed: false }))
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { ui } = withQueryClient(<ArticleContent detail={detailFixture()} />)
    render(ui)
    expect(await screen.findByText('A', { selector: 'strong' })).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('extract-compare-open'))
    const refetched = await screen.findByText('重抓的原文段落')
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('extractOnce=true'))).toBe(true)
    expect(refetched.closest('[data-testid="extract-compare-refetch"]')).not.toBeNull()
    const currentPane = document.querySelector('[data-testid="extract-compare-current"]')
    expect(currentPane?.textContent).toContain('富文本正文')
  })

  it('抓取失败诚实提示（不假装成功）', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/v1/entries/e1.a?extractOnce=true') {
        return Promise.resolve(jsonResponse({ contentHtml: null, extractionFailed: true }))
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { ui } = withQueryClient(<ArticleContent detail={detailFixture()} />)
    render(ui)
    fireEvent.click(await screen.findByTestId('extract-compare-open'))
    await waitFor(() => {
      expect(screen.getByText('原文抓取失败，无法对比。')).toBeInTheDocument()
    })
  })
})

// ---- F061：分页迷你地图 ----

describe('F061 — 分页迷你地图（跳页条）', () => {
  function setupPager(scrollWidth: number) {
    const container = document.createElement('div')
    const article = document.createElement('article')
    article.className = 'lumi-reader-article'
    article.innerHTML = '<div class="article-content"><p>第一段</p><p>第二段</p></div>'
    container.appendChild(article)
    document.body.appendChild(container)
    Object.defineProperty(container, 'clientWidth', { value: 800, configurable: true })
    Object.defineProperty(container, 'clientHeight', { value: 600, configurable: true })
    Object.defineProperty(article, 'scrollWidth', { value: scrollWidth, configurable: true })
    vi.stubGlobal(
      'getComputedStyle',
      () => ({ paddingLeft: '20px', getPropertyValue: () => '' }) as unknown as CSSStyleDeclaration,
    )
    const containerRef = createRef<HTMLDivElement>()
    const articleRef = createRef<HTMLElement>()
    Object.defineProperty(containerRef, 'current', { value: container })
    Object.defineProperty(articleRef, 'current', { value: article })
    render(
      <ReaderPager
        enabled
        containerRef={containerRef as React.RefObject<HTMLDivElement>}
        articleRef={articleRef as React.RefObject<HTMLElement>}
        entryRef={null}
      />,
    )
    return { container, article }
  }

  it('跳页条存在且反映当前页/总页；拖动/点击跳页并施加位移', async () => {
    const { article } = setupPager(2400) // 3 页
    const map = await screen.findByLabelText('跳页（当前页 / 总页）')
    expect(map).toHaveAttribute('max', '3')
    expect(map).toHaveAttribute('value', '1')
    expect(article.style.transform).toBe('translateX(-0px)')

    // 拖到第 3 页
    fireEvent.change(map, { target: { value: '3' } })
    await waitFor(() => expect(screen.getByText('3 / 3')).toBeInTheDocument())
    expect(article.style.transform).toBe('translateX(-1600px)')
    expect(map).toHaveAttribute('value', '3')
  })
})
