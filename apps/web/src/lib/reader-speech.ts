/** reader-speech — P18 朗读引擎（speechSynthesis 接线的纯逻辑部分）。
 *
 * F19 是「整篇文章一条 utterance」；P18 重构为逐块（段落级）队列：
 * 每个块一条 SpeechSynthesisUtterance（自带 lang/voice/rate），读完一块
 * 在块边界接续下一块——段落跟踪（onBlockChange / data-speech-active 高亮）、
 * 睡眠定时（块边界检查）、变速重读当前段（而非整篇从头）都建立在
 * 块边界之上。顺带缓解 Chrome 长 utterance 静默截断问题（块天然短；
 * 全文仍受 SPEECH_MAX_CHARS 总量上限约束）。
 *
 * 组件侧只做状态机；本模块负责能力检测、声音挑选、utterance 组装与
 * 「从视口顶部段落开始」的文本收集算法（几何输入由调用方注入）。
 * 平台能力缺失 = 按钮诚实禁用，不假装派发。 */

/** 与 Reader 的 ANCHOR_SELECTOR 同源的朗读块选择器（正文段落级元素）。 */
export const SPEECH_BLOCK_SELECTOR = [
  '.lumi-reader-article p',
  '.lumi-reader-article li',
  '.lumi-reader-article pre',
  '.lumi-reader-article blockquote',
  '.lumi-reader-article h1',
  '.lumi-reader-article h2',
  '.lumi-reader-article h3',
  '.lumi-reader-article h4',
  '.lumi-reader-article h5',
  '.lumi-reader-article h6',
].join(', ')

/** 单次朗读文本总量上限（超长utterance在部分引擎会静默失败；逐块队列
 * 按块累计截断，末块截到近似长度——诚实标注为近似值）。 */
export const SPEECH_MAX_CHARS = 20_000

/** 语速档位（segmented 可选值）。 */
export const SPEECH_RATES = [0.75, 1, 1.25, 1.5] as const
export type SpeechRate = (typeof SPEECH_RATES)[number]

/** 睡眠定时档位（分钟；0 = 关）。纯前端计时：monotonic 墙钟 deadline，
 * 只在块边界检查——暂停期间没有块边界，恢复后才停，实际停止可能晚于
 * 设定（诚实语义，面板有说明文案）。 */
export const SPEECH_SLEEP_TIMER_MINUTES = [0, 5, 10, 15, 30] as const

/** 能力检测：speechSynthesis 可用性（jsdom/极老浏览器 → false）。 */
export function speechSynthesisAvailable(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    window.speechSynthesis !== null
  )
}

// ---- 声音挑选 ----

/** 挑选中文声音：优先 zh* 语言；没有任何中文时回退第一个声音。
 * （F19 语义保留；P18 中作为 pickVoice 的「诚实默认」兜底。） */
export function pickChineseVoice(
  voices: SpeechSynthesisVoice[],
): SpeechSynthesisVoice | null {
  return (
    voices.find((v) => v.lang.toLowerCase().startsWith('zh')) ??
    voices[0] ??
    null
  )
}

/** P18 声音挑选：preferredVoiceURI 命中 → 精确 lang 匹配 → lang 前缀
 * 匹配 → 诚实默认（保留 F19 的中文优先，再退第一个声音 → null）。
 * 首选 URI 在系统中已不存在（换设备/声音被卸载）时静默走回退链——
 * 不假装用户选中的声音还在。 */
export function pickVoice(
  voices: SpeechSynthesisVoice[],
  langPrefix: string,
  preferredVoiceURI: string | null = null,
): SpeechSynthesisVoice | null {
  if (voices.length === 0) return null
  if (preferredVoiceURI !== null && preferredVoiceURI !== '') {
    const preferred = voices.find((v) => v.voiceURI === preferredVoiceURI)
    if (preferred !== undefined) return preferred
  }
  const lang = langPrefix.toLowerCase()
  const exact = voices.find((v) => v.lang.toLowerCase() === lang)
  if (exact !== undefined) return exact
  const prefixed = voices.find((v) => v.lang.toLowerCase().startsWith(lang))
  if (prefixed !== undefined) return prefixed
  return pickChineseVoice(voices)
}

