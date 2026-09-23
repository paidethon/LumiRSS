/** P18 朗读引擎测试（mock speechSynthesis：证明接线，非平台能力验证）。
 *
 * 覆盖：逐块队列（顺序 / lang / voice / rate）、currentBlockIndex 推进
 * 与 onBlockChange、speakFrom 中间块起点、stop 作废在途回调、暂停/继续、
 * 声音挑选（首选 URI 优先 / 缺失回退 / 中文优先保留）、睡眠定时（块边界
 * 停止 + 已停止状态；关 = 永不触发）、20k 总量截断、ReaderHeader 面板
 * （进度/预览/声音选择/当前块 DOM 高亮）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import {
  ReaderSpeechEngine,
  SPEECH_MAX_CHARS,
  capSpeechBlocks,
  listVoices,
  markSpeechBlockElement,
  pickVoice,
} from '../lib/reader-speech'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

// ---- speechSynthesis mock ----

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
  { lang: 'en-US', name: 'English (America)', voiceURI: 'en-us' },
  { lang: 'zh-CN', name: '婷婷', voiceURI: 'zh-cn' },
  { lang: 'zh-TW', name: 'Mei-Jia', voiceURI: 'zh-tw' },
] as unknown as SpeechSynthesisVoice[]

/** 引擎 + 事件记录（onBlockChange 索引流 / 自然读完 / 错误 / 睡眠到点）。 */
function makeEngine() {
  const events = {
    blocks: [] as number[],
    ended: 0,
    errors: [] as string[],
    sleep: 0,
  }
  const engine = new ReaderSpeechEngine(
    { rate: 1, voiceURI: null, langPrefix: 'zh' },
    {
      onBlockChange: (block) => {
        events.blocks.push(block.index)
      },
      onEnd: () => {
        events.ended += 1
      },
      onError: (message) => {
        events.errors.push(message)
      },
      onSleepTimer: () => {
        events.sleep += 1
      },
    },
  )
  return { engine, events }
}

/** 依序驱动队列读完，返回每块实际朗读文本。 */
function drain(speak: ReturnType<typeof vi.fn>, maxBlocks = 64): string[] {
  const spoken: string[] = []
  for (let i = 0; i < maxBlocks; i += 1) {
    const call = speak.mock.calls[i] as unknown[] | undefined
    if (call === undefined) break
    const utterance = call[0] as MockUtterance
    spoken.push(utterance.text)
    utterance.onend?.()
  }
  return spoken
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  localStorage.clear()
})

// ---- (a)(b)(c)(d)(e) 逐块引擎 ----

