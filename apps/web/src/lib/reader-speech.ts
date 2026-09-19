/** reader-speech — F19 朗读（speechSynthesis 接线的纯逻辑部分）。
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

/** 单次朗读文本上限（超长 utterance 在部分引擎会静默失败；截断并在
 * 注释中诚实标注：截到段尾附近的近似长度）。 */
export const SPEECH_MAX_CHARS = 20_000

/** 语速档位（segmented 可选值）。 */
export const SPEECH_RATES = [0.75, 1, 1.25, 1.5] as const
export type SpeechRate = (typeof SPEECH_RATES)[number]

/** 能力检测：speechSynthesis 可用性（jsdom/极老浏览器 → false）。 */
export function speechSynthesisAvailable(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    window.speechSynthesis !== null
  )
}

/** 挑选中文声音：优先 zh* 语言；没有任何中文时回退第一个声音。 */
export function pickChineseVoice(
  voices: SpeechSynthesisVoice[],
): SpeechSynthesisVoice | null {
  return (
    voices.find((v) => v.lang.toLowerCase().startsWith('zh')) ??
    voices[0] ??
    null
  )
}

export interface SpeakOptions {
  rate: SpeechRate
  onEnd?: () => void
  onError?: (message: string) => void
}

/** 朗读一段文本（先 cancel 既有 utterance——单通道语义）。
 * 声音优先 zh；onerror 透出消息（诚实失败，不假装在读）。 */
export function speakText(text: string, options: SpeakOptions): void {
  const synthesis = window.speechSynthesis
  synthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.rate = options.rate
  const voice = pickChineseVoice(synthesis.getVoices())
  if (voice !== null) {
    utterance.voice = voice
    utterance.lang = voice.lang
  } else {
    utterance.lang = 'zh-CN'
  }
  utterance.onend = () => options.onEnd?.()
  utterance.onerror = () => options.onError?.('朗读失败，请重试。')
  synthesis.speak(utterance)
}

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

/** 块文本拼接：过滤空块，双换行分段。 */
export function joinBlockTexts(texts: string[]): string {
  return texts
    .map((t) => t.trim())
    .filter((t) => t !== '')
    .join('\n\n')
}
