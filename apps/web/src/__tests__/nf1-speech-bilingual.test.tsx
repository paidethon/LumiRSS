/** NF1 N097 — 原文译文交替听读（jsdom）。
 *
 * 覆盖：交替开启时队列顺序为 [原文, 译文, 原文, 译文…]（同块相邻条目、
 * 高亮块 id 共享）；缺译文的块诚实只读原文（不补空档、不发起翻译）；
 * 原文 → 译文间隔按档位以定时器实现（无/短/长 → 0/500/1200ms，fake
 * timers 验证）；交替关闭恢复原逐块序列；译文取自既有 overlay DOM
 * （data-lb-t 节点），无 overlay 时不产出译文条目。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import {
  applyOverlay,
  annotateBlocks,
  resetOverlay,
} from '../lib/translation-blocks'
import {
  bilingualGapMs,
  buildSpeechQueue,
  collectSpeechCollection,
  DEFAULT_SPEECH_EXCLUSIONS,
  normalizeSpeechBilingualGap,
  ReaderSpeechEngine,
  type SpeechCollection,
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

const ORIG = ['原文一。', '原文二。', '原文三。']
const TRANS = ['译文一。', '译文三。']

beforeEach(() => {
  window.localStorage.clear()
  vi.useRealTimers()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  localStorage.clear()
})

// ---- 纯函数：队列构建 + 引擎间隔 ----

describe('N097 — 队列构建（纯函数）', () => {
  const collection: SpeechCollection = {
    texts: ORIG,
    startIndex: 0,
    translations: [TRANS[0]!, null, TRANS[1]!],
  }

  it('交替开启：每块 [原文, 译文] 相邻（同 blockIndex）；缺译文跳过', () => {
    const items = buildSpeechQueue(collection, { bilingual: true })
    expect(items.map((i) => i.text)).toEqual([
      '原文一。',
      '译文一。',
      '原文二。', // 缺译文 → 只读原文
      '原文三。',
      '译文三。',
    ])
    expect(items.map((i) => i.blockIndex)).toEqual([0, 0, 1, 2, 2])
    expect(items[1]!.isTranslation).toBe(true)
    expect(items[2]!.isTranslation).toBeUndefined()
  })

  it('交替关闭：纯原文序列（既有行为）；无 translations 字段也安全', () => {
    expect(buildSpeechQueue(collection).map((i) => i.text)).toEqual(ORIG)
    expect(
      buildSpeechQueue({ texts: ['甲', '乙'], startIndex: 0 }, { bilingual: true }).map(
        (i) => i.text,
      ),
    ).toEqual(['甲', '乙'])
  })

  it('间隔档位：无/短/长 → 0/500/1200ms；非法回退 none', () => {
    expect(bilingualGapMs('none')).toBe(0)
    expect(bilingualGapMs('short')).toBe(500)
    expect(bilingualGapMs('long')).toBe(1200)
    expect(normalizeSpeechBilingualGap('short')).toBe('short')
    expect(normalizeSpeechBilingualGap('medium')).toBe('none')
  })

  it('引擎：译文条目前按档位静默（fake timers）；stop 作废在途间隔', () => {
    vi.useFakeTimers()
    const speech = stubSpeech(VOICES)
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh', interPairGapMs: 500 },
      {},
    )
    const items = buildSpeechQueue(collection, { bilingual: true })
    engine.speakQueue(items, 0)
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).text).toBe('原文一。')

    // 原文读完 → 间隔期不出声；500ms 后译文出声
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    expect(speech.speak).toHaveBeenCalledTimes(1)
    act(() => {
      vi.advanceTimersByTime(499)
    })
    expect(speech.speak).toHaveBeenCalledTimes(1)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).text).toBe('译文一。')

    // stop 作废在途间隔定时（译文不再出声）
    ;(speech.speak.mock.calls[1]![0] as MockUtterance).onend!() // → 原文二（无间隔）
    expect((speech.speak.mock.calls[2]![0] as MockUtterance).text).toBe('原文二。')
    engine.stop()
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(speech.speak).toHaveBeenCalledTimes(3)
    expect(engine.speaking).toBe(false)
  })

  it('引擎：间隔 0（无档）时原文 → 译文立即接续', () => {
    const speech = stubSpeech(VOICES)
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh', interPairGapMs: 0 },
      {},
    )
    engine.speakQueue(buildSpeechQueue(collection, { bilingual: true }), 0)
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).text).toBe('译文一。')
  })
})

// ---- 组件：朗读设置面板开关 + overlay DOM 集成 ----

function mountArticleWithOverlay(): { container: HTMLElement; article: HTMLElement } {
  const container = document.createElement('div')
  container.innerHTML = [
    '<div class="lumi-reader-article">',
    `<p>${ORIG[0]}</p>`,
    `<p>${ORIG[1]}</p>`,
    `<p>${ORIG[2]}</p>`,
    '</div>',
  ].join('')
  document.body.appendChild(container)
  const article = container.querySelector('.lumi-reader-article') as HTMLElement
  // 模拟翻译 overlay（与 ReaderTranslation 同一 lib 路径）：分块编号 +
  // 全部块有译文，再隐藏第二块的译文（模拟局部失败）→ overlay DOM 中
  // 第二块没有 data-lb-t 邻居。
  const blocks = annotateBlocks(article)
  const texts = new Map<number, string>([
    [0, TRANS[0]!],
    [1, '不会出现的译文'],
    [2, TRANS[1]!],
  ])
  texts.delete(1) // 第二块：译文缺失（诚实跳过）
  applyOverlay(article, { texts, mode: 'bilingual' })
  expect(blocks).toHaveLength(3)
  return { container, article }
}

function collectFrom(container: HTMLElement, article: HTMLElement) {
  return () => {
    const s = useAppSettings.getState().settings
    const result = collectSpeechCollection(container, article, {
      exclusions: { ...DEFAULT_SPEECH_EXCLUSIONS },
      lexicon: s.speechLexicon,
    })
    // jsdom 几何全 0 → 自动起点会落在最后一个块；固定从头开始，
    // 让断言聚焦在交替顺序本身。
    return result === null ? null : { ...result, startIndex: 0 }
  }
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

describe('N097 — 交替听读（组件集成）', () => {
  it('开启交替：出声顺序 [原文, 译文, 原文, 原文, 译文]（缺译文跳过）；译文期间高亮停在原块', () => {
    vi.useFakeTimers()
    const speech = stubSpeech(VOICES)
    const { article } = mountArticleWithOverlay()
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, speechBilingualAlternate: true },
    })
    const paragraphs = article.querySelectorAll('p')

    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={collectFrom(article.parentElement as HTMLElement, article)}
        />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))

    const textsSoFar = () => speech.speak.mock.calls.map((c) => (c[0] as MockUtterance).text)
    expect(textsSoFar()).toEqual(['原文一。'])
    // 原文一读完 → 译文一接续；译文朗读期间高亮停在原块
    // （译文条目与原块共享 blockIndex——高亮/进度按块对齐）
    act(() => {
      ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    })
    expect(textsSoFar()).toEqual(['原文一。', '译文一。'])
    expect(paragraphs[0]!.hasAttribute('data-speech-active')).toBe(true)

    // 继续驱动：缺译文的原文二只读原文，原文三 → 译文三
    for (let i = 2; i < 5; i += 1) {
      act(() => {
        ;(speech.speak.mock.calls[i - 1]![0] as MockUtterance).onend!()
      })
    }
    expect(textsSoFar()).toEqual(['原文一。', '译文一。', '原文二。', '原文三。', '译文三。'])

    // 读完自然结束：不再有新的出声
    act(() => {
      ;(speech.speak.mock.calls[4]![0] as MockUtterance).onend!()
    })
    expect(speech.speak).toHaveBeenCalledTimes(5)
  })

  it('交替关闭：恢复纯原文序列；overlay DOM 里的译文条目不出现', () => {
    const speech = stubSpeech(VOICES)
    const { article } = mountArticleWithOverlay()
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        speechBilingualAlternate: false,
      },
    })

    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={collectFrom(article.parentElement as HTMLElement, article)}
        />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    const spoken = speech.speak.mock.calls.map((c) => (c[0] as MockUtterance).text)
    expect(spoken).toEqual(['原文一。'])

    let next = spoken.length
    for (let i = 0; i < 4; i += 1) {
      act(() => {
        ;(speech.speak.mock.calls[next - 1]![0] as MockUtterance).onend!()
      })
      next = speech.speak.mock.calls.length
    }
    expect(speech.speak.mock.calls.map((c) => (c[0] as MockUtterance).text)).toEqual(ORIG)
  })

  it('面板开关：交替 + 间隔档位写回设置（设备本地）', () => {
    stubSpeech(VOICES)
    const { article } = mountArticleWithOverlay()
    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={collectFrom(article.parentElement as HTMLElement, article)}
        />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    fireEvent.click(screen.getByRole('switch', { name: '原文译文交替听读' }))
    expect(useAppSettings.getState().settings.speechBilingualAlternate).toBe(true)
    // 间隔档位（无/短/长 segmented）
    fireEvent.click(screen.getByRole('button', { name: '长' }))
    expect(useAppSettings.getState().settings.speechBilingualGap).toBe('long')
    expect(bilingualGapMs(useAppSettings.getState().settings.speechBilingualGap)).toBe(1200)
    // 清理 overlay
    resetOverlay(article)
  })

  it('间隔档位在组件链路生效：短档下原文 → 译文间隔 500ms（fake timers）', () => {
    vi.useFakeTimers()
    const speech = stubSpeech(VOICES)
    const { article } = mountArticleWithOverlay()
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        speechBilingualAlternate: true,
        speechBilingualGap: 'short',
      },
    })
    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={collectFrom(article.parentElement as HTMLElement, article)}
        />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).text).toBe('原文一。')
    act(() => {
      ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    })
    expect(speech.speak).toHaveBeenCalledTimes(1)
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).text).toBe('译文一。')
    // 译文 → 下一块原文之间无间隔
    act(() => {
      ;(speech.speak.mock.calls[1]![0] as MockUtterance).onend!()
    })
    expect((speech.speak.mock.calls[2]![0] as MockUtterance).text).toBe('原文二。')
  })
})