/** 按语言分组的系统声音清单（lang 小写为组键，组按 lang 字典序）。
 * voices 参数缺省时读 window.speechSynthesis——voices 异步加载的浏览器
 * 上调用方需自行处理「首次为空」的诚实降级（读起后再取即可，本模块
 * 在每次出声时都会重新 getVoices()）。 */
export interface VoiceGroup {
  lang: string
  voices: SpeechSynthesisVoice[]
}

export function listVoices(voices?: SpeechSynthesisVoice[]): VoiceGroup[] {
  const all =
    voices ?? (speechSynthesisAvailable() ? window.speechSynthesis.getVoices() : [])
  const groups = new Map<string, SpeechSynthesisVoice[]>()
  for (const voice of all) {
    const lang = voice.lang.toLowerCase()
    const bucket = groups.get(lang)
    if (bucket !== undefined) bucket.push(voice)
    else groups.set(lang, [voice])
  }
  return [...groups.entries()]
    .map(([lang, groupVoices]) => ({ lang, voices: groupVoices }))
    .sort((a, b) => a.lang.localeCompare(b.lang))
}

// ---- 归一化（settings store 复用；单一来源在本模块） ----

/** 语速归一化：非法值回退 1。 */
export function normalizeSpeechRate(value: unknown): SpeechRate {
  return (SPEECH_RATES as readonly number[]).includes(value as number)
    ? (value as SpeechRate)
    : 1
}

/** 睡眠定时归一化：仅接受档位值，非法回退 0（关）。 */
export function normalizeSpeechSleepMinutes(value: unknown): number {
  return (SPEECH_SLEEP_TIMER_MINUTES as readonly number[]).includes(value as number)
    ? (value as number)
    : 0
}

// ---- 文本收集（Reader 注入几何） ----

/** 纯计算：朗读起点块索引——「当前段落」= 最后一个已越过视口顶线的块
 * （含恰好跨线的块，从它开始读）；没有任何块越过顶线（全部在视口下方）
 * → 0（从头读）。tops 为文档序块元素的视口相对 top。 */
export function findStartBlockIndex(
  tops: number[],
  viewportTop: number,
  tolerancePx = 8,
): number {
  let start = -1
  for (let i = 0; i < tops.length; i += 1) {
    if (tops[i]! <= viewportTop + tolerancePx) start = i
    else break
  }
  return start < 0 ? 0 : start
}

/** 块文本拼接：过滤空块，双换行分段。（F19 兼容导出；P18 主路径是
 * speakFrom 的逐块队列，不再先拼接。） */
export function joinBlockTexts(texts: string[]): string {
  return texts
    .map((t) => t.trim())
    .filter((t) => t !== '')
    .join('\n\n')
}

/** Reader 侧收集结果：全部块文本（DOM 序，数组下标即块索引）+ 起点
 * 块索引。总量上限由引擎在入队时施加（cap 逻辑单点在 speakFrom）。 */
export interface SpeechCollection {
  texts: string[]
  startIndex: number
}

// ---- 逐块朗读引擎 ----

interface QueuedBlock {
  /** 块在调用方 texts 数组中的原始下标（= DOM 块序，高亮用它）。 */
  index: number
  text: string
}

/** 按总量上限截块：末块截断到剩余预算，其后整块丢弃。空块已在入队前
 * 过滤（调用方保证），此处只管预算。 */
function capQueue(blocks: QueuedBlock[], maxChars: number): QueuedBlock[] {
  const out: QueuedBlock[] = []
  let budget = maxChars
  for (const block of blocks) {
    if (budget <= 0) break
    if (block.text.length <= budget) {
      out.push(block)
      budget -= block.text.length
    } else {
      out.push({ index: block.index, text: block.text.slice(0, budget) })
      budget = 0
    }
  }
  return out
}

/** 纯函数版总量截断（过滤空块 + 末块截断；测试/工具用）。 */
export function capSpeechBlocks(
  texts: string[],
  maxChars: number = SPEECH_MAX_CHARS,
): string[] {
  const trimmed = texts
    .map((text, index) => ({ index, text: text.trim() }))
    .filter((block) => block.text !== '')
  return capQueue(trimmed, maxChars).map((block) => block.text)
}

