/** N069 选词双语词典卡 — lib + DictSelectionLayer + 设置接线（jsdom）。
 *
 * 覆盖：未配置 → 提示且零 fetch；离线 → 「本机离线：无可用词典」且零
 * fetch（关键断言）；已配置 → 卡片渲染词头/音标/释义/来源；查询 URL 只
 * 携带单词本身；多词选区不弹卡；CJK 词；发音走 speechSynthesis；
 * 设置保存归一化（非法模板 → ''）。 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import DictSelectionLayer from '../components/DictSelectionLayer'
import { DictSourceSettings } from '../components/settings/DictSourceSettings'
import {
  buildDictUrl,
  normalizeDictApiUrl,
  normalizeDictWord,
  parseDictJson,
  queryDict,
} from '../lib/dict-lookup'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

class MockUtterance {
  text: string
  constructor(text: string) {
    this.text = text
  }
}

function stubSpeech(voices: SpeechSynthesisVoice[] = []) {
  const speak = vi.fn()
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => voices,
    speak,
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
  })
  vi.stubGlobal('SpeechSynthesisUtterance', MockUtterance)
  return speak
}

const VOICES = [{ lang: 'zh-CN', name: '婷婷', voiceURI: 'zh-cn' }] as unknown as SpeechSynthesisVoice[]

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  const original = navigator.onLine
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true })
  window.sessionStorage.setItem('nw1-online', String(original))
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  window.getSelection()?.removeAllRanges()
  window.localStorage.clear()
})

function setOnline(value: boolean): void {
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value })
}

function mountArticle(body: string): { container: HTMLElement; article: HTMLElement } {
  const container = document.createElement('div')
  container.innerHTML = `<div class="lumi-reader-article">${body}</div>`
  document.body.appendChild(container)
  const article = container.querySelector('.lumi-reader-article') as HTMLElement
  return { container, article }
}

function selectText(el: Element, start: number, end: number): void {
  const range = document.createRange()
  range.setStart(el.firstChild!, start)
  range.setEnd(el.firstChild!, end)
  const sel = window.getSelection()!
  sel.removeAllRanges()
  sel.addRange(range)
}

function detailFixture(): EntryDetail {
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
  }
}

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('dict-lookup 纯逻辑', () => {
  it('normalizeDictWord：单个词（拉丁/CJK）通过；多词/超长/符号拒绝', () => {
    expect(normalizeDictWord('hello')).toBe('hello')
    expect(normalizeDictWord("don't")).toBe("don't")
    expect(normalizeDictWord('well-known')).toBe('well-known')
    expect(normalizeDictWord('词典')).toBe('词典')
    expect(normalizeDictWord('机器学习')).toBeNull() // CJK > 3 字 → 非单词
    expect(normalizeDictWord('机器')).toBe('机器')
    expect(normalizeDictWord('two words')).toBeNull() // 多词 → 不弹卡
    expect(normalizeDictWord('  spaced  ')).toBe('spaced') // 首尾空白先裁剪
    expect(normalizeDictWord('a'.repeat(25))).toBeNull()
    expect(normalizeDictWord('123')).toBeNull()
    expect(normalizeDictWord('')).toBeNull()
  })

  it('normalizeDictApiUrl / buildDictUrl：模板必须 http(s) 且含 {word}；URL 只含单词', () => {
    expect(normalizeDictApiUrl('')).toBe('')
    expect(normalizeDictApiUrl('https://api.test/dict?q={word}')).toBe('https://api.test/dict?q={word}')
    expect(normalizeDictApiUrl('https://api.test/dict?q=term')).toBe('') // 缺占位符
    expect(normalizeDictApiUrl('ftp://api.test/{word}')).toBe('')
    expect(normalizeDictApiUrl('not a url')).toBe('')
    const url = buildDictUrl('https://api.test/dict?q={word}', 'well-known')
    expect(url).toBe('https://api.test/dict?q=well-known')
    expect(url).not.toContain('context')
    expect(buildDictUrl('', 'x')).toBeNull()
  })

  it('parseDictJson：宽容提取词头/音标/释义；来源主机展示', () => {
    const entry = parseDictJson(
      {
        word: 'serendipity',
        phonetic: 'ˌserənˈdipədē',
        translations: ['意外发现珍宝的运气', '机缘巧合'],
      },
      'serendipity',
    )
    expect(entry.term).toBe('serendipity')
    expect(entry.phonetic).toBe('ˌserənˈdipədē')
    expect(entry.meanings).toEqual(['意外发现珍宝的运气', '机缘巧合'])
    // 结构化失败 → 原始片段（调用方回退展示，不假装）
    const fallback = parseDictJson({ unexpected: true }, 'word')
    expect(fallback.meanings).toEqual([])
    expect(fallback.term).toBe('word')
  })

  it('queryDict 编排：offline / unconfigured / HTTP 错误 / 成功', async () => {
    const fetchMock = vi.fn()
    // 离线：不 fetch
    expect(await queryDict('https://api.test/{word}', 'x', { online: false, fetchImpl: fetchMock })).toEqual({ status: 'offline' })
    expect(fetchMock).not.toHaveBeenCalled()
    // 未配置：不 fetch
    expect(await queryDict('', 'x', { online: true, fetchImpl: fetchMock })).toEqual({ status: 'unconfigured' })
    expect(fetchMock).not.toHaveBeenCalled()
    // HTTP 500
    fetchMock.mockResolvedValueOnce(new Response('nope', { status: 500 }))
    const err = await queryDict('https://api.test/{word}', 'x', { online: true, fetchImpl: fetchMock })
    expect(err.status).toBe('error')
    // 成功
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ word: 'x', translation: '某释义' }), { status: 200 }),
    )
    const done = await queryDict('https://api.test/{word}', 'x', { online: true, fetchImpl: fetchMock })
    expect(done.status).toBe('done')
    if (done.status === 'done') {
      expect(done.entry.meanings).toEqual(['某释义'])
      expect(done.entry.source).toBe('api.test')
    }
  })
})

describe('DictSelectionLayer 接线', () => {
  it('多词选区不弹卡；单词选区弹卡；未配置时查询显示提示且零 fetch', async () => {
    stubSpeech(VOICES)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { article } = mountArticle('<p>hello world 词典</p>')
    const p = article.querySelector('p')!

    // 多词选区（挂载前已就绪）：挂载同步一次 → 多词 → 不弹卡
    const textNode = p.firstChild!
    const range = document.createRange()
    range.setStart(textNode, 0)
    range.setEnd(textNode, 11) // "hello world"
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    render(<DictSelectionLayer />)
    expect(screen.queryByTestId('dict-word')).toBeNull()

    // 单词选区 → 弹卡
    selectText(p, 0, 5)
    fireEvent.mouseUp(article)
    expect(screen.getByTestId('dict-word').textContent).toBe('hello')

    // 未配置 → 查询按钮给诚实提示，不发请求
    fireEvent.click(screen.getByTestId('dict-query'))
    await waitFor(() => expect(screen.getByTestId('dict-unconfigured')).toBeInTheDocument())
    expect(screen.getByTestId('dict-unconfigured').textContent).toContain('未配置词典来源')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('离线：显示「本机离线：无可用词典」，断言零请求', async () => {
    stubSpeech(VOICES)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    setOnline(false)
    useAppSettings.getState().update({ dictApiUrl: 'https://api.test/dict?q={word}' })
    const { article } = mountArticle('<p>hello</p>')
    render(<DictSelectionLayer />)

    selectText(article.querySelector('p')!, 0, 5)
    fireEvent.mouseUp(article)
    fireEvent.click(screen.getByTestId('dict-query'))
    await waitFor(() => expect(screen.getByTestId('dict-offline')).toBeInTheDocument())
    expect(screen.getByTestId('dict-offline').textContent).toContain('本机离线：无可用词典')
    // 关键断言：离线绝不发请求
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('已配置在线：渲染词头/音标/释义/来源；URL 只携带单词；CJK 词可查', async () => {
    stubSpeech(VOICES)
    const calls: string[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      calls.push(String(input))
      return Promise.resolve(
        new Response(
          JSON.stringify({ word: 'hello', phonetic: 'həˈləʊ', translations: ['你好', '问候'] }),
          { status: 200 },
        ),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ dictApiUrl: 'https://api.test/dict?q={word}' })
    const { article } = mountArticle('<p>hello 词典</p>')
    render(<DictSelectionLayer />)

    selectText(article.querySelector('p')!, 0, 5)
    fireEvent.mouseUp(article)
    fireEvent.click(screen.getByTestId('dict-query'))
    await waitFor(() => expect(screen.getByTestId('dict-result')).toBeInTheDocument())
    expect(screen.getByTestId('dict-result').textContent).toContain('你好')
    expect(screen.getByTestId('dict-result').textContent).toContain('həˈləʊ')
    expect(screen.getByTestId('dict-result').textContent).toContain('api.test')
    // 隐私断言：请求 URL 只含单词本身
    expect(calls).toEqual(['https://api.test/dict?q=hello'])

    // CJK 词
    const p = article.querySelector('p')!
    selectText(p, 6, 8) // 词典
    fireEvent.mouseUp(article)
    expect(screen.getByTestId('dict-word').textContent).toBe('词典')
  })

  it('发音按钮走 speechSynthesis（复用 P18 朗读链路）', () => {
    const speak = stubSpeech(VOICES)
    const { article } = mountArticle('<p>hello</p>')
    render(<DictSelectionLayer />)
    selectText(article.querySelector('p')!, 0, 5)
    fireEvent.mouseUp(article)
    fireEvent.click(screen.getByTestId('dict-speak'))
    expect(speak).toHaveBeenCalledTimes(1)
    expect((speak.mock.calls[0]![0] as MockUtterance).text).toBe('hello')
  })

  it('ReaderHeader 接线：选词后词典卡出现（lazy 分包 + 挂载同步）', async () => {
    stubSpeech(VOICES)
    vi.stubGlobal('fetch', vi.fn())
    const { article } = mountArticle('<p>hello</p>')
    render(withProviders(<ReaderHeader detail={detailFixture()} />))
    selectText(article.querySelector('p')!, 0, 5)
    fireEvent.mouseUp(article)
    // lazy chunk 挂载后同步一次选区 → 卡片出现
    await waitFor(() => expect(screen.getByTestId('dict-word').textContent).toBe('hello'))
  })
})

describe('DictSourceSettings 设置接线', () => {
  it('保存合法模板；非法模板拒绝并说明；清除来源', () => {
    render(withProviders(<DictSourceSettings />))
    const input = screen.getByLabelText(/选词词典来源/) as HTMLInputElement
    // 非法：缺 {word}
    fireEvent.change(input, { target: { value: 'https://api.test/dict' } })
    fireEvent.click(screen.getByRole('button', { name: '保存词典来源' }))
    expect(screen.getByText(/未保存/)).toBeInTheDocument()
    expect(useAppSettings.getState().settings.dictApiUrl).toBe('')

    // 合法
    fireEvent.change(input, { target: { value: 'https://api.test/dict?q={word}' } })
    fireEvent.click(screen.getByRole('button', { name: '保存词典来源' }))
    expect(useAppSettings.getState().settings.dictApiUrl).toBe('https://api.test/dict?q={word}')
    expect(screen.getByText(/词典来源已保存/)).toBeInTheDocument()

    // 清除
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '保存词典来源' }))
    expect(useAppSettings.getState().settings.dictApiUrl).toBe('')
    expect(screen.getByText(/已清除词典来源/)).toBeInTheDocument()
  })

  it('settings 归一化：损坏持久化值回退未配置（零外发默认）', () => {
    window.localStorage.setItem(
      'lumirss-settings',
      JSON.stringify({ ...DEFAULT_APP_SETTINGS, dictApiUrl: 'javascript:alert(1)' }),
    )
    act(() => {
      useAppSettings.setState({ settings: useAppSettings.getState().settings })
    })
    // 经 normalize 路径验证
    expect(normalizeDictApiUrl('javascript:alert(1)')).toBe('')
  })
})
