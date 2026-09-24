/** NF1 N095 — 发音词典（jsdom）。
 *
 * 覆盖：词典替换只作用于出声文本（utterance）与试听预览，文章 DOM 不变；
 * 大小写不敏感子串匹配；空匹配在设置面板被诚实拒绝；cap 50 拒绝新增；
 * 词典写入设备本地设置并持久化（重载归一化后保留）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import {
  applySpeechLexicon,
  collectSpeechCollection,
  DEFAULT_SPEECH_EXCLUSIONS,
  normalizeSpeechLexicon,
  SPEECH_LEXICON_CAP,
} from '../lib/reader-speech'
import {
  DEFAULT_APP_SETTINGS,
  loadSettings,
  useAppSettings,
} from '../store/app-settings'
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

const PARA_A = 'LumiRSS is a self-hosted reader.'
const PARA_B = '第二段正文。'

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  localStorage.clear()
})

// ---- 纯函数 ----

describe('N095 — 词典归一化与应用（纯函数）', () => {
  it('大小写不敏感子串替换；按序应用；空匹配为无操作', () => {
    const lexicon = [
      { match: 'lumirss', replace: '露米RSS' },
      { match: 'reader', replace: '阅读器' },
    ]
    expect(applySpeechLexicon(PARA_A, lexicon)).toBe('露米RSS is a self-hosted 阅读器.')
    expect(applySpeechLexicon(PARA_A, [])).toBe(PARA_A)
    // 空匹配不产生正则灾难（guard：normalize 已过滤，但 apply 仍防御）
    expect(applySpeechLexicon('abc', [{ match: '', replace: 'x' } as never])).toBe('abc')
  })

  it('归一化：空匹配/非对象丢弃、按 match 去重（大小写不敏感）、cap 50', () => {
    expect(
      normalizeSpeechLexicon([
        { match: ' Lumi ', replace: '露米' },
        { match: '', replace: 'x' },
        { match: 'lumi', replace: '重复' },
        { match: 42, replace: 'x' },
        'junk',
        null,
        { match: 'ok' }, // replace 缺省 → ''
      ]),
    ).toEqual([
      { match: 'Lumi', replace: '露米' },
      { match: 'ok', replace: '' },
    ])
    const many = Array.from({ length: 60 }, (_, i) => ({ match: `w${i}`, replace: `r${i}` }))
    expect(normalizeSpeechLexicon(many)).toHaveLength(SPEECH_LEXICON_CAP)
  })
})

// ---- 组件：出声替换 + 预览 + 面板校验 + 持久化 ----

function mountArticle(): { container: HTMLElement; article: HTMLElement } {
  const container = document.createElement('div')
  container.innerHTML = [
    '<div class="lumi-reader-article">',
    `<p>${PARA_A}</p>`,
    `<p>${PARA_B}</p>`,
    '</div>',
  ].join('')
  document.body.appendChild(container)
  const article = container.querySelector('.lumi-reader-article') as HTMLElement
  return { container, article }
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

describe('N095 — 朗读出声替换、试听预览与面板校验', () => {
  it('替换作用于出声与试听；文章 DOM 不变；词典持久化', () => {
    const speech = stubSpeech(VOICES)
    const container = document.createElement('div')
    container.innerHTML = `<div class="lumi-reader-article"><p>${PARA_A}</p></div>`
    document.body.appendChild(container)
    const article = container.querySelector('.lumi-reader-article') as HTMLElement
    const collect = () => {
      const s = useAppSettings.getState().settings
      return collectSpeechCollection(container, article, {
        exclusions: { ...DEFAULT_SPEECH_EXCLUSIONS },
        lexicon: s.speechLexicon,
      })
    }
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        speechLexicon: [{ match: 'LumiRSS', replace: '露米' }],
      },
    })

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )

    // 试听预览反映替换
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    expect(document.querySelector('[data-lumi-speech-preview]')!.textContent).toContain(
      '露米 is a self-hosted reader.',
    )

    // 出声文本替换（单块文章：自动起点即该块）
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    const utterance = speech.speak.mock.calls[0]![0] as MockUtterance
    expect(utterance.text).toBe('露米 is a self-hosted reader.')

    // 文章 DOM 不变（替换只在朗读/试听路径）
    expect(article.querySelector('p')!.textContent).toBe(PARA_A)

    // 持久化（本例为 setState 直写；持久化路径由下一条用例覆盖）
    expect(useAppSettings.getState().settings.speechLexicon).toEqual([
      { match: 'LumiRSS', replace: '露米' },
    ])
    container.remove()
  })

  it('面板：空匹配拒绝、重复拒绝、cap 50 拒绝；有效条目添加并持久化', () => {
    stubSpeech(VOICES)
    const { container, article } = mountArticle()
    const collect = () => {
      const s = useAppSettings.getState().settings
      return collectSpeechCollection(container, article, {
        exclusions: { ...DEFAULT_SPEECH_EXCLUSIONS },
        lexicon: s.speechLexicon,
      })
    }

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))

    const matchInput = screen.getByLabelText('词典匹配词')
    const replaceInput = screen.getByLabelText('替换为')
    const addButton = screen.getByRole('button', { name: '添加' })

    // 空匹配拒绝
    fireEvent.click(addButton)
    expect(screen.getByText('匹配词不能为空。')).toBeInTheDocument()
    expect(useAppSettings.getState().settings.speechLexicon).toEqual([])

    // 有效添加 + 持久化
    fireEvent.change(matchInput, { target: { value: 'TTS' } })
    fireEvent.change(replaceInput, { target: { value: '语音合成' } })
    fireEvent.click(addButton)
    expect(useAppSettings.getState().settings.speechLexicon).toEqual([
      { match: 'TTS', replace: '语音合成' },
    ])
    const raw = JSON.parse(
      localStorage.getItem('lumirss-settings') ?? '{}',
    ) as { speechLexicon?: unknown }
    expect(raw.speechLexicon).toEqual([{ match: 'TTS', replace: '语音合成' }])
    expect(loadSettings(localStorage).speechLexicon).toEqual([
      { match: 'TTS', replace: '语音合成' },
    ])
    // 输入清空、错误清除
    expect(matchInput).toHaveValue('')

    // 重复（大小写不敏感）拒绝
    fireEvent.change(matchInput, { target: { value: 'tts' } })
    fireEvent.click(addButton)
    expect(screen.getByText('该匹配词已存在。')).toBeInTheDocument()

    // cap 50 拒绝
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        speechLexicon: Array.from({ length: SPEECH_LEXICON_CAP }, (_, i) => ({
          match: `w${i}`,
          replace: `r${i}`,
        })),
      },
    })
    fireEvent.change(matchInput, { target: { value: '新词' } })
    fireEvent.click(addButton)
    expect(screen.getByText(`最多 ${SPEECH_LEXICON_CAP} 条，请先删除旧条目。`)).toBeInTheDocument()
    expect(useAppSettings.getState().settings.speechLexicon).toHaveLength(SPEECH_LEXICON_CAP)
  })

  it('删除条目：从词典移除并同步设置', () => {
    stubSpeech(VOICES)
    const { container, article } = mountArticle()
    const collect = () => {
      const s = useAppSettings.getState().settings
      return collectSpeechCollection(container, article, {
        exclusions: { ...DEFAULT_SPEECH_EXCLUSIONS },
        lexicon: s.speechLexicon,
      })
    }
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        speechLexicon: [
          { match: '甲', replace: '一' },
          { match: '乙', replace: '二' },
        ],
      },
    })
    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    fireEvent.click(screen.getByRole('button', { name: '删除词典条目 甲' }))
    expect(useAppSettings.getState().settings.speechLexicon).toEqual([
      { match: '乙', replace: '二' },
    ])
  })
})