export interface SpeechEngineConfig {
  rate: SpeechRate
  /** 首选声音 voiceURI；null / '' = 自动（pickVoice：zh 优先）。 */
  voiceURI: string | null
  /** 声音挑选的语言前缀（默认中文场景 'zh'）。 */
  langPrefix: string
}

export interface SpeechBlockInfo {
  /** 块在调用方 texts 数组中的下标（= DOM 块序）。 */
  index: number
  /** 队列中的位置（1 起）与总块数。 */
  position: number
  total: number
}

export interface SpeechEngineCallbacks {
  /** 一块开始朗读（speak 即通知——部分引擎 onstart 不可靠/jsdom 无此事件）。 */
  onBlockChange?: (block: SpeechBlockInfo) => void
  /** 队列自然读完（手动 stop 不触发——那是用户中止，不是「读完」）。 */
  onEnd?: () => void
  onError?: (message: string) => void
  /** 睡眠定时到点（在块边界干净停止后触发）。 */
  onSleepTimer?: () => void
}

/** P18 逐块朗读引擎。单通道语义与 F19 一致：speakFrom 先 cancel 再入队；
 * stop = cancel + 清队列 + generation 前进作废全部在途回调（已挂到旧
 * utterance 上的 onend/onerror 不再产生任何通知）。 */
export class ReaderSpeechEngine {
  private config: SpeechEngineConfig
  private readonly callbacks: SpeechEngineCallbacks
  private queue: QueuedBlock[] = []
  private queuePos = 0
  /** 会话代次：speakFrom / stop / 重读当前块都前进一代，旧 utterance 的
   * 回调闭包比对代次即可自证过期（Chrome cancel 会异步回放 onend/onerror）。 */
  private generation = 0
  private stopped = true
  private sleepDeadline: number | null = null

  constructor(
    config: SpeechEngineConfig,
    callbacks: SpeechEngineCallbacks = {},
  ) {
    this.config = config
    this.callbacks = callbacks
  }

  /** 是否有进行中的会话（含暂停）。 */
  get speaking(): boolean {
    return !this.stopped
  }

  /** 当前朗读块下标；无会话 → null。 */
  get currentBlockIndex(): number | null {
    if (this.stopped) return null
    return this.queue[this.queuePos]?.index ?? null
  }

  /** 队列进度（1 起 position）；无会话 → null。 */
  get progress(): { position: number; total: number } | null {
    if (this.stopped) return null
    return { position: this.queuePos + 1, total: this.queue.length }
  }

  /** 从 startBlockIndex 块开始逐块朗读（空块跳过，原始下标保留给高亮；
   * 总量受 SPEECH_MAX_CHARS 截断）。先 cancel——单通道语义。 */
  speakFrom(texts: string[], startBlockIndex: number): void {
    this.generation += 1
    const synthesis = window.speechSynthesis
    synthesis.cancel()
    const start = Math.max(0, Math.min(startBlockIndex, texts.length))
    const trimmed = texts
      .map((text, index) => ({ index, text: text.trim() }))
      .filter((block) => block.index >= start && block.text !== '')
    this.queue = capQueue(trimmed, SPEECH_MAX_CHARS)
    this.queuePos = 0
    this.stopped = this.queue.length === 0
    if (this.stopped) return
    this.speakNext()
  }

  /** 睡眠定时：minutes ≤ 0 / null = 关。deadline 从现在起算（会话中途
   * 改设定即重新锚定）。 */
  armSleepTimer(minutes: number | null): void {
    this.sleepDeadline =
      minutes !== null && minutes > 0 ? Date.now() + minutes * 60_000 : null
  }

  pause(): void {
    if (this.stopped) return
    window.speechSynthesis.pause()
  }

  resume(): void {
    if (this.stopped) return
    window.speechSynthesis.resume()
  }

