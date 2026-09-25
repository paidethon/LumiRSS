/** dict-lookup — N069 选词双语词典卡（web-only，纯逻辑核心）。
 *
 * 隐私边界（硬约束）：
 * - 无外部服务可用「没有配置」时的诚实默认：settings.dictApiUrl 为空 →
 *   卡片显示「未配置词典来源」+ 设置提示，绝不发任何请求；
 * - 查询只发送所选的**单个词**（URL 模板中的 {word} 占位符），绝不携带
 *   选区上下文 / 文章内容 / 标题；
 * - 离线（navigator.onLine === false）→ 显示「本机离线：无可用词典」，
 *   不发请求（可测）；
 * - 用户自行配置词典端点（自托管 / 自选服务商），Lumi 不内置任何默认
 *   上游——外发目的地永远由用户显式决定。
 *
 * 词典响应形态各异（FreeDictionary API / 自建服务 / 各种 CE API），解析
 * 按常见键宽容提取（term/phonetic/translation/definition/meaning…），
 * 提取不到时诚实回退展示原始片段（截断），不假装结构化。 */

/** 词典端点配置上限（URL 模板长度）。 */
export const DICT_API_URL_MAX = 500

/** 未配置时的设置提示（诚实：外发目的地由用户显式配置）。 */
export const DICT_SETUP_HINT =
  '在 设置 → 阅读 → 选词词典 填入词典 API 地址模板（需含 {word} 占位符）。查询只会发送所选单词本身。'

/** 离线提示补充（诚实：不假装有离线词库）。 */
export const DICT_OFFLINE_HINT = '恢复联网后可重试；Lumi 不内置离线词库。'

/** 词典配置归一化（settings store 复用）：空 → ''；非法协议 / 缺
 * {word} 占位符 → ''（诚实回退未配置，不猜测）。 */
export function normalizeDictApiUrl(value: unknown): string {
  if (typeof value !== 'string') return ''
  const trimmed = value.trim().slice(0, DICT_API_URL_MAX)
  if (trimmed === '') return ''
  if (!trimmed.includes('{word}')) return ''
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return ''
    if (parsed.hostname === '') return ''
  } catch {
    return ''
  }
  return trimmed
}

export interface DictWordRange {
  start: number
  end: number
}

/** 选词归一化：仅接受「单个词」——
 * - 不含空白（多词选区 → null，不弹卡）；
 * - CJK 连续串 1–3 字（词级，与任务「≤3 tokens」口径一致）；
 * - 拉丁字母词（含内部连字符/撇号）1–24 字符；
 * 返回 null 表示不是可查词（调用方不弹卡）。 */
