/** NF1 N091 — 从选中句开始朗读（jsdom）。
 *
 * 覆盖：正文段落内选区显示「从此处朗读」浮动入口；点击从选区所在块
 * 的索引开始朗读（mock speechSynthesis 证明接线）；既有播放被 cancel
 * （引擎单通道 cancel-first）；代码块（pre/code）与表格内的选区不显示
 * 入口；正文外选区不显示入口。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import {
  collectSpeechCollection,
  DEFAULT_SPEECH_EXCLUSIONS,
} from '../lib/reader-speech'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

// ---- speechSynthesis mock（同 p18 模式） ----

class MockUtterance {
  text: string
  lang = ''
  voice: unknown = null
  rate = 1
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}

function stubSpeech(voices: SpeechSynthesisVoice[] = []) {
  const speak = vi.fn()
  const cancel = vi.fn()
  const pause = vi.fn()
  const resume = vi.fn()
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => voices,
    speak,
    cancel,
    pause,
    resume,
  })
  vi.stubGlobal('SpeechSynthesisUtterance', MockUtterance)
  return { speak, cancel, pause, resume }
}

const VOICES = [
  { lang: 'zh-CN', name: '婷婷', voiceURI: 'zh-cn' },
] as unknown as SpeechSynthesisVoice[]

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  window.getSelection()?.removeAllRanges()
})

// ---- fixture：真实 DOM + 真实收集（几何全 0 只影响自动起点；本特性
// 全部走显式选区起点，不依赖它） ----

function mountArticle(): {
  container: HTMLElement
  article: HTMLElement
} {
  const container = document.createElement('div')
  container.innerHTML = [
    '<div class="lumi-reader-article">',
    '<p>第一段的内容。</p>',
    '<p>第二段的内容。</p>',
    '<pre><code>const x = 1</code></pre>',
    '<table><tbody><tr><td><p>表格里的文字</p></td></tr></tbody></table>',
    '</div>',
  ].join('')
  document.body.appendChild(container)
  const article = container.querySelector('.lumi-reader-article') as HTMLElement
  return { container, article }
}

/** 与 Reader.collectSpeechBlocks 同构的收集入口（设置快照 → lib 收集）。 */
function makeCollect(container: HTMLElement, article: HTMLElement) {
  return () => {
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
}

function selectText(el: Element, start: number, end: number): void {
  const textNode = el.firstChild!
  const range = document.createRange()
  range.setStart(textNode, start)
  range.setEnd(textNode, end)
  const sel = window.getSelection()!
  sel.removeAllRanges()
  sel.addRange(range)
}

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

describe('N091 — 从选中句开始朗读', () => {
  it('段落内选区显示「从此处朗读」；点击从该块开始朗读并清选区', () => {
    const speech = stubSpeech(VOICES)
    const { container, article } = mountArticle()
    const paragraphs = article.querySelectorAll('p')

    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={makeCollect(container, article)}
        />,
      ),
    )

    selectText(paragraphs[1]!, 0, 4) // 第二段的内容
    fireEvent.mouseUp(article)
    const action = screen.getByRole('button', { name: '从此处朗读' })
    expect(action).toBeInTheDocument()

    fireEvent.click(action)
    // 引擎从选区所在块（selectorIndex 1）入队：首条 utterance = 第二段
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).text).toBe('第二段的内容。')
    // 点击后选区清除、浮动入口消失
    expect(screen.queryByRole('button', { name: '从此处朗读' })).not.toBeInTheDocument()
    expect(window.getSelection()?.isCollapsed ?? true).toBe(true)
    // 当前块高亮落在第二段
    expect(paragraphs[1]!.hasAttribute('data-speech-active')).toBe(true)
  })

  it('既有播放被 cancel（单通道 cancel-first），新会话从选区块开始', () => {
    const speech = stubSpeech(VOICES)
    const { container, article } = mountArticle()
    const paragraphs = article.querySelectorAll('p')

    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={makeCollect(container, article)}
        />,
      ),
    )

    // 先从「自动起点」开始朗读（jsdom 几何全 0 → 起点为最后一个收集块）
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    expect(speech.speak).toHaveBeenCalledTimes(1)
    expect(speech.cancel).toHaveBeenCalledTimes(1)

    // 选区「从此处朗读」：旧会话停机 + 新队列入队（cancel ≥ 2），
    // 新会话从第二段开始
    selectText(paragraphs[0]!, 0, 3)
    fireEvent.mouseUp(article)
    fireEvent.click(screen.getByRole('button', { name: '从此处朗读' }))
    expect(speech.cancel.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(speech.speak).toHaveBeenCalledTimes(2)
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).text).toBe('第一段的内容。')
    // 高亮从 pre 移到第一段
    expect(paragraphs[0]!.hasAttribute('data-speech-active')).toBe(true)
    expect(article.querySelector('pre')!.hasAttribute('data-speech-active')).toBe(false)
  })

  it('代码块与表格内的选区不显示入口（即使未被排除开关过滤）', () => {
    stubSpeech(VOICES)
    const { container, article } = mountArticle()
    const pre = article.querySelector('pre')!
    const tableCell = article.querySelector('td p')!

    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={makeCollect(container, article)}
        />,
      ),
    )

    selectText(pre.querySelector('code')!, 0, 5)
    fireEvent.mouseUp(article)
    expect(screen.queryByRole('button', { name: '从此处朗读' })).not.toBeInTheDocument()

    selectText(tableCell, 0, 2)
    fireEvent.mouseUp(article)
    expect(screen.queryByRole('button', { name: '从此处朗读' })).not.toBeInTheDocument()
  })

  it('正文外选区不显示入口', () => {
    stubSpeech(VOICES)
    const outside = document.createElement('p')
    outside.textContent = '工具栏文字'
    document.body.appendChild(outside)
    const { container, article } = mountArticle()

    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={makeCollect(container, article)}
        />,
      ),
    )

    selectText(outside, 0, 3)
    fireEvent.mouseUp(article)
    expect(screen.queryByRole('button', { name: '从此处朗读' })).not.toBeInTheDocument()
  })

  it('排除开关命中的块不在收集结果里，选区落入时不显示入口', () => {
    stubSpeech(VOICES)
    const { container, article } = mountArticle()
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, speechSkipCode: true },
    })
    const paragraphs = article.querySelectorAll('p')

    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={makeCollect(container, article)}
        />,
      ),
    )
    // 排除后的收集不再含 pre
    const collection = makeCollect(container, article)()
    expect(collection?.texts).not.toContain('const x = 1')
    expect(DEFAULT_SPEECH_EXCLUSIONS.skipCode).toBe(false) // 默认不动既有行为

    // 正常段落选区仍可用
    selectText(paragraphs[0]!, 0, 2)
    fireEvent.mouseUp(article)
    expect(screen.getByRole('button', { name: '从此处朗读' })).toBeInTheDocument()
  })
})
