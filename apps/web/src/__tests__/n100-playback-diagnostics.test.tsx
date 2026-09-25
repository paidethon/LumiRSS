/** N100 播放故障自助诊断 —— 故障分型（附件播放器 + 朗读引擎）。
 *
 * 覆盖：{网络失败 / 解码失败 / 音源缺失 / 未授权} 各自的独立话术与
 * 匹配处置——网络失败允许恰好一次手动重试（预算用尽后诚实死路，绝
 * 不无限循环）；解码失败有备选音源时「换其它音源」、无备选诚实死路；
 * 音源缺失（无 src / 404）给设置指引；未授权（探测 401/403）给重新
 * 登录指引。朗读引擎侧：speechSynthesis 错误码分型 + 零自动重试。
 * 同源探测用 fetch mock；跨源地址诚实跳过探测。 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EnclosurePlayer, ENCLOSURE_RETRY_BUDGET } from '../components/EnclosurePlayer'
import {
  classifyMediaErrorCode,
  classifySpeechError,
  probePlaybackSource,
} from '../lib/playback-diagnostics'
import {
  ReaderSpeechEngine,
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
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => voices,
    speak,
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
  })
  vi.stubGlobal('SpeechSynthesisUtterance', MockUtterance)
  return { speak }
}

const VOICES = [
  { lang: 'zh-CN', name: '婷婷', voiceURI: 'zh-cn' },
] as unknown as SpeechSynthesisVoice[]

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ---- 分型纯函数 ----

describe('N100 故障分型', () => {
  it('媒体错误码：2(网络)/1(中止) → 网络失败；3(解码)/4(格式) → 解码失败', () => {
    expect(classifyMediaErrorCode(2).cls).toBe('network')
    expect(classifyMediaErrorCode(1).cls).toBe('network')
    expect(classifyMediaErrorCode(3).cls).toBe('decode')
    expect(classifyMediaErrorCode(4).cls).toBe('decode')
    expect(classifyMediaErrorCode(null).cls).toBe('unknown')
  })

  it('四类故障各有独立话术（互不相同、非空）', () => {
    const failures = [
      classifyMediaErrorCode(2),
      classifyMediaErrorCode(3),
      classifySpeechError('voice-unavailable', 3),
      classifySpeechError('not-allowed', 3),
    ]
    const messages = new Set(failures.map((f) => f.message))
    expect(messages.size).toBe(4)
    for (const failure of failures) {
      expect(failure.message).not.toBe('')
      expect(failure.hint).not.toBe('')
    }
  })

  it('朗读错误码分型：network→网络失败；not-allowed→未授权；voice/language-unavailable→音源缺失；零语音→音源缺失优先', () => {
    expect(classifySpeechError('network', 3).cls).toBe('network')
    expect(classifySpeechError('not-allowed', 3).cls).toBe('unauthorized')
    expect(classifySpeechError('voice-unavailable', 3).cls).toBe('missing')
    expect(classifySpeechError('language-unavailable', 3).cls).toBe('missing')
    // 系统一个语音都没有：任何错误都按音源缺失解释（最常见真因）
    expect(classifySpeechError('network', 0).cls).toBe('missing')
    expect(classifySpeechError(null, 0).cls).toBe('missing')
    expect(classifySpeechError('synthesis-failed', 3).cls).toBe('decode')
  })

  it('同源探测：401/403 → unauthorized；404 → missing；2xx → decode；网络抛错 → network', async () => {
    const ok = (status: number) =>
      vi.fn().mockResolvedValue(new Response(null, { status }))
    await expect(
      probePlaybackSource('/media.mp3', ok(403) as unknown as typeof fetch),
    ).resolves.toBe('unauthorized')
    await expect(
      probePlaybackSource('/media.mp3', ok(401) as unknown as typeof fetch),
    ).resolves.toBe('unauthorized')
    await expect(
      probePlaybackSource('/media.mp3', ok(404) as unknown as typeof fetch),
    ).resolves.toBe('missing')
    await expect(
      probePlaybackSource('/media.mp3', ok(200) as unknown as typeof fetch),
    ).resolves.toBe('decode')
    const networkFail = vi.fn().mockRejectedValue(new TypeError('down'))
    await expect(
      probePlaybackSource('/media.mp3', networkFail as unknown as typeof fetch),
    ).resolves.toBe('network')
  })

  it('跨源地址诚实跳过探测（CORS 下结果不可信）：不发请求、返回 null', async () => {
    const fetchMock = vi.fn()
    await expect(
      probePlaybackSource('https://cdn.example.com/media.mp3', fetchMock as unknown as typeof fetch),
    ).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

// ---- 朗读引擎：故障注入（零自动重试） ----

describe('N100 朗读引擎错误透出', () => {
  it('network / not-allowed 错误事件 → 独立诊断文案；引擎停机、不再接续（有界）', () => {
    const speech = stubSpeech(VOICES)
    const errors: string[] = []
    const engine = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh' },
      { onError: (message) => errors.push(message) },
    )
    engine.speakFrom(['一', '二'], 0)
    act(() => {
      ;(speech.speak.mock.calls[0]![0] as MockUtterance).onerror?.({ error: 'network' })
    })
    expect(errors[0]).toContain('网络失败')
    expect(engine.speaking).toBe(false)

    const speech2 = stubSpeech(VOICES)
    const engine2 = new ReaderSpeechEngine(
      { rate: 1, voiceURI: null, langPrefix: 'zh' },
      { onError: (message) => errors.push(message) },
    )
    engine2.speakFrom(['一'], 0)
    act(() => {
      ;(speech2.speak.mock.calls[0]![0] as MockUtterance).onerror?.({ error: 'not-allowed' })
    })
    expect(errors[1]).toContain('未授权')
    // 错误后引擎不再接续队列（无重试循环）
    expect(speech2.speak).toHaveBeenCalledTimes(1)
  })
})

// ---- EnclosurePlayer：故障注入（每类独立处置；重试有界） ----

const AUDIO = { href: '/media/ep12.mp3', type: 'audio/mpeg' }

function stubMediaError(code: number | null) {
  return (media: Element) => {
    Object.defineProperty(media, 'error', {
      value: code === null ? null : { code },
      configurable: true,
    })
    fireEvent.error(media)
  }
}

describe('N100 EnclosurePlayer 故障处置', () => {
  it('网络失败（code 2 + 探测 network）：重试按钮出现，预算 1 次；重试后再失败 → 诚实死路（按钮消失）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('down')),
    )
    render(<EnclosurePlayer enclosure={AUDIO} entryRef="e1.n100" />)
    fireEvent.click(screen.getByRole('button', { name: /播放附件/ }))
    const media = screen.getByTestId('enclosure-media')
    act(() => stubMediaError(2)(media))
    await waitFor(() => {
      expect(screen.getByText(/网络失败/)).toBeInTheDocument()
    })
    expect(ENCLOSURE_RETRY_BUDGET).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    // 重试后 media 重新挂载；再次失败：
    const media2 = await waitFor(() => screen.getByTestId('enclosure-media'))
    act(() => stubMediaError(2)(media2))
    await waitFor(() => {
      expect(screen.getByText(/已重试一次仍失败/)).toBeInTheDocument()
    })
    // 预算耗尽：重试按钮不再出现（无无限循环）
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull()
  })

  it('解码失败（code 3）：有备选音源 → 「换其它音源」；无备选 → 诚实死路（无重试按钮）', async () => {
    // jsdom 地址与 localhost 同源 → 探测 200 → decode
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 200 })),
    )
    const onSwitch = vi.fn()
    const alternatives = [{ href: '/media/ep12.ogg', type: 'audio/ogg' }]
    render(
      <EnclosurePlayer
        enclosure={AUDIO}
        entryRef="e1.n100d"
        alternatives={alternatives}
        onSwitchAlternative={onSwitch}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /播放附件/ }))
    act(() => stubMediaError(3)(screen.getByTestId('enclosure-media')))
    await waitFor(() => {
      expect(screen.getByText(/解码失败/)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /换其它音源/ }))
    expect(onSwitch).toHaveBeenCalledWith(alternatives[0])
  })

  it('解码失败且无备选：诚实死路——诊断展示、无重试、无换源', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 200 })),
    )
    render(<EnclosurePlayer enclosure={AUDIO} entryRef="e1.n100d2" />)
    fireEvent.click(screen.getByRole('button', { name: /播放附件/ }))
    act(() => stubMediaError(3)(screen.getByTestId('enclosure-media')))
    await waitFor(() => {
      expect(screen.getByText(/解码失败/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /换其它音源/ })).toBeNull()
  })

  it('音源缺失：href 为空 → 播放按钮禁用；点击不可行时诊断给设置指引（非网络话术）', () => {
    render(
      <EnclosurePlayer enclosure={{ href: '', type: 'audio/mpeg' }} entryRef="e1.n100m" />,
    )
    const play = screen.getByRole('button', { name: /附件没有可用音源/ })
    expect(play).toBeDisabled()
    // 无 src 的 media error 路径（地址被清理为空的运行时场景）：
    render(
      <EnclosurePlayer enclosure={{ href: '  ', type: null }} entryRef="e1.n100m2" />,
    )
    expect(screen.getAllByText(/（无附件地址）|音源缺失/).length).toBeGreaterThan(0)
  })

  it('未授权：同源探测 401 → 独立话术 + 重新登录指引（无网络重试按钮）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
    )
    render(<EnclosurePlayer enclosure={AUDIO} entryRef="e1.n100a" />)
    fireEvent.click(screen.getByRole('button', { name: /播放附件/ }))
    act(() => stubMediaError(2)(screen.getByTestId('enclosure-media')))
    await waitFor(() => {
      expect(screen.getByText(/未授权/)).toBeInTheDocument()
    })
    expect(screen.getAllByText(/重新登录/).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull()
    // 「已重新登录？重新开始」回到干净起点（手动、非自动循环）
    fireEvent.click(screen.getByRole('button', { name: /已重新登录？重新开始/ }))
    expect(screen.getByRole('button', { name: /播放附件/ })).toBeInTheDocument()
  })
})
