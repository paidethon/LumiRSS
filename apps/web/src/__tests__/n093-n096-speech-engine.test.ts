/** N093 按语言自动选声 + N096 结束模式/剩余段数 —— 逐块引擎增量。
 *
 * N093：混合语言块按 CJK/拉丁启发式逐块选声（中文块用 speechVoiceURIZh、
 * 拉丁块用 speechVoiceURIEn）；手动 voiceURI 非空 = 手动覆盖恒赢；
 * 配置的 URI 在系统中不存在 → pickVoice 自动链诚实回退，不崩不哑。
 * N096：'article' 模式读完触发 onEnd；'queue' 模式有续读源时接续
 * 下一批条目（onEnd 不触发）；无队列流（未注册续读源）= 诚实 no-op
 * （与到本篇相同）；remainingBlocks 展示剩余段数。 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ReaderSpeechEngine,
  detectSpeechLanguage,
  normalizeSpeechStopMode,
} from '../lib/reader-speech'

class MockUtterance {
  text: string
  lang = ''
  voice: unknown = null
  rate = 1
  onend: (() => void) | null = null
  onerror: ((event?: { error?: string }) => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}

function stubSpeech(voices: SpeechSynthesisVoice[] = []) {
  const speak = vi.fn()
  const cancel = vi.fn()
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => voices,
    speak,
    cancel,
    pause: vi.fn(),
    resume: vi.fn(),
  })
  vi.stubGlobal('SpeechSynthesisUtterance', MockUtterance)
  return { speak, cancel }
}

const VOICES = [
  { lang: 'en-US', name: 'English (America)', voiceURI: 'en-us' },
  { lang: 'zh-CN', name: '婷婷', voiceURI: 'zh-cn' },
  { lang: 'zh-TW', name: 'Mei-Jia', voiceURI: 'zh-tw' },
] as unknown as SpeechSynthesisVoice[]

beforeEach(() => {
  vi.useRealTimers()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** 依序驱动读完并返回每条 utterance（读取 live calls——引擎是懒惰链，
 * 后续 utterance 在前一块 onend 之后才入队）。 */
function drain(speak: ReturnType<typeof vi.fn>): MockUtterance[] {
  const spoken: MockUtterance[] = []
  for (let i = 0; ; i += 1) {
    const call = speak.mock.calls[i] as unknown[] | undefined
    if (call === undefined) break
    const utterance = call[0] as MockUtterance
    spoken.push(utterance)
    utterance.onend?.()
  }
  return spoken
}

// ---- N093：块级语言判定 ----

describe('N093 detectSpeechLanguage（CJK/拉丁启发式）', () => {
  it('中文块 → zh；英文块 → en；混排按占比；空/纯标点 → zh 保守回退', () => {
    expect(detectSpeechLanguage('这是一段中文正文。')).toBe('zh')
    expect(detectSpeechLanguage('This is an English paragraph.')).toBe('en')
    // 中文段落里夹少量英文词：CJK 占比高 → zh
    expect(detectSpeechLanguage('这是一个 Transformer 模型的中文介绍。')).toBe('zh')
    // 英文段落里夹个别中文字符：拉丁占多 → en
    expect(detectSpeechLanguage('A long English sentence about models 模型.')).toBe('en')
    expect(detectSpeechLanguage('')).toBe('zh')
    expect(detectSpeechLanguage('…!?')).toBe('zh')
  })
})

// ---- N093：逐块按语言出声 ----

describe('N093 引擎按语言选声', () => {
  it('混合块逐块切声：中文块用 voiceURIZh、英文块用 voiceURIEn（lang 也跟随）', () => {
    const speech = stubSpeech(VOICES)
    const engine = new ReaderSpeechEngine(
      {
        rate: 1,
        voiceURI: null,
        langPrefix: 'zh',
        perLanguageVoices: true,
        voiceURIZh: 'zh-tw',
        voiceURIEn: 'en-us',
      },
      {},
    )
    engine.speakFrom(['中文段落内容', 'English paragraph content'], 0)
    const spoken = drain(speech.speak)
    expect(spoken).toHaveLength(2)
    expect(spoken[0]!.voice).toMatchObject({ voiceURI: 'zh-tw' })
    expect(spoken[0]!.lang).toBe('zh-TW')
    expect(spoken[1]!.voice).toMatchObject({ voiceURI: 'en-us' })
    expect(spoken[1]!.lang).toBe('en-US')
  })

  it('手动 voiceURI 非空 = 手动覆盖恒赢（按语言设置不生效）', () => {
    const speech = stubSpeech(VOICES)
    const engine = new ReaderSpeechEngine(
      {
        rate: 1,
        voiceURI: 'en-us',
        langPrefix: 'zh',
        perLanguageVoices: true,
        voiceURIZh: 'zh-tw',
        voiceURIEn: 'en-us',
      },
      {},
    )
    engine.speakFrom(['中文段落内容', 'English paragraph content'], 0)
    const spoken = drain(speech.speak)
    // 两块都是手动选择的 en-us（P18 手动语义不变）
    expect(spoken[0]!.voice).toMatchObject({ voiceURI: 'en-us' })
    expect(spoken[1]!.voice).toMatchObject({ voiceURI: 'en-us' })
  })

  it('回退诚实：配置的 URI 已不存在 → 该语言走 pickVoice 自动链；完全无声音 → lang 仍标块语言', () => {
    // zh 配置失效 → 自动链回到 zh-cn（不哑、不假装配置还在）
    const speech = stubSpeech(VOICES)
    const engine = new ReaderSpeechEngine(
      {
        rate: 1,
        voiceURI: null,
        langPrefix: 'zh',
        perLanguageVoices: true,
        voiceURIZh: 'missing-uri',
        voiceURIEn: 'en-us',
      },
      {},
    )
    engine.speakFrom(['中文段落内容'], 0)
    const spoken = drain(speech.speak)
    expect(spoken[0]!.voice).toMatchObject({ voiceURI: 'zh-cn' })

    // 系统无任何声音：voice 为空，lang 诚实标注为块语言（默认引擎按 lang 挑音）
    const speechEmpty = stubSpeech([])
    const engineEmpty = new ReaderSpeechEngine(
      {
        rate: 1,
        voiceURI: null,
        langPrefix: 'zh',
        perLanguageVoices: true,
        voiceURIEn: 'en-us',
      },
      {},
    )
    engineEmpty.speakFrom(['English paragraph content'], 0)
    const spokenEmpty = drain(speechEmpty.speak)
    expect(spokenEmpty[0]!.voice).toBeNull()
    expect(spokenEmpty[0]!.lang).toBe('en-US')
  })
})