  /** 停止：cancel + 清队列 + 睡眠定时一并解除；generation 前进作废在途
   * 回调。幂等（重复 stop 无害）。平台能力缺失时只清内部状态（卸载
   * 清理路径晚于全局 mock 拆除也不抛错）。 */
  stop(): void {
    this.generation += 1
    this.stopped = true
    this.queue = []
    this.queuePos = 0
    this.sleepDeadline = null
    if (speechSynthesisAvailable()) window.speechSynthesis.cancel()
  }

  /** 更新 rate / voice 配置；朗读中 → 取消当前块并按新配置重读当前块
   * （P18：段落跟踪使重读停在当前段，不再整篇从头）。 */
  setConfig(patch: Partial<SpeechEngineConfig>): void {
    this.config = { ...this.config, ...patch }
    if (!this.stopped) this.restartCurrentBlock()
  }

  private restartCurrentBlock(): void {
    this.generation += 1
    window.speechSynthesis.cancel()
    this.speakNext()
  }

  private speakNext(): void {
    if (this.stopped) return
    // 睡眠定时只在块边界检查（monotonic 墙钟）。暂停期间没有块边界，
    // 恢复后才可能停——实际停止可能晚于设定时长（面板有诚实说明）。
    if (this.sleepDeadline !== null && Date.now() >= this.sleepDeadline) {
      const onSleepTimer = this.callbacks.onSleepTimer
      this.stop()
      onSleepTimer?.()
      return
    }
    const entry = this.queue[this.queuePos]
    if (entry === undefined) {
      this.finish()
      return
    }
    const gen = this.generation
    const synthesis = window.speechSynthesis
    const utterance = new SpeechSynthesisUtterance(entry.text)
    utterance.rate = this.config.rate
    // 每块出声前重取 getVoices()——voices 异步加载的浏览器在会话中途
    // 也能拿到晚到的声音（下一块即生效）。
    const voice = pickVoice(
      synthesis.getVoices(),
      this.config.langPrefix,
      this.config.voiceURI,
    )
    if (voice !== null) {
      utterance.voice = voice
      utterance.lang = voice.lang
    } else {
      utterance.lang = 'zh-CN'
    }
    utterance.onend = () => {
      if (gen !== this.generation) return
      this.queuePos += 1
      this.speakNext()
    }
    utterance.onerror = () => {
      if (gen !== this.generation) return
      const onError = this.callbacks.onError
      this.stop()
      onError?.('朗读失败，请重试。')
    }
    synthesis.speak(utterance)
    this.callbacks.onBlockChange?.({
      index: entry.index,
      position: this.queuePos + 1,
      total: this.queue.length,
    })
  }

  private finish(): void {
    this.generation += 1
    this.stopped = true
    this.queue = []
    this.queuePos = 0
    this.sleepDeadline = null
    this.callbacks.onEnd?.()
  }
}

// ---- F19 兼容 API（CommandPalette 等既有调用方） ----

export interface SpeakOptions {
  rate: SpeechRate
  onEnd?: () => void
  onError?: (message: string) => void
}

/** 朗读一段文本（先 cancel 既有 utterance——单通道语义）。
 * F19 语义保留：内部走逐块引擎（单块入队）。 */
export function speakText(text: string, options: SpeakOptions): void {
  const engine = new ReaderSpeechEngine(
    { rate: options.rate, voiceURI: null, langPrefix: 'zh' },
    { onEnd: options.onEnd, onError: options.onError },
  )
  engine.speakFrom([text], 0)
}

// ---- 当前块 DOM 标记（段落高亮） ----

/** 给当前朗读块打 data-speech-active（正文左侧 accent 细条，CSS 无动画
 * 无布局位移）。index 与 SPEECH_BLOCK_SELECTOR 在 .lumi-reader-article
 * 内的查询序一致；null = 清除标记。文章未挂载时为无操作。 */
export function markSpeechBlockElement(blockIndex: number | null): void {
  if (typeof document === 'undefined') return
  const article = document.querySelector('.lumi-reader-article')
  if (article === null) return
  article.querySelectorAll('[data-speech-active]').forEach((el) => {
    el.removeAttribute('data-speech-active')
  })
  if (blockIndex === null) return
  const blocks = article.querySelectorAll(SPEECH_BLOCK_SELECTOR)
  blocks[blockIndex]?.setAttribute('data-speech-active', '')
}