export function normalizeDictWord(text: string): string | null {
  if (typeof text !== 'string') return null
  const trimmed = text.trim()
  if (trimmed === '' || /\s/.test(trimmed)) return null
  if (/^[\p{Script=Han}]+$/u.test(trimmed)) {
    return trimmed.length <= 3 ? trimmed : null
  }
  if (/^[A-Za-z][A-Za-z'’-]*$/.test(trimmed)) {
    return trimmed.length <= 24 ? trimmed : null
  }
  return null
}

/** 由模板构造查询 URL：{word} → encodeURIComponent(word)。模板非法 →
 * null（调用方按未配置处理）。URL 里只有单词本身，无任何上下文。 */
export function buildDictUrl(template: string, word: string): string | null {
  const normalized = normalizeDictApiUrl(template)
  if (normalized === '') return null
  return normalized.replace(/\{word\}/g, encodeURIComponent(word))
}

export interface DictEntry {
  /** 词头（响应给出时展示；缺失回退查询词）。 */
  term: string | null
  /** 音标（可选）。 */
  phonetic: string | null
  /** 释义/翻译列表（宽容提取，≤5 条）。 */
  meanings: string[]
  /** 来源主机（诚实展示「来自哪里」）。 */
  source: string
}

export type DictQueryResult =
  | { status: 'offline' }
  | { status: 'unconfigured' }
  | { status: 'error'; message: string }
  | { status: 'done'; entry: DictEntry; /** 原始片段回退（结构化提取失败时） */ raw?: string }

const MEANING_KEYS = [
  'translation',
  'translations',
  'definition',
  'definitions',
  'meaning',
  'meanings',
  'explain',
  'senses',
] as const

const PHONETIC_KEYS = ['phonetic', 'pronunciation', 'us-phonetic', 'uk-phonetic'] as const
const TERM_KEYS = ['word', 'term', 'query', 'text'] as const

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

/** 从（不可信的）JSON 对象宽容提取词典字段。 */
export function parseDictJson(data: unknown, fallbackTerm: string): DictEntry {
  const record =
    typeof data === 'object' && data !== null ? (data as Record<string, unknown>) : {}
  let term: string | null = null
  for (const key of TERM_KEYS) {
    term = asString(record[key])
    if (term !== null) break
  }
  let phonetic: string | null = null
  for (const key of PHONETIC_KEYS) {
    phonetic = asString(record[key])
    if (phonetic !== null) break
  }
  const meanings: string[] = []
  const collect = (value: unknown): void => {
    if (meanings.length >= 5 || value === null || value === undefined) return
    if (typeof value === 'string') {
      const text = value.trim()
      if (text !== '') meanings.push(text.slice(0, 200))
      return
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (meanings.length >= 5) break
        collect(item)
      }
      return
    }
    if (typeof value === 'object') {
      const obj = value as Record<string, unknown>
      for (const key of MEANING_KEYS) {
        if (meanings.length >= 5) break
        if (key in obj) collect(obj[key])
      }
      if (meanings.length === 0) {
        collect(asString(obj.text) ?? asString(obj.sense))
      }
    }
  }
  for (const key of MEANING_KEYS) {
    if (meanings.length >= 5) break
    if (key in record) collect(record[key])
  }
  return {
    term: term ?? (fallbackTerm !== '' ? fallbackTerm : null),
    phonetic,
    meanings: meanings.slice(0, 5),
    source: '',
  }
}

/** 查询词典（编排入口）。`online` 由调用方注入（navigator.onLine），
 * fetchImpl 可注入（测试）；10s 超时，AbortSignal 取消。 */
export async function queryDict(
  template: string,
  word: string,
  options: {
    online: boolean
    fetchImpl?: typeof fetch
    timeoutMs?: number
    signal?: AbortSignal
  },
): Promise<DictQueryResult> {
  if (!options.online) return { status: 'offline' }
  const url = buildDictUrl(template, word)
  if (url === null) return { status: 'unconfigured' }
  const doFetch = options.fetchImpl ?? fetch
  const timeoutMs = options.timeoutMs ?? 10_000
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  if (options.signal !== undefined) {
    if (options.signal.aborted) controller.abort()
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true })
  }
  try {
    const response = await doFetch(url, { signal: controller.signal })
    if (!response.ok) {
      return { status: 'error', message: `词典查询失败（HTTP ${response.status}）` }
    }
    const text = await response.text()
    let entry: DictEntry
    let raw: string | undefined
    try {
      entry = parseDictJson(JSON.parse(text), word)
    } catch {
      // 非 JSON：诚实展示原始片段（截断），不假装结构化
      entry = { term: word, phonetic: null, meanings: [], source: '' }
      raw = text.trim().slice(0, 300)
    }
    let source = ''
    try {
      source = new URL(url).hostname
    } catch {
      source = ''
    }
    return { status: 'done', entry: { ...entry, source }, raw }
  } catch (error) {
    if (controller.signal.aborted) {
      return { status: 'error', message: '词典查询超时，请稍后重试。' }
    }
    return {
      status: 'error',
      message: error instanceof Error ? error.message : '词典查询失败',
    }
  } finally {
    clearTimeout(timer)
  }
}
