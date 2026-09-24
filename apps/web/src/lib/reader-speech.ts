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

// ---- NF1 N095：发音词典（设备本地；只作用于出声文本，展示不动） ----

export interface SpeechLexiconEntry {
  /** 匹配串：普通子串，大小写不敏感。 */
  match: string
  /** 替换为（可为空串 = 静音删词）。 */
  replace: string
}

/** 词典容量上限（超出拒绝新增——设置面板给出诚实提示）。 */
export const SPEECH_LEXICON_CAP = 50

/** 词典归一化：逐条校验（match 非空 trim、replace 为字符串）、按 match
 * 去重（大小写不敏感）、截断到容量上限。非法条目丢弃而非崩掉设置。 */
export function normalizeSpeechLexicon(raw: unknown): SpeechLexiconEntry[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: SpeechLexiconEntry[] = []
  for (const item of raw.slice(0, SPEECH_LEXICON_CAP)) {
    if (typeof item !== 'object' || item === null) continue
    const e = item as Record<string, unknown>
    const match = typeof e.match === 'string' ? e.match.trim() : ''
    if (match === '') continue
    const key = match.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      match,
      replace: typeof e.replace === 'string' ? e.replace : '',
    })
  }
  return out
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** 把词典应用到一段出声文本（顺序应用；子串、大小写不敏感）。
 * 只在朗读/试听路径调用——文章展示 DOM 永不经过这里。 */
export function applySpeechLexicon(
  text: string,
  lexicon: readonly SpeechLexiconEntry[],
): string {
  let out = text
  for (const entry of lexicon) {
    if (entry.match === '') continue
    out = out.replace(new RegExp(escapeRegExp(entry.match), 'gi'), entry.replace)
  }
  return out
}

// ---- NF1 N097：原文译文交替听读（原文 → 译文 → 下一块原文…） ----

/** 交替听读的原文/译文间隔档位（无/短/长 → 0/500/1200ms；定时器实现，
 * 不占 utterance）。 */
export const SPEECH_BILINGUAL_GAPS = [
  { key: 'none', ms: 0, label: '无' },
  { key: 'short', ms: 500, label: '短' },
  { key: 'long', ms: 1200, label: '长' },
] as const

export type SpeechBilingualGap = (typeof SPEECH_BILINGUAL_GAPS)[number]['key']

export function bilingualGapMs(key: SpeechBilingualGap): number {
  return SPEECH_BILINGUAL_GAPS.find((g) => g.key === key)?.ms ?? 0
}

/** 间隔档位归一化：非法值回退 'none'。 */
export function normalizeSpeechBilingualGap(value: unknown): SpeechBilingualGap {
  return SPEECH_BILINGUAL_GAPS.some((g) => g.key === value)
    ? (value as SpeechBilingualGap)
    : 'none'
}

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

// ---- NF1 N094：听读内容排除（设备本地开关；展示不动，只影响收集） ----

export interface SpeechExclusions {
  skipCode: boolean
  skipTables: boolean
  skipFootnotes: boolean
  skipCaptions: boolean
  /** 纯链接段落：可见文本全部来自 <a>（至少含一个链接）——通常是
   * 「阅读原文」式导航噪声。 */
  skipLinkOnly: boolean
}

export const DEFAULT_SPEECH_EXCLUSIONS: SpeechExclusions = {
  skipCode: false,
  skipTables: false,
  skipFootnotes: false,
  skipCaptions: false,
  skipLinkOnly: false,
}

/** 纯链接判定：克隆后移除全部 <a>，剩余可见文本为空且原块至少含一个
 * 链接。 */
function isLinkOnlyBlock(el: Element): boolean {
  if (el.querySelector('a') === null) return false
  const clone = el.cloneNode(true) as Element
  clone.querySelectorAll('a').forEach((a) => a.remove())
  return (clone.textContent ?? '').trim() === ''
}

/** 单块排除判定（纯函数；closest 启发式与 sanitize 产物解耦）。 */
export function isExcludedSpeechBlock(
  el: Element,
  exclusions: SpeechExclusions,
): boolean {
  if (exclusions.skipCode && el.closest('pre, code') !== null) return true
  if (exclusions.skipTables && el.closest('table') !== null) return true
  if (
    exclusions.skipFootnotes &&
    el.closest(
      '[role="doc-footnote"], [data-footnote], [class*="footnote" i], [id*="footnote" i]',
    ) !== null
  ) {
    return true
  }
  if (
    exclusions.skipCaptions &&
    (el.closest('figcaption') !== null ||
      el.closest('[class*="caption" i]') !== null)
  ) {
    return true
  }
  if (exclusions.skipLinkOnly && isLinkOnlyBlock(el)) return true
  return false
}

/** 收集参与朗读的块元素：SPEECH_BLOCK_SELECTOR 文档序，过滤排除开关
 * 命中的块。被排除内容在文章里原样保留（只影响朗读范围）。 */
