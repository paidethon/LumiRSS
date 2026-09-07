/** local-translator — 浏览器内置 Translator API 适配（本机翻译）。
 *
 * 明确的执行位置：这一整条链路只跑在“此浏览器/此设备上”，不经过
 * BFF，不会把正文发往任何服务器。
 *
 * 能力检测三态，绝不假装可用：
 * - unsupported       ：window.Translator 不存在（Firefox/Safari/旧 Chrome）
 * - unavailable       ：该语言对在此浏览器不可用（含不可下载）
 * - needs-download    ：语言对可下载但尚未就绪（create 时会触发下载，
 *                       需要 the user activation——切到双语/译文的那次
 *                       点击即是激活；下载失败如实报错，不静默回退云翻译）
 *
 * 结果只存内存（会话内去重）；页面刷新后按需重新翻译，不写
 * localStorage，不做任何隐式持久化。 */

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
    monitor?: (monitor: { addEventListener: (t: string, cb: () => void) => void }) => void
  }) => Promise<FakeTranslatorInstance>
}

function translatorCtor(): FakeTranslatorConstructor | null {
  const w = window as unknown as {
    Translator?: FakeTranslatorConstructor
  }
  return w.Translator ?? null
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

/** 创建一个本地翻译器；不可用/需下载失败时抛
 * LocalTranslatorUnsupportedError（浏览器安全中文消息由 UI 层映射）。 */
export async function createLocalTranslator(
  sourceLanguage: string,
  targetLanguage: string,
): Promise<LocalTranslator> {
  const ctor = translatorCtor()
  if (ctor === null) {
    throw new LocalTranslatorUnsupportedError(
      '此浏览器不支持本地翻译（需要 Chrome 内置 Translator API）。',
    )
  }
  const state = await availability(sourceLanguage, targetLanguage)
  if (state === 'unavailable' || state === 'unsupported') {
    throw new LocalTranslatorUnsupportedError(
      '此浏览器不支持该语言对的本地翻译。',
    )
  }
  const instance = await ctor.create({ sourceLanguage, targetLanguage })
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
}

/** 能力探测（设置页/工具栏提示用）：不触发下载。 */
export async function localTranslatorPairStatus(
  sourceLanguage: string,
  targetLanguage: string,
): Promise<LocalTranslatorAvailability> {
  return availability(sourceLanguage, targetLanguage)
}
