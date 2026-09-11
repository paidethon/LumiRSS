/** local-translator — 浏览器内置 Translator API 适配（本机翻译）。
 *
 * 明确的执行位置：这一整条链路只跑在“此浏览器/此设备上”，不经过
 * BFF，不会把正文发往任何服务器。
 *
 * 能力检测状态机（phase2 G2 加固后），绝不假装可用：
 * - unsupported       ：window.Translator 不存在（Firefox/Safari/旧
 *                       Chrome/一切移动浏览器——官方明确不支持）
 * - unavailable       ：该语言对在此浏览器不可用（含不可下载）
 * - downloadable      ：语言对可下载但尚未就绪（privacy mask 下首次
 *                       create 前一律报 downloadable，不保证真的可得）
 * - downloading       ：create 触发的语言包下载进行中（onDownloadProgress）
 * - available         ：语言对就绪，可翻译
 * - translating / cancelled / error 由 UI 层状态条表达（ReaderTranslation）
 *
 * 错误分型（phase2 G1/G4 加固，全部有真机证据，见
 * docs/research/local-translation.md §2）：
 * - LocalTranslatorUnsupportedError    ：API 不存在（换浏览器才能解决）
 * - LocalTranslatorComponentError      ：TranslateKit 组件未就绪（Linux
 *   真实故障模式：availability=downloadable 但 create 抛
 *   NotSupportedError 且零下载事件）→ 指引 chrome://components
 * - LocalTranslatorActivationError     ：NotAllowedError——一次点击的
 *   user activation 被一次 create 消耗；重试必须来自新的真实点击
 * - LocalTranslatorLanguagePairError   ：该语言对确实不可用
 *
 * 源语言检测（phase2 G2）：createLocalTranslator 不再硬编码 'en'；
 * detectArticleLanguage 用同批内置 LanguageDetector 探测文章主语言，
 * 探测失败诚实回退 'en'。结果只存内存（会话内去重）；页面刷新后按
 * 需重新翻译，不写 localStorage，不做任何隐式持久化。 */

export interface LocalTranslator {
  translate: (text: string, signal?: AbortSignal) => Promise<string>
  destroy: () => void
}

export type LocalTranslatorAvailability =
  | 'available'
  | 'downloadable'
  | 'downloading'
  | 'unavailable'
  | 'unsupported'

interface TranslatorAvailabilityResult {
  available?: string
}

interface FakeTranslatorInstance {
  translate: (text: string, options?: { signal?: AbortSignal }) => Promise<string>
  destroy?: () => void
}

interface FakeTranslatorConstructor {
  availability?: (options: {
    sourceLanguage: string
    targetLanguage: string
  }) => Promise<LocalTranslatorAvailability | TranslatorAvailabilityResult>
  create: (options: {
    sourceLanguage: string
    targetLanguage: string
    monitor?: (monitor: {
      addEventListener: (
        t: string,
        cb: (event?: { loaded?: number }) => void,
      ) => void
    }) => void
  }) => Promise<FakeTranslatorInstance>
}

interface FakeLanguageDetectorInstance {
  detect: (
    text: string,
    options?: object,
  ) => Promise<{ detectedLanguage: string; confidence: number }[]>
}

interface FakeLanguageDetectorConstructor {
  create?: (options?: object) => Promise<FakeLanguageDetectorInstance>
}

function translatorCtor(): FakeTranslatorConstructor | null {
  const w = window as unknown as {
    Translator?: FakeTranslatorConstructor
  }
  return w.Translator ?? null
}

function detectorCtor(): FakeLanguageDetectorConstructor | null {
  const w = window as unknown as {
    LanguageDetector?: FakeLanguageDetectorConstructor
  }
  return w.LanguageDetector ?? null
}

export function localTranslatorAvailable(): boolean {
  return translatorCtor() !== null
}

async function availability(
  sourceLanguage: string,
  targetLanguage: string,
): Promise<LocalTranslatorAvailability> {
  const ctor = translatorCtor()
  if (ctor === null) return 'unsupported'
  if (typeof ctor.availability !== 'function') return 'available'
  const result = await ctor.availability({ sourceLanguage, targetLanguage })
  if (typeof result === 'string') {
    return result as LocalTranslatorAvailability
  }
  return (result.available as LocalTranslatorAvailability) ?? 'unavailable'
}

export class LocalTranslatorUnsupportedError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LocalTranslatorUnsupportedError'
  }
}

/** TranslateKit 组件未就绪（Linux 零售 Chrome 真实故障模式）。
 * availability 报 downloadable 但 create 立刻抛 NotSupportedError、
 * 零下载事件——"downloadable"不等于语言包真的可得。 */
export class LocalTranslatorComponentError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LocalTranslatorComponentError'
  }
}

/** user activation 已被消耗（NotAllowedError）。重试必须来自一次新的
 * 真实点击；effect 链里的自动重试永远会再次失败。 */
export class LocalTranslatorActivationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LocalTranslatorActivationError'
  }
}

/** 该语言对在此浏览器不可用（unavailable）。 */
export class LocalTranslatorLanguagePairError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LocalTranslatorLanguagePairError'
  }
}