describe('P18 — 逐块朗读引擎', () => {
  it('逐块出声：块文本按序、每块自带 lang/voice/rate；读完触发 onEnd', () => {
    const speech = stubSpeech(VOICES)
    const { engine, events } = makeEngine()

    engine.speakFrom(['第一段', '第二段', '第三段'], 0)

    // 首块即刻出声（其余在块边界接续——引擎的懒惰链，不是一次性全部入队）
    expect(speech.speak).toHaveBeenCalledTimes(1)
    expect(speech.cancel).toHaveBeenCalledTimes(1)
    const spoken = drain(speech.speak)
    expect(spoken).toEqual(['第一段', '第二段', '第三段'])
    for (let i = 0; i < 3; i += 1) {
      const utterance = speech.speak.mock.calls[i]![0] as MockUtterance
      expect(utterance.rate).toBe(1)
      expect(utterance.voice).toMatchObject({ voiceURI: 'zh-cn' })
      expect(utterance.lang).toBe('zh-CN')
    }
    expect(events.ended).toBe(1)
    expect(engine.speaking).toBe(false)
  })

  it('currentBlockIndex 随块推进；onBlockChange 携带 1 起 position/total', () => {
    const speech = stubSpeech(VOICES)
    const infos: Array<{ index: number; position: number; total: number }> = []
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh' },
      { onBlockChange: (block) => infos.push({ ...block }) },
    )

    engine.speakFrom(['一', '二', '三'], 0)
    expect(engine.currentBlockIndex).toBe(0)
    expect(engine.progress).toEqual({ position: 1, total: 3 })
    expect(infos).toEqual([{ index: 0, position: 1, total: 3 }])

    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    expect(engine.currentBlockIndex).toBe(1)
    expect(infos[infos.length - 1]).toEqual({ index: 1, position: 2, total: 3 })
  })

  it('speakFrom 中间块起点：从指定索引开读；空块跳过但保留原始下标', () => {
    const speech = stubSpeech(VOICES)
    const { engine, events } = makeEngine()

    engine.speakFrom(['a', 'b', 'c'], 1)
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).text).toBe('b')
    expect(events.blocks[0]).toBe(1)
    expect(engine.currentBlockIndex).toBe(1)

    // 空白块不入队，但高亮用的是原始块下标
    const speech2 = stubSpeech(VOICES)
    const { engine: engine2, events: events2 } = makeEngine()
    engine2.speakFrom(['  ', '乙', '丙'], 0)
    expect((speech2.speak.mock.calls[0]![0] as MockUtterance).text).toBe('乙')
    expect(events2.blocks[0]).toBe(1)
  })

  it('stop：cancel + 清队列 + 作废在途回调（不再 onBlockChange / 不再出声）', () => {
    const speech = stubSpeech(VOICES)
    const { engine, events } = makeEngine()

    engine.speakFrom(['一', '二', '三'], 0)
    expect(events.blocks).toEqual([0])
    const first = speech.speak.mock.calls[0]![0] as MockUtterance

    engine.stop()
    expect(speech.cancel).toHaveBeenCalled()
    expect(engine.speaking).toBe(false)
    expect(engine.currentBlockIndex).toBeNull()

    // 旧 utterance 的 onend / onerror 回放（Chrome cancel 行为）不产生任何通知
    first.onend!()
    first.onerror!()
    expect(events.blocks).toEqual([0])
    expect(events.ended).toBe(0)
    expect(events.errors).toEqual([])
    expect(speech.speak).toHaveBeenCalledTimes(1)
    // 幂等：重复 stop 无害
    expect(() => engine.stop()).not.toThrow()
  })

  it('暂停/继续接线 synthesis.pause / resume；自然读完与手动停止语义分明', () => {
    const speech = stubSpeech(VOICES)
    const { engine, events } = makeEngine()

    engine.speakFrom(['一', '二'], 0)
    engine.pause()
    expect(speech.pause).toHaveBeenCalledTimes(1)
    engine.resume()
    expect(speech.resume).toHaveBeenCalledTimes(1)

    // 手动停止不触发 onEnd（那是「读完」；睡眠到点走 onSleepTimer）
    engine.stop()
    expect(events.ended).toBe(0)
  })

  it('utterance onerror → onError 透出并停机（错误后不再接续）', () => {
    const speech = stubSpeech(VOICES)
    const { engine, events } = makeEngine()

    engine.speakFrom(['一', '二'], 0)
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onerror!()
    expect(events.errors).toEqual(['朗读失败，请重试。'])
    expect(engine.speaking).toBe(false)
    expect(speech.speak).toHaveBeenCalledTimes(1)
  })

  it('setConfig 朗读中生效：取消当前块并按新配置重读当前段（非整篇从头）', () => {
    const speech = stubSpeech(VOICES)
    const { engine } = makeEngine()

    engine.speakFrom(['一', '二', '三'], 0)
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!() // 推进到第二块
    engine.setConfig({ rate: 1.5 })
    const call = speech.speak.mock.calls[2]![0] as MockUtterance
    expect(call.text).toBe('二') // 当前段重读，不回到第一段
    expect(call.rate).toBe(1.5)
  })
})

// ---- (f) 声音挑选 ----

describe('P18 — 声音挑选', () => {
  it('首选 voiceURI 命中即赢（可跨语言）；系统缺该 URI → 回退语言链', () => {
    expect(pickVoice(VOICES, 'zh', 'en-us')?.voiceURI).toBe('en-us')
    expect(pickVoice(VOICES, 'zh', 'missing-uri')?.voiceURI).toBe('zh-cn')
    expect(pickVoice(VOICES, 'en', 'missing-uri')?.voiceURI).toBe('en-us')
  })

  it('精确 lang → 前缀匹配 → 诚实默认（保留中文优先）→ 空清单 null', () => {
    expect(pickVoice(VOICES, 'zh-CN', null)?.voiceURI).toBe('zh-cn') // 精确
    expect(pickVoice(VOICES, 'zh', null)?.voiceURI).toBe('zh-cn') // 前缀
    expect(pickVoice(VOICES, 'fr-FR', null)?.voiceURI).toBe('zh-cn') // 默认 = 中文优先
    expect(pickVoice([{ lang: 'en-US', name: 'E', voiceURI: 'e' } as SpeechSynthesisVoice], 'fr', null)?.voiceURI).toBe('e')
    expect(pickVoice([], 'zh', null)).toBeNull()
  })

  it('listVoices 按 lang 分组（小写组键、字典序）；缺省读全局 getVoices', () => {
    expect(listVoices(VOICES).map((g) => g.lang)).toEqual(['en-us', 'zh-cn', 'zh-tw'])
    expect(listVoices(VOICES)[1]!.voices).toHaveLength(1)
    stubSpeech(VOICES)
    expect(listVoices()).toHaveLength(3)
  })
})