export function collectSpeechBlockElements(
  article: Element,
  exclusions: SpeechExclusions,
): Element[] {
  return Array.from(article.querySelectorAll(SPEECH_BLOCK_SELECTOR)).filter(
    (el) => !isExcludedSpeechBlock(el, exclusions),
  )
}

/** 读一个原文块挂着的译文（translation-blocks overlay：译文节点带
 * data-lb-t="1"，bilingual 配对与 translated/嵌套插入都紧邻原文块的
 * nextElementSibling）。无 overlay / 译文为空 → null（诚实：不做任何
 * 翻译调用）。 */
export function blockTranslationText(el: Element): string | null {
  const sib = el.nextElementSibling
  if (sib === null || !sib.matches('[data-lb-t="1"]')) return null
  const text = (sib.textContent ?? '').trim()
  return text === '' ? null : text
}

/** Reader 侧收集结果：全部块文本（DOM 序，数组下标即块索引）+ 起点
 * 块索引。总量上限由引擎在入队时施加（cap 逻辑单点在 speakFrom）。 */
export interface SpeechCollection {
  texts: string[]
  startIndex: number
  /** NF1：与 texts 平行的块定位——元素 + 其在 SPEECH_BLOCK_SELECTOR
   * 文档序中的下标（= 高亮/书签/选区共享的块 id）。启用排除后 texts
   * 下标与 selectorIndex 不再相同，UI 一律以 selectorIndex 为准；
   * 缺省（旧调用方）时块 id = texts 下标。 */
  blocks?: { element: Element; selectorIndex: number }[]
  /** NF1：与 texts 平行的译文文本（无 overlay / 该块无译文 → null；
   * 交替听读开启时才会被消费）。 */
  translations?: (string | null)[]
}

/** 完整收集（Reader 接线 + 测试共用的单一实现）：容器注入几何，设置
 * 快照注入排除/词典。返回的 startIndex 已是 selectorIndex 语义。 */
export function collectSpeechCollection(
  container: HTMLElement,
  article: Element,
  options: { exclusions: SpeechExclusions; lexicon: readonly SpeechLexiconEntry[] },
): SpeechCollection | null {
  const kept = collectSpeechBlockElements(article, options.exclusions)
  if (kept.length === 0) return null
  const containerTop = container.getBoundingClientRect().top
  const tops = kept.map((block) => block.getBoundingClientRect().top)
  const localStart = findStartBlockIndex(tops, containerTop)
  const texts = kept.map((block) =>
    applySpeechLexicon(block.textContent ?? '', options.lexicon),
  )
  if (texts.slice(localStart).every((text) => text.trim() === '')) return null
  const positions = new Map<Element, number>()
  Array.from(article.querySelectorAll(SPEECH_BLOCK_SELECTOR)).forEach(
    (el, i) => {
      positions.set(el, i)
    },
  )
  const blocks = kept.map((element, i) => ({
    element,
    selectorIndex: positions.get(element) ?? i,
  }))
  const translations = kept.map((element) => blockTranslationText(element))
  return {
    texts,
    startIndex: blocks[localStart]?.selectorIndex ?? 0,
    blocks,
    translations,
  }
}

/** NF1：由收集结果构建引擎队列条目。bilingual 开启时每个有译文的块
 * 产生 [原文, 译文] 相邻条目（同 blockIndex；缺译文诚实跳过——不补
 * 空档、不发起任何翻译）。blockIndex 取 selectorIndex（无 blocks 时
 * 回退 texts 下标——既有调用方语义不变）。 */
export interface SpeechQueueItem {
  text: string
  /** 块 id（SPEECH_BLOCK_SELECTOR 文档序下标）：高亮/进度/书签共用。 */
  blockIndex: number
  /** true = 该条目是所在块的译文（原文 → 译文间隔由引擎按档位插入）。 */
  isTranslation?: boolean
}

export function buildSpeechQueue(
  collection: SpeechCollection,
  options: { bilingual?: boolean } = {},
): SpeechQueueItem[] {
  const items: SpeechQueueItem[] = []
  const translations = collection.translations
  for (let i = 0; i < collection.texts.length; i += 1) {
    const text = collection.texts[i] ?? ''
    if (text.trim() === '') continue
    const blockIndex = collection.blocks?.[i]?.selectorIndex ?? i
    items.push({ text, blockIndex })
    if (options.bilingual === true && translations !== undefined) {
      const trans = translations[i]
      if (typeof trans === 'string' && trans.trim() !== '') {
        items.push({ text: trans, blockIndex, isTranslation: true })
      }
    }
  }
  return items
}

/** NF1 N091：把文档选区映射到朗读块 id（selectorIndex）。选区锚点必须
 * 在容器内，且不在 pre/code/table 内——代码与表格从不作为「从此处朗读」
 * 的起点（产品规则：代码读出来没有意义；表格本就不在
 * SPEECH_BLOCK_SELECTOR 里）。命中收集结果里的块才返回；否则 null。 */
