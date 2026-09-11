/** local-translator 加固测试（phase2 G1-G4）。
 *
 * 全部用 fake ctor 模拟浏览器 API 形状——按 docs/research/local-translation.md
 * §2 的证据：headless 下 API 不存在（unsupported）、Linux 组件缺口
 * （downloadable + create 抛 NotSupportedError）、activation 消耗
 * （NotAllowedError）。不把 mock 冒充真实浏览器验证（E2E 诚实降级由
 * Playwright smoke 覆盖）。 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createLocalTranslator,
  detectArticleLanguage,
  detectLanguage,
  LocalTranslatorActivationError,
  LocalTranslatorComponentError,
  LocalTranslatorLanguagePairError,
  LocalTranslatorUnsupportedError,
  localTranslatorPairStatus,
  normalizeBcp47,
} from '../lib/local-translator'

type MonitorCb = (event?: { loaded?: number }) => void

interface FakeSetup {
  availabilityResult?: string
  createImpl?: (options: {
    sourceLanguage: string
    targetLanguage: string
    monitor?: (monitor: { addEventListener: (t: string, cb: MonitorCb) => void }) => void
  }) => Promise<{ translate: (t: string) => Promise<string>; destroy?: () => void }>
  detector?: {
    detect: (text: string) => Promise<{ detectedLanguage: string; confidence: number }[]>
  } | null
}

function installFake(setup: FakeSetup = {}): void {
  const progressCbs: MonitorCb[] = []
  const ctor = {
    availability: vi.fn().mockResolvedValue(setup.availabilityResult ?? 'available'),
    create: vi.fn().mockImplementation(async (options) => {
      if (options.monitor) {
        options.monitor({
          addEventListener: (_t: string, cb: MonitorCb) => progressCbs.push(cb),
        })
      }
      return setup.createImpl
        ? await setup.createImpl(options)
        : {
            translate: async (t: string) => `译:${t}`,
            destroy: () => {},
          }
    }),
  }
  const record = ctor as unknown as { __progress: MonitorCb[] }
  record.__progress = progressCbs
  ;(window as unknown as { Translator?: unknown }).Translator = ctor
  if (setup.detector !== undefined) {
    ;(window as unknown as { LanguageDetector?: unknown }).LanguageDetector =
      setup.detector === null ? undefined : { create: async () => setup.detector }
  }
}

function fakeCtor(): { create: ReturnType<typeof vi.fn> } {
  return (window as unknown as { Translator: { create: ReturnType<typeof vi.fn> } })
    .Translator
}

beforeEach(() => {
  delete (window as unknown as { Translator?: unknown }).Translator
  delete (window as unknown as { LanguageDetector?: unknown }).LanguageDetector
})

afterEach(() => {
  delete (window as unknown as { Translator?: unknown }).Translator
  delete (window as unknown as { LanguageDetector?: unknown }).LanguageDetector
})

describe('能力检测三态', () => {
  it('无 ctor → unsupported，create 抛 UnsupportedError', async () => {
    expect(await localTranslatorPairStatus('en', 'zh')).toBe('unsupported')
    await expect(createLocalTranslator('en', 'zh')).rejects.toBeInstanceOf(
      LocalTranslatorUnsupportedError,
    )
  })

  it('unavailable 语言对 → LanguagePairError（不误导为组件问题）', async () => {
    installFake({ availabilityResult: 'unavailable' })
    await expect(createLocalTranslator('en', 'xx')).rejects.toBeInstanceOf(
      LocalTranslatorLanguagePairError,
    )
  })

  it('available → 翻译 + 会话内缓存（同文本零二次调用）', async () => {
    installFake()
    const translator = await createLocalTranslator('en', 'zh')
    expect(await translator.translate('hello')).toBe('译:hello')
    expect(await translator.translate('hello')).toBe('译:hello')
    const ctor = fakeCtor()
    const create = (ctor as unknown as { create: ReturnType<typeof vi.fn> }).create
    expect(create).toHaveBeenCalledTimes(1)
  })
})

describe('G1 错误语义：组件缺口 vs 语言对不支持', () => {
  it('downloadable + create 抛 NotSupportedError → ComponentError（TranslateKit 指引）', async () => {
    installFake({
      availabilityResult: 'downloadable',
      createImpl: async () => {
        throw new DOMException('no backing model', 'NotSupportedError')
      },
    })
    const error = await createLocalTranslator('en', 'zh').catch((e) => e)
    expect(error).toBeInstanceOf(LocalTranslatorComponentError)
    expect(error.message).toContain('chrome://components')
    expect(error.message).toContain('TranslateKit')
  })

  it('available 状态下 create 抛 NotSupportedError → LanguagePairError', async () => {
    installFake({
      availabilityResult: 'available',
      createImpl: async () => {
        throw new DOMException('pair', 'NotSupportedError')
      },
    })
    await expect(createLocalTranslator('en', 'zh')).rejects.toBeInstanceOf(
      LocalTranslatorLanguagePairError,
    )
  })
})

describe('G4 activation 语义', () => {
  it('NotAllowedError → ActivationError（提示需要新的点击）', async () => {
    installFake({
      availabilityResult: 'downloadable',
      createImpl: async () => {
        throw new DOMException('gesture', 'NotAllowedError')
      },
    })
    const error = await createLocalTranslator('en', 'zh').catch((e) => e)
    expect(error).toBeInstanceOf(LocalTranslatorActivationError)
    expect(error.message).toContain('点击')
  })
})

describe('G3 下载进度', () => {
  it('downloadprogress 事件回调 onDownloadProgress（0..1 截断）', async () => {
    installFake({ availabilityResult: 'downloadable' })
    const seen: number[] = []
    const translator = await createLocalTranslator('en', 'zh', {
      onDownloadProgress: (f) => seen.push(f),
    })
    expect(translator).toBeTruthy()
    const ctor = fakeCtor() as unknown as { __progress: MonitorCb[] }
    expect(ctor.__progress).toHaveLength(1)
    ctor.__progress[0]({ loaded: 0.25 })
    ctor.__progress[0]({ loaded: 2 })
    ctor.__progress[0]()
    expect(seen).toEqual([0.25, 1, 0])
  })

  it('不传 onDownloadProgress 时不挂 monitor', async () => {
    installFake({ availabilityResult: 'downloadable' })
    await createLocalTranslator('en', 'zh')
    const ctor = fakeCtor() as unknown as { __progress: MonitorCb[] }
    expect(ctor.__progress).toHaveLength(0)
  })
})

describe('G2 源语言检测', () => {
  it('normalizeBcp47：base language 抽取与非法拒绝', () => {
    expect(normalizeBcp47('en-US')).toBe('en')
    expect(normalizeBcp47('zh-Hans-CN')).toBe('zh')
    expect(normalizeBcp47('EN')).toBe('en')
    expect(normalizeBcp47('')).toBeNull()
    expect(normalizeBcp47('123')).toBeNull()
    expect(normalizeBcp47(null)).toBeNull()
  })

  it('LanguageDetector 存在 → 探测主语言；zh 文本回 zh', async () => {
    installFake({
      detector: { detect: async () => [{ detectedLanguage: 'zh-Hans', confidence: 0.9 }] },
    })
    expect(await detectLanguage('这是一段中文文本')).toBe('zh')
    expect(await detectArticleLanguage('这是一段中文文本的内容抽样')).toBe('zh')
  })

  it('探测失败 / 无检测器 → 诚实回退 fallback（不假装检测成功）', async () => {
    installFake() // 无 LanguageDetector
    expect(await detectLanguage('hello world')).toBeNull()
    expect(await detectArticleLanguage('hello world', 'en')).toBe('en')

    installFake({
      detector: {
        detect: async () => {
          throw new Error('detector failed')
        },
      },
    })
    expect(await detectArticleLanguage('texto español', 'en')).toBe('en')
  })

  it('空抽样 → 直接回退，不调用检测器', async () => {
    expect(await detectArticleLanguage('   ', 'en')).toBe('en')
  })

  it('zh→en：探测 zh 后以 zh 为源语言 create', async () => {
    installFake({
      detector: { detect: async () => [{ detectedLanguage: 'zh', confidence: 0.95 }] },
    })
    await createLocalTranslator(await detectArticleLanguage('中文文章'), 'en')
    const ctor = fakeCtor() as unknown as {
      create: ReturnType<typeof vi.fn>
    }
    expect(ctor.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({ sourceLanguage: 'zh', targetLanguage: 'en' }),
    )
  })
})
