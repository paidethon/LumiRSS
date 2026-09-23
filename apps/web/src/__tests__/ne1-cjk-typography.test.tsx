/** N055+N056 中文排版细化测试 — 首行缩进按块类型（列表/引用）开关、
 * 避头尾（line-break: strict）开关：设置归一化/回退、html data 标记、
 * 恢复默认覆盖、CSS-only（正文 DOM 零改动）、预览样例渲染。 */

import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  applyReaderTypography,
  DEFAULT_APP_SETTINGS,
  normalizeSettings,
  PORTABLE_KEYS,
  useAppSettings,
  type AppSettings,
} from '../store/app-settings'
import { ReaderSampleArticle } from '../components/settings/reader/ReadingPreviewPane'

function setSettings(patch: Partial<AppSettings>) {
  useAppSettings.setState({ settings: { ...useAppSettings.getState().settings, ...patch } })
}

beforeEach(() => {
  localStorage.clear()
  setSettings({
    readerIndentLists: false,
    readerIndentQuotes: false,
    readerLineBreakStrict: false,
    readerReadingMode: 'scroll',
  })
})

afterEach(() => {
  localStorage.clear()
})

describe('N055 首行缩进按块类型', () => {
  it('新设置不在 PORTABLE_KEYS（设备本地，不参与服务端同步）', () => {
    for (const key of [
      'readerIndentLists',
      'readerIndentQuotes',
      'readerLineBreakStrict',
      'readerReadingMode',
      'readerTapZoneAxis',
      'readerTapZoneSize',
    ]) {
      expect(PORTABLE_KEYS).not.toContain(key)
    }
  })

  it('默认关：html data 标记为 false（段落缩进之外零改动）', () => {
    applyReaderTypography(useAppSettings.getState().settings)
    expect(document.documentElement.dataset.readerIndentLists).toBe('false')
    expect(document.documentElement.dataset.readerIndentQuotes).toBe('false')
    expect(document.documentElement.dataset.readerLineBreakStrict).toBe('false')
  })

  it('开关切换 → data 标记跟随（CSS 规则按标记命中 li/blockquote）', () => {
    setSettings({ readerIndentLists: true, readerIndentQuotes: true })
    applyReaderTypography(useAppSettings.getState().settings)
    expect(document.documentElement.dataset.readerIndentLists).toBe('true')
    expect(document.documentElement.dataset.readerIndentQuotes).toBe('true')
    // 标题/代码无对应标记——缩进永不作用于标题与代码
    expect(document.documentElement.dataset.readerIndentHeadings).toBeUndefined()
    expect(document.documentElement.dataset.readerIndentCode).toBeUndefined()
  })

  it('归一化：非法值回退默认', () => {
    const next = normalizeSettings({
      readerIndentLists: 'yes',
      readerIndentQuotes: 1,
      readerLineBreakStrict: 'on',
    })
    expect(next.readerIndentLists).toBe(false)
    expect(next.readerIndentQuotes).toBe(false)
    expect(next.readerLineBreakStrict).toBe(false)
  })

  it('「恢复默认阅读设置」覆盖缩进扩展与避头尾', () => {
    setSettings({ readerIndentLists: true, readerIndentQuotes: true, readerLineBreakStrict: true })
    useAppSettings.getState().resetReader()
    const settings = useAppSettings.getState().settings
    expect(settings.readerIndentLists).toBe(false)
    expect(settings.readerIndentQuotes).toBe(false)
    expect(settings.readerLineBreakStrict).toBe(false)
  })
})

describe('N056 避头尾（line-break: strict）', () => {
  it('开关独立于标点悬挂：两者互不影响', () => {
    setSettings({ readerLineBreakStrict: true, readerHangingPunctuation: false })
    applyReaderTypography(useAppSettings.getState().settings)
    expect(document.documentElement.dataset.readerLineBreakStrict).toBe('true')
    expect(document.documentElement.dataset.readerHangingPunctuation).toBe('false')
    setSettings({ readerLineBreakStrict: false, readerHangingPunctuation: true })
    applyReaderTypography(useAppSettings.getState().settings)
    expect(document.documentElement.dataset.readerLineBreakStrict).toBe('false')
    expect(document.documentElement.dataset.readerHangingPunctuation).toBe('true')
  })

  it('CSS-only：开关切换前后正文 DOM 零改动（复制文本不变）', () => {
    const host = document.createElement('div')
    host.className = 'article-content'
    host.innerHTML = '<p>中文正文 Mixed text 3.14、“引号”与（括号）。</p>'
    document.body.appendChild(host)
    const before = host.innerHTML

    setSettings({ readerLineBreakStrict: true })
    applyReaderTypography(useAppSettings.getState().settings)
    expect(host.innerHTML).toBe(before)
    expect(host.textContent).toBe(
      '中文正文 Mixed text 3.14、“引号”与（括号）。',
    )

    setSettings({ readerLineBreakStrict: false })
    applyReaderTypography(useAppSettings.getState().settings)
    expect(host.innerHTML).toBe(before)
    host.remove()
  })
})

describe('N052 阅读模式设置（分页）', () => {
  it('迁移：旧 readerPagedMode=true 且未显式设置阅读模式 → 分页；显式值优先', () => {
    expect(normalizeSettings({ readerPagedMode: true }).readerReadingMode).toBe('paged')
    expect(
      normalizeSettings({ readerPagedMode: true, readerReadingMode: 'scroll' })
        .readerReadingMode,
    ).toBe('scroll')
    expect(normalizeSettings({}).readerReadingMode).toBe('scroll')
    expect(normalizeSettings({ readerReadingMode: 'lane' }).readerReadingMode).toBe('scroll')
  })

  it('点按翻页区设置归一化：非法值回退默认（左右 / 小）', () => {
    const next = normalizeSettings({ readerTapZoneAxis: 'diagonal', readerTapZoneSize: 'huge' })
    expect(next.readerTapZoneAxis).toBe(DEFAULT_APP_SETTINGS.readerTapZoneAxis)
    expect(next.readerTapZoneSize).toBe(DEFAULT_APP_SETTINGS.readerTapZoneSize)
  })
})

describe('阅读预览样例（ReadingPreviewPane）', () => {
  it('样例含列表 + 引用 + 中英混排段落（缩进/避头尾观察点）', () => {
    render(<ReaderSampleArticle />)
    expect(screen.getByText('列表项一：检查项目符号与行距')).toBeInTheDocument()
    expect(screen.getByText(/开启「列表缩进」后/)).toBeInTheDocument()
    expect(screen.getByText(/引用块：检查左边框/)).toBeInTheDocument()
    expect(screen.getByText(/中英混排样例 Mixed Text/)).toBeInTheDocument()
  })

  it('切换缩进/避头尾设置后，样例文章 DOM 结构不变（样式经全局 data 标记生效）', () => {
    render(<ReaderSampleArticle />)
    const article = document.querySelector('[data-reading-preview-article]') as HTMLElement
    const before = article.innerHTML
    setSettings({ readerIndentLists: true, readerIndentQuotes: true, readerLineBreakStrict: true })
    // 设置变化只翻全局 data 标记（CSS-only），样例与正文的 DOM 不动
    applyReaderTypography(useAppSettings.getState().settings)
    expect(document.documentElement.dataset.readerIndentLists).toBe('true')
    expect(article.innerHTML).toBe(before)
  })
})