function errorName(error: unknown): string | null {
  if (error instanceof DOMException) return error.name
  if (error instanceof Error && error.name !== 'Error') return error.name
  return null
}

export interface CreateLocalTranslatorOptions {
  /** 语言包下载进度（0..1）；仅 downloadable→available 路径触发。 */
  onDownloadProgress?: (fraction: number) => void
}

/** 创建一个本地翻译器；失败按错误分型抛出（浏览器安全中文消息由
 * UI 层映射；此层的消息是兜底文案）。 */
export async function createLocalTranslator(
  sourceLanguage: string,
  targetLanguage: string,
  options: CreateLocalTranslatorOptions = {},
): Promise<LocalTranslator> {
  const ctor = translatorCtor()
  if (ctor === null) {
    throw new LocalTranslatorUnsupportedError(
      '此浏览器不支持本地翻译（需要 Chrome 内置 Translator API）。',
    )
  }
  const state = await availability(sourceLanguage, targetLanguage)
  if (state === 'unsupported') {
    throw new LocalTranslatorUnsupportedError(
      '此浏览器不支持本地翻译（需要 Chrome 内置 Translator API）。',
    )
  }
  if (state === 'unavailable') {
    throw new LocalTranslatorLanguagePairError(
      '此浏览器不支持该语言对的本地翻译。',
    )
  }
  try {
    const instance = await ctor.create({
      sourceLanguage,
      targetLanguage,
      monitor: options.onDownloadProgress
        ? (monitor) => {
            monitor.addEventListener('downloadprogress', (event) => {
              const loaded = event?.loaded
              options.onDownloadProgress?.(
                typeof loaded === 'number' ? Math.min(1, Math.max(0, loaded)) : 0,
              )
            })
          }
        : undefined,
    })
    const cache = new Map<string, string>()
    return {
      async translate(text, signal) {
        const cached = cache.get(text)
        if (cached !== undefined) return cached
        const result = await instance.translate(text, { signal })
        cache.set(text, result)
        return result
      },
      destroy() {
        instance.destroy?.()
      },
    }
  } catch (error) {
    // G1：Linux 组件缺口——downloadable 状态下 create 抛 NotSupportedError
    // 是“TranslateKit 未就绪”，不是“语言对不支持”。
    const name = errorName(error)
    if (name === 'NotAllowedError') {
      throw new LocalTranslatorActivationError(
        '浏览器需要一次新的点击授权才能开始下载语言包，请点击重试。',
      )
    }
    if (name === 'NotSupportedError') {
      if (state === 'downloadable' || state === 'downloading') {
        throw new LocalTranslatorComponentError(
          '浏览器翻译组件未就绪：请打开 chrome://components 更新 TranslateKit（浏览器翻译组件）后重试。',
        )
      }
      throw new LocalTranslatorLanguagePairError(
        '此浏览器不支持该语言对的本地翻译。',
      )
    }
    throw error
  }
}

/** 能力探测（设置页/工具栏提示用）：不触发下载。 */
export async function localTranslatorPairStatus(
  sourceLanguage: string,
  targetLanguage: string,
): Promise<LocalTranslatorAvailability> {
  return availability(sourceLanguage, targetLanguage)
}

// ---------------------------------------------------------------------------
// 源语言检测（phase2 G2）
// ---------------------------------------------------------------------------

/** 归一化到 Translator API 的 base language：'en-US'→'en'，
 * 'zh-Hans-CN'→'zh'；非法输入返回 null。 */
export function normalizeBcp47(tag: string | null | undefined): string | null {
  if (typeof tag !== 'string') return null
  const trimmed = tag.trim()
  if (!trimmed) return null
  const base = trimmed.split('-')[0]?.toLowerCase()
  if (base === undefined || base.length < 2 || base.length > 8) return null
  if (!/^[a-z]{2,3}$/.test(base)) return null
  return base
}

/** 用浏览器内置 LanguageDetector 探测主语言（base language）。
 * 不支持/探测失败/无置信结果 → null（调用方诚实回退，不假装检测成功）。 */
export async function detectLanguage(
  text: string,
): Promise<string | null> {
  const ctor = detectorCtor()
  if (ctor === null) return null
  try {
    let detector: FakeLanguageDetectorInstance
    if (typeof ctor.create === 'function') {
      detector = await ctor.create()
    } else {
      // 规范里 LanguageDetector.create()；防御无 create 的老实现
      return null
    }
    const results = await detector.detect(text)
    if (!Array.isArray(results) || results.length === 0) return null
    const base = normalizeBcp47(results[0]?.detectedLanguage)
    return base
  } catch {
    return null
  }
}

/** 文章主语言探测：抽样正文前 ~600 字符；失败回退 fallback。
 * 文章 lang 元数据由调用方优先传入（articles 常有 <html lang>）。 */
export async function detectArticleLanguage(
  sample: string,
  fallback = 'en',
): Promise<string> {
  const text = sample.slice(0, 600)
  if (!text.trim()) return fallback
  const detected = await detectLanguage(text)
  return detected ?? fallback
}
