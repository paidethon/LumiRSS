/** NF1 N094 — 听读内容排除（jsdom）。
 *
 * 覆盖：五个开关各自把对应块类型从收集结果中排除（代码块 / 表格 / 脚注 /
 * 图片说明 / 纯链接段落）；被排除内容在文章 DOM 中原样保留；朗读设置
 * 面板的「试听文本」预览反映排除后的剩余内容；开关写入设备本地设置并
 * 持久化（重载归一化后保留）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import {
  collectSpeechCollection,
  DEFAULT_SPEECH_EXCLUSIONS,
  type SpeechExclusions,
} from '../lib/reader-speech'
import {
  DEFAULT_APP_SETTINGS,
  loadSettings,
  useAppSettings,
} from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const CODE_TEXT = 'const framework = "lumi"'
const TABLE_TEXT = '表格里的段落'
const FOOTNOTE_TEXT = '脚注一：出处说明'
const CAPTION_TEXT = '图片说明文字'
const LINK_TEXT = '阅读原文'
const PARA_A = '普通段落甲'
const PARA_B = '普通段落乙'

function mountArticle(): { container: HTMLElement; article: HTMLElement } {
  const container = document.createElement('div')
  container.innerHTML = [
    '<div class="lumi-reader-article">',
    `<p>${PARA_A}</p>`,
    `<pre><code>${CODE_TEXT}</code></pre>`,
    `<table><tbody><tr><td><p>${TABLE_TEXT}</p></td></tr></tbody></table>`,
    `<section class="footnotes"><p>${FOOTNOTE_TEXT}</p></section>`,
    `<figure><figcaption><p>${CAPTION_TEXT}</p></figcaption></figure>`,
    `<p><a href="https://example.com">${LINK_TEXT}</a></p>`,
    `<p>${PARA_B}</p>`,
    '</div>',
  ].join('')
  document.body.appendChild(container)
  const article = container.querySelector('.lumi-reader-article') as HTMLElement
  return { container, article }
}

function collectWith(
  container: HTMLElement,
  article: HTMLElement,
  exclusions: SpeechExclusions,
) {
  return collectSpeechCollection(container, article, { exclusions, lexicon: [] })
}

// speechSynthesis stub：朗读设置面板入口（工具栏 Popover）只在能力可用
// 时渲染（同 p18 模式；本文件不点朗读，仅需能力可用）。beforeEach 里
// 打——afterEach 会 unstub，模块级一次性 stub 在第二个用例起就失效。
beforeEach(() => {
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => [],
    speak: vi.fn(),
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
  })
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  localStorage.clear()
})

describe('N094 — 排除收集（纯函数）', () => {
  it('默认不排除：全部块被收集（既有行为不变）', () => {
    const { container, article } = mountArticle()
    const result = collectWith(container, article, DEFAULT_SPEECH_EXCLUSIONS)
    expect(result).not.toBeNull()
    expect(result!.texts).toEqual([
      PARA_A,
      CODE_TEXT,
      TABLE_TEXT,
      FOOTNOTE_TEXT,
      CAPTION_TEXT,
      LINK_TEXT,
      PARA_B,
    ])
  })

  it('每个开关只排除自己的块类型；全开只剩正文段落', () => {
    const { container, article } = mountArticle()

    const rest = [PARA_A, TABLE_TEXT, FOOTNOTE_TEXT, CAPTION_TEXT, LINK_TEXT, PARA_B]
    expect(
      collectWith(container, article, { ...DEFAULT_SPEECH_EXCLUSIONS, skipCode: true })!.texts,
    ).toEqual(rest)
    expect(
      collectWith(container, article, { ...DEFAULT_SPEECH_EXCLUSIONS, skipTables: true })!.texts,
    ).not.toContain(TABLE_TEXT)
    expect(
      collectWith(container, article, { ...DEFAULT_SPEECH_EXCLUSIONS, skipFootnotes: true })!.texts,
    ).not.toContain(FOOTNOTE_TEXT)
    expect(
      collectWith(container, article, { ...DEFAULT_SPEECH_EXCLUSIONS, skipCaptions: true })!.texts,
    ).not.toContain(CAPTION_TEXT)
    // 纯链接段落：只排除该段，正文段落不受影响
    expect(
      collectWith(container, article, { ...DEFAULT_SPEECH_EXCLUSIONS, skipLinkOnly: true })!.texts,
    ).toEqual([PARA_A, CODE_TEXT, TABLE_TEXT, FOOTNOTE_TEXT, CAPTION_TEXT, PARA_B])

    // 全开：只剩正文段落
    expect(
      collectWith(container, article, {
        skipCode: true,
        skipTables: true,
        skipFootnotes: true,
        skipCaptions: true,
        skipLinkOnly: true,
      })!.texts,
    ).toEqual([PARA_A, PARA_B])
  })

  it('被排除内容在文章 DOM 中原样保留（只影响朗读范围）', () => {
    const { container, article } = mountArticle()
    collectWith(container, article, {
      skipCode: true,
      skipTables: true,
      skipFootnotes: true,
      skipCaptions: true,
      skipLinkOnly: true,
    })
    expect(article.textContent).toContain(CODE_TEXT)
    expect(article.textContent).toContain(TABLE_TEXT)
    expect(article.textContent).toContain(FOOTNOTE_TEXT)
    expect(article.textContent).toContain(CAPTION_TEXT)
    expect(article.textContent).toContain(LINK_TEXT)
  })

  it('块 id 对齐 selector 序：排除中间块后块 id 仍能对回同一元素', () => {
    const { container, article } = mountArticle()
    const result = collectWith(container, article, {
      ...DEFAULT_SPEECH_EXCLUSIONS,
      skipCode: true,
    })
    const all = Array.from(
      article.querySelectorAll(
        'p, li, pre, blockquote, h1, h2, h3, h4, h5, h6',
      ),
    )
    for (const block of result!.blocks ?? []) {
      expect(all[block.selectorIndex]).toBe(block.element)
    }
  })
})

// ---- 面板：试听文本 + 开关持久化 ----

function detailFixture(over: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: '<p>正文</p>',
    ...over,
  }
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('N094 — 试听文本与持久化', () => {
  it('试听文本反映排除后的剩余内容；开关写回设置并持久化', () => {
    const { container, article } = mountArticle()
    const collect = () => {
      const s = useAppSettings.getState().settings
      return collectSpeechCollection(container, article, {
        exclusions: {
          skipCode: s.speechSkipCode,
          skipTables: s.speechSkipTables,
          skipFootnotes: s.speechSkipFootnotes,
          skipCaptions: s.speechSkipCaptions,
          skipLinkOnly: s.speechSkipLinkOnly,
        },
        lexicon: s.speechLexicon,
      })
    }

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    const preview = () =>
      document.querySelector('[data-lumi-speech-preview]')!.textContent ?? ''
    expect(preview()).toContain(CODE_TEXT)
    expect(preview()).toContain(PARA_B)

    // 打开「跳过代码块」→ 试听文本立即去掉代码块，剩余正文仍在
    fireEvent.click(screen.getByRole('switch', { name: '朗读跳过代码块' }))
    expect(useAppSettings.getState().settings.speechSkipCode).toBe(true)
    expect(preview()).not.toContain(CODE_TEXT)
    expect(preview()).toContain(PARA_B)

    // 持久化：写入设备本地 lumirss-settings，重载归一化后保留
    const raw = JSON.parse(
      localStorage.getItem('lumirss-settings') ?? '{}',
    ) as Record<string, unknown>
    expect(raw.speechSkipCode).toBe(true)
    expect(loadSettings(localStorage).speechSkipCode).toBe(true)
  })

  it('全部排除后试听文本诚实显示无内容', () => {
    const { container, article } = mountArticle()
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        speechSkipCode: true,
        speechSkipTables: true,
        speechSkipFootnotes: true,
        speechSkipCaptions: true,
        speechSkipLinkOnly: true,
      },
    })
    // 留下两个正文段落并从收集里排除（用自定义 collect 模拟全排除场景：
    // 排除开关命中的「普通段落」由 skipLinkOnly 类规则之外的路径覆盖——
    // 这里直接用空文本段落验证空收集的诚实降级）
    const collect = () => null
    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    expect(screen.getByText('没有可朗读的正文（或全部被排除）。')).toBeInTheDocument()
    expect(article.textContent).toContain(PARA_A) // 展示不动
    expect(container).toBeTruthy()
  })
})