// ---- N096：结束模式 + 剩余段数 ----

describe('N096 结束模式（到本篇 / 到本队列）', () => {
  it("'article'：本篇读完 → onEnd 触发一次（既有语义）", () => {
    const speech = stubSpeech(VOICES)
    let ended = 0
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh', stopMode: 'article' },
      { onEnd: () => { ended += 1 } },
    )
    engine.speakFrom(['一', '二'], 0)
    drain(speech.speak)
    expect(ended).toBe(1)
    expect(engine.speaking).toBe(false)
  })

  it("'queue' + 续读源：本篇读完接续下一批条目（onEnd 不触发，跨批朗读）", () => {
    const speech = stubSpeech(VOICES)
    let ended = 0
    let asked = 0
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh', stopMode: 'queue' },
      { onEnd: () => { ended += 1 } },
    )
    engine.setQueueContinuation(() => {
      asked += 1
      // 只供给下一批一次；再问 = 队列尽头 → null
      if (asked === 1) {
        return [
          { text: '下一篇一', blockIndex: 0 },
          { text: '下一篇二', blockIndex: 1 },
        ]
      }
      return null
    })
    engine.speakFrom(['本篇一', '本篇二'], 0)
    // 第一批读到一半：尚未询问续读源，onEnd 不触发
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    expect(ended).toBe(0)
    // 依序读完整条链（第一批 → 续读批次 → 队列尽头）
    const spoken = drain(speech.speak)
    expect(spoken.map((u) => u.text)).toEqual(['本篇一', '本篇二', '下一篇一', '下一篇二'])
    expect(asked).toBe(2)
    // 整条队列耗尽 → 诚实结束，onEnd 恰好一次
    expect(ended).toBe(1)
    expect(engine.speaking).toBe(false)
  })

  it("'queue' 无队列流（未注册续读源）= 诚实 no-op：与到本篇相同", () => {
    const speech = stubSpeech(VOICES)
    let ended = 0
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh', stopMode: 'queue' },
      { onEnd: () => { ended += 1 } },
    )
    engine.speakFrom(['一', '二'], 0)
    drain(speech.speak)
    expect(ended).toBe(1)
  })

  it("'queue' 续读源返回空/null → 诚实结束（onEnd 一次），不空转", () => {
    const speech = stubSpeech(VOICES)
    let ended = 0
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh', stopMode: 'queue' },
      { onEnd: () => { ended += 1 } },
    )
    engine.setQueueContinuation(() => null)
    engine.speakFrom(['一'], 0)
    drain(speech.speak)
    expect(ended).toBe(1)
    expect(speech.speak).toHaveBeenCalledTimes(1)
  })

  it('会话中 setStopMode 不重读当前块；剩余段数 remainingBlocks 随推进递减', () => {
    const speech = stubSpeech(VOICES)
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh', stopMode: 'article' },
      {},
    )
    engine.speakFrom(['一', '二', '三'], 0)
    expect(engine.remainingBlocks).toBe(3)
    engine.setStopMode('queue') // 边界生效模式：不重读当前块
    expect(speech.speak).toHaveBeenCalledTimes(1)
    expect(engine.currentBlockIndex).toBe(0)
    ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    expect(engine.remainingBlocks).toBe(2)
    engine.stop()
    expect(engine.remainingBlocks).toBeNull()
  })

  it('normalizeSpeechStopMode：非法值回退 article（既有语义）', () => {
    expect(normalizeSpeechStopMode('queue')).toBe('queue')
    expect(normalizeSpeechStopMode('article')).toBe('article')
    expect(normalizeSpeechStopMode('nonsense')).toBe('article')
    expect(normalizeSpeechStopMode(undefined)).toBe('article')
  })
})
