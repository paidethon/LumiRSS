/** reading-time — CJK 感知阅读时间估算（0012 Gate 5）。
 *
 * 目标不是“科学上绝对准确”，而是：一致、可测试、对中英文混排明显
 * 比英文 word count 更合理。
 *
 * 算法（速度常量集中定义）：
 * - Han 字符（CJK 统一表意文字 + 扩展 A）按中文阅读速度计；
 * - Latin 词（连续字母/撇号序列）按英文阅读速度计；
 * - 其余字符（标点/空格/数字串按词计等）不单独计速度，避免双重计费；
 * - minutes = max(1, ceil(cjk / CJK_WPM + latinWords / LATIN_WPM))，
 *   非常短文章最低显示 1 分钟（由 formatReadingTime 输出「< 1 分钟」）。 */

// ---- 速度常量（集中定义；参考常见阅读研究的大众区间取中值） ----

/** 中文阅读速度：字/分钟（一般读者 250–400 区间取保守中值）。 */
export const CJK_CHARS_PER_MINUTE = 300
/** 英文阅读速度：词/分钟（一般读者 200–260 区间取保守中值）。 */
export const LATIN_WORDS_PER_MINUTE = 220

export interface ReadingTimeEstimate {
  /** 向上取整后的整分钟数，最短文章为 1（展示层用 formatReadingTime）。 */
  minutes: number
  /** Han / 中文字符数。 */
  cjkCharacters: number
  /** Latin 单词数。 */
  latinWords: number
}

/** Han 字符：CJK 统一表意文字（U+4E00–U+9FFF）+ 扩展 A（U+3400–U+4DBF）。
 * 不含标点/谚文/假名——本产品面向中文正文，粒度足够且行为可预测。 */
const HAN_RE = /[\u3400-\u4dbf\u4e00-\u9fff]/g
/** Latin 词：连续拉丁字母（含撇号，如 don't）。 */
const LATIN_WORD_RE = /[A-Za-z]+(?:['’][A-Za-z]+)*/g

/** 估算中英混排文本的阅读时间（纯函数）。 */
export function estimateReadingTime(text: string): ReadingTimeEstimate {
  const cjkCharacters = (text.match(HAN_RE) ?? []).length
  const latinWords = (text.match(LATIN_WORD_RE) ?? []).length
  const raw =
    cjkCharacters / CJK_CHARS_PER_MINUTE + latinWords / LATIN_WORDS_PER_MINUTE
  return {
    minutes: Math.max(1, Math.ceil(raw)),
    cjkCharacters,
    latinWords,
  }
}

/** 展示格式：非常短文章显示「< 1 分钟」，其余「约 N 分钟」。
 * minutes 由 estimateReadingTime 保证 >= 1；isVeryShort 判定基于原始
 * 计算值 < 1（即原始不足 1 分钟被抬到 1 的场景）。 */
export function formatReadingTime(text: string): string {
  const cjkCharacters = (text.match(HAN_RE) ?? []).length
  const latinWords = (text.match(LATIN_WORD_RE) ?? []).length
  const raw =
    cjkCharacters / CJK_CHARS_PER_MINUTE + latinWords / LATIN_WORDS_PER_MINUTE
  if (raw < 1) return '< 1 分钟'
  return `约 ${Math.ceil(raw)} 分钟`
}

// ---- F075：剩余阅读时间（进度条联动） ----

/** 阅读速度（可校准接口）：默认速度 = 上面两个全局常量；F051 校准速度
 * （timeline 域）落地后可传入实测速度替换，调用方接口不变。 */
export interface ReadingSpeed {
  cjkPerMinute: number
  latinWordsPerMinute: number
}

export const DEFAULT_READING_SPEED: ReadingSpeed = {
  cjkPerMinute: CJK_CHARS_PER_MINUTE,
  latinWordsPerMinute: LATIN_WORDS_PER_MINUTE,
}

export interface RemainingTimeInput {
  /** 全文文本（评估输入，同 estimateReadingTime）。 */
  text: string
  /** 已读进度（0–1；非法值按 0 处理）。 */
  ratio: number
  /** 阅读速度（缺省 = 默认速度；预留 F051 校准速度接口）。 */
  speed?: ReadingSpeed
}

/** 纯计算：按当前进度估算剩余阅读分钟数（进度 1 → 0；不足 1 分钟
 * 的余量向上取整为 1，进度为 0 时返回全文估时）。 */
export function estimateRemainingMinutes(input: RemainingTimeInput): number {
  const speed = input.speed ?? DEFAULT_READING_SPEED
  const cjk = (input.text.match(HAN_RE) ?? []).length
  const latin = (input.text.match(LATIN_WORD_RE) ?? []).length
  const totalMinutes = cjk / speed.cjkPerMinute + latin / speed.latinWordsPerMinute
  const ratio =
    Number.isFinite(input.ratio) ? Math.min(1, Math.max(0, input.ratio)) : 0
  const remaining = totalMinutes * (1 - ratio)
  if (remaining <= 0) return 0
  return Math.max(1, Math.ceil(remaining))
}

/** 从已 sanitize 的文章 HTML 提取纯文本（评估输入用）：
 * 先移除 script/style（jsdom 的 DOMParser 会保留其文本），
 * 块级闭合边界补空格（避免词粘连影响词数），空格归一。 */
export function textFromHtml(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  doc.querySelectorAll('script, style').forEach((el) => el.remove())
  const spaced = doc.body.innerHTML.replace(/<\/(?:p|div|li|h[1-6])>/gi, ' ')
  const tmp = new DOMParser().parseFromString(spaced, 'text/html')
  return (tmp.body.textContent ?? '').replace(/\s+/g, ' ').trim()
}