// ---- (g) 睡眠定时 ----

describe('P18 — 睡眠定时（块边界检查）', () => {
  it('到点后在下一个块边界干净停止：不接续、触发 onSleepTimer、不触发 onEnd', () => {
    vi.useFakeTimers()
    const speech = stubSpeech(VOICES)
    const { engine, events } = makeEngine()

    engine.armSleepTimer(5)
    engine.speakFrom(['一', '二', '三'], 0)
    // 未到点：边界正常接续
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    expect(speech.speak).toHaveBeenCalledTimes(2)
    expect(events.sleep).toBe(0)

    vi.advanceTimersByTime(5 * 60_000)
    ;(speech.speak.mock.calls[1]![0] as MockUtterance).onend!()
    expect(speech.speak).toHaveBeenCalledTimes(2) // 第三块不再出声
    expect(events.sleep).toBe(1)
    expect(events.ended).toBe(0)
    expect(engine.speaking).toBe(false)
    expect(engine.currentBlockIndex).toBeNull()
  })

  it('定时关闭（0/null）= 永不触发：超时后照常读完', () => {
    vi.useFakeTimers()
    const speech = stubSpeech(VOICES)
    const { engine, events } = makeEngine()

    engine.armSleepTimer(null)
    engine.speakFrom(['一', '二'], 0)
    vi.advanceTimersByTime(60 * 60_000)
    expect(drain(speech.speak)).toEqual(['一', '二'])
    expect(events.sleep).toBe(0)
    expect(events.ended).toBe(1)
  })
})

// ---- (h) 20k 总量截断 ----

describe('P18 — 总量上限（20k 截断）', () => {
  it('capSpeechBlocks：末块截断到预算，空块过滤', () => {
    const capped = capSpeechBlocks(['a'.repeat(15_000), 'b'.repeat(10_000)])
    expect(capped[0]).toHaveLength(15_000)
    expect(capped[1]).toHaveLength(SPEECH_MAX_CHARS - 15_000)
    expect(capped.join('').length).toBeLessThanOrEqual(SPEECH_MAX_CHARS)
    expect(capSpeechBlocks(['', '  ', 'x'])).toEqual(['x'])
  })

  it('引擎入队施加同一上限：截断后仍逐块接续', () => {
    const speech = stubSpeech(VOICES)
    const { engine } = makeEngine()

    engine.speakFrom(['a'.repeat(15_000), 'b'.repeat(10_000)], 0)
    expect(engine.progress).toEqual({ position: 1, total: 2 })
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).text).toHaveLength(15_000)
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).text).toHaveLength(5_000)
  })
})

// ---- 段落高亮标记 ----

describe('P18 — 当前块 DOM 标记', () => {
  it('markSpeechBlockElement：按块下标打 data-speech-active；null 清除', () => {
    document.body.innerHTML =
      '<div class="lumi-reader-article"><p id="b0">甲</p><p id="b1">乙</p></div>'
    try {
      markSpeechBlockElement(1)
      expect(document.getElementById('b1')!.hasAttribute('data-speech-active')).toBe(true)
      expect(document.getElementById('b0')!.hasAttribute('data-speech-active')).toBe(false)
      markSpeechBlockElement(0)
      expect(document.getElementById('b1')!.hasAttribute('data-speech-active')).toBe(false)
      expect(document.getElementById('b0')!.hasAttribute('data-speech-active')).toBe(true)
      markSpeechBlockElement(null)
      expect(document.querySelectorAll('[data-speech-active]')).toHaveLength(0)
    } finally {
      document.body.innerHTML = ''
    }
  })
})

// ---- ReaderHeader 面板接线 ----

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

/** 面板预览截前 40 字：块文本故意 48 字，DOM 段落与预览文本不重合。 */
const BLOCK_TEXT = '段落零一'.repeat(12)

function stubArticleDom(): () => void {
  const host = document.createElement('div')
  host.innerHTML = `<div class="lumi-reader-article"><p>${BLOCK_TEXT}</p><p>${BLOCK_TEXT}</p><p>${BLOCK_TEXT}</p></div>`
  document.body.appendChild(host)
  return () => {
    host.remove()
  }
}