export function speechBlockIndexForSelection(
  selection: Selection,
  container: Element,
  blocks: readonly { element: Element; selectorIndex: number }[],
): number | null {
  if (
    selection.rangeCount === 0 ||
    selection.isCollapsed ||
    typeof selection.getRangeAt !== 'function'
  ) {
    return null
  }
  const range = selection.getRangeAt(0)
  const common = range.commonAncestorContainer
  const el =
    common.nodeType === Node.ELEMENT_NODE
      ? (common as Element)
      : common.parentElement
  if (el === null || !container.contains(el)) return null
  if (el.closest('pre, code, table') !== null) return null
  let cur: Element | null = el
  while (cur !== null && container.contains(cur)) {
    const hit = blocks.find((b) => b.element === cur)
    if (hit !== undefined) return hit.selectorIndex
    cur = cur.parentElement
  }
  return null
}

// ---- 逐块朗读引擎 ----

/** 队列条目（NF1：由 {index, text} 泛化为 SpeechQueueItem——blockIndex
 * 是高亮/书签/选区共享的块 id，译文条目与原文条目共享同一 blockIndex）。 */
type QueuedBlock = SpeechQueueItem

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
      out.push({ ...block, text: block.text.slice(0, budget) })
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
    .map((text, index) => ({ blockIndex: index, text: text.trim() }))
    .filter((block) => block.text !== '')
  return capQueue(trimmed, maxChars).map((block) => block.text)
}

export interface SpeechEngineConfig {
  rate: SpeechRate
  /** 首选声音 voiceURI；null / '' = 自动（pickVoice：zh 优先）。 */
  voiceURI: string | null
  /** 声音挑选的语言前缀（默认中文场景 'zh'）。 */
  langPrefix: string
  /** NF1 N097：原文 → 译文间隔毫秒数（仅译文条目前插入；0 = 无间隔）。 */
  interPairGapMs?: number
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
  /** NF1 N097：原文 → 译文间隔定时器（stop/finish 清除；代次比对兜底）。 */
  private gapTimer: ReturnType<typeof setTimeout> | null = null

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

  /** 当前朗读块下标（块 id，见 SpeechQueueItem.blockIndex）；无会话 → null。 */
  get currentBlockIndex(): number | null {
    if (this.stopped) return null
    return this.queue[this.queuePos]?.blockIndex ?? null
  }

  /** 队列进度（1 起 position）；无会话 → null。 */
  get progress(): { position: number; total: number } | null {
    if (this.stopped) return null
    return { position: this.queuePos + 1, total: this.queue.length }
  }

  /** 从 startBlockIndex 块开始逐块朗读（空块跳过，原始下标保留给高亮；
   * 总量受 SPEECH_MAX_CHARS 截断）。先 cancel——单通道语义。 */
  speakFrom(texts: string[], startBlockIndex: number): void {
    this.speakQueue(
      texts.map((text, index) => ({ text, blockIndex: index })),
      startBlockIndex,
    )
  }

  /** NF1：显式队列条目版 speakFrom——交替听读（同块原文/译文相邻条目）、
   * 排除/词典后的块 id 对齐都经这里入队。条目按 blockIndex ≥ start 过滤
   * （与 speakFrom 的下标过滤同语义，只是块 id 与队列位置解耦）。 */
  speakQueue(items: SpeechQueueItem[], startBlockIndex: number): void {
    this.generation += 1
    this.clearGapTimer()
    const synthesis = window.speechSynthesis
    synthesis.cancel()
    const start = Math.max(0, startBlockIndex)
    const trimmed = items
      .map((item) => ({ ...item, text: item.text.trim() }))
      .filter((item) => item.blockIndex >= start && item.text !== '')
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
    this.clearGapTimer()
    if (speechSynthesisAvailable()) window.speechSynthesis.cancel()
  }

  /** 更新 rate / voice / 间隔配置；朗读中 → 取消当前块并按新配置重读
   * 当前块（P18：段落跟踪使重读停在当前段，不再整篇从头）。 */
  setConfig(patch: Partial<SpeechEngineConfig>): void {
    this.config = { ...this.config, ...patch }
    if (!this.stopped) this.restartCurrentBlock()
  }

  private restartCurrentBlock(): void {
    this.generation += 1
    this.clearGapTimer()
    window.speechSynthesis.cancel()
    this.speakNext()
  }

  private clearGapTimer(): void {
    if (this.gapTimer !== null) {
      clearTimeout(this.gapTimer)
      this.gapTimer = null
    }
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
    // NF1 N097：译文条目前按档位静默（定时器实现；代次比对使 stop/
    // 重读/新会话作废在途定时——到点后不再出声）。
    const gapMs =
      entry.isTranslation === true
        ? Math.max(0, this.config.interPairGapMs ?? 0)
        : 0
    if (gapMs > 0) {
      const gen = this.generation
      this.gapTimer = setTimeout(() => {
        if (gen !== this.generation) return
        this.gapTimer = null
        this.speakEntry(entry)
      }, gapMs)
      return
    }
    this.speakEntry(entry)
  }

  private speakEntry(entry: QueuedBlock): void {
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
      index: entry.blockIndex,
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
    this.clearGapTimer()
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