describe('P18 — ReaderHeader 朗读面板接线', () => {
  it('逐块出声 + 当前面板进度/预览 + data-speech-active 跟随推进；停止清除', () => {
    const speech = stubSpeech(VOICES)
    const cleanupDom = stubArticleDom()
    const collect = () => ({ texts: [BLOCK_TEXT, BLOCK_TEXT, BLOCK_TEXT], startIndex: 0 })

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    try {
      fireEvent.click(screen.getByRole('button', { name: '朗读' }))
      const paragraphs = document.querySelectorAll('.lumi-reader-article p')
      expect(paragraphs[0]!.hasAttribute('data-speech-active')).toBe(true)

      fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
      expect(screen.getByText('正在朗读 第 1 / 3 段')).toBeInTheDocument()
      expect(screen.getByText(BLOCK_TEXT.slice(0, 40))).toBeInTheDocument()

      act(() => {
        ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
      })
      expect(paragraphs[1]!.hasAttribute('data-speech-active')).toBe(true)
      expect(paragraphs[0]!.hasAttribute('data-speech-active')).toBe(false)
      expect(screen.getByText('正在朗读 第 2 / 3 段')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: '停止朗读' }))
      expect(paragraphs[1]!.hasAttribute('data-speech-active')).toBe(false)
      expect(screen.queryByText('正在朗读 第 2 / 3 段')).not.toBeInTheDocument()
    } finally {
      cleanupDom()
    }
  })

  it('声音选择：设置中的 voiceURI 生效；面板下拉改动写回设置并影响下一块', () => {
    const speech = stubSpeech(VOICES)
    const cleanupDom = stubArticleDom()
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, speechVoiceURI: 'en-us' },
    })
    const collect = () => ({ texts: [BLOCK_TEXT, BLOCK_TEXT, BLOCK_TEXT], startIndex: 0 })

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    try {
      fireEvent.click(screen.getByRole('button', { name: '朗读' }))
      // 首选 URI 优先于语言默认（zh）
      expect(speech.speak.mock.calls[0]![0] as MockUtterance).toMatchObject({
        voice: { voiceURI: 'en-us' },
      })

      fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
      fireEvent.change(screen.getByLabelText('朗读声音'), { target: { value: 'zh-tw' } })
      expect(useAppSettings.getState().settings.speechVoiceURI).toBe('zh-tw')
      // 朗读中改声音 → 当前段按新声音重读
      const utterance = speech.speak.mock.calls[1]![0] as MockUtterance
      expect(utterance.voice).toMatchObject({ voiceURI: 'zh-tw' })
    } finally {
      cleanupDom()
    }
  })

  it('睡眠定时（5 分）：块边界到点停止，面板诚实显示 已停止（睡眠定时）', () => {
    vi.useFakeTimers()
    const speech = stubSpeech(VOICES)
    const collect = () => ({ texts: ['一', '二', '三'], startIndex: 0 })
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, speechSleepTimerMinutes: 5 },
    })

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    act(() => {
      vi.advanceTimersByTime(5 * 60_000)
    })
    act(() => {
      ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    })
    // 到点：不接续第二块
    expect(speech.speak).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    expect(screen.getByText('已停止（睡眠定时）')).toBeInTheDocument()
  })

  it('定时关闭：超时后照常读完，面板无 已停止 文案', () => {
    vi.useFakeTimers()
    const speech = stubSpeech(VOICES)
    const collect = () => ({ texts: ['一', '二'], startIndex: 0 })

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    act(() => {
      vi.advanceTimersByTime(2 * 60 * 60_000)
    })
    let spoken: string[] = []
    act(() => {
      spoken = drain(speech.speak)
    })
    expect(spoken).toEqual(['一', '二'])

    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    expect(screen.queryByText('已停止（睡眠定时）')).not.toBeInTheDocument()
    expect(screen.getByText('未在朗读')).toBeInTheDocument()
  })

  it('语速：面板 segmented 写回设置；朗读中调速 = 当前段按新语速重读', () => {
    const speech = stubSpeech(VOICES)
    const collect = () => ({ texts: ['一', '二'], startIndex: 0 })

    render(
      withProviders(
        <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).rate).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    const panel = screen.getByRole('group', { name: '朗读设置' })
    fireEvent.click(within(panel).getByRole('button', { name: '1.5x' }))
    expect(useAppSettings.getState().settings.speechRate).toBe(1.5)
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).rate).toBe(1.5)
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).text).toBe('一')
  })
})
