/** note-sections — N079 笔记与事实分栏（Web 侧纯逻辑）。
 *
 * 与 BFF note_sections.py 同一词表：三栏 facts / interpretation /
 * toVerify，类型标签「[事实]/[个人解读]/[待核实]」逐条渲染。凡把
 * 笔记内容导出/外送的地方（.md 下载、后续 AI 面）一律用本渲染——
 * 绝不把个人判断表述为原文事实。渲染是纯函数，可独立单测。
 */

export const SECTION_KEYS = ['facts', 'interpretation', 'toVerify'] as const

export type NoteSectionKey = (typeof SECTION_KEYS)[number]

export interface NoteSections {
  facts: string[]
  interpretation: string[]
  toVerify: string[]
}

export const SECTION_LABELS: Record<NoteSectionKey, string> = {
  facts: '事实',
  interpretation: '个人解读',
  toVerify: '待核实',
}

export const SECTION_HINTS: Record<NoteSectionKey, string> = {
  facts: '能在原文中指认的陈述',
  interpretation: '读者自己的推断与评价',
  toVerify: '疑点、需要查证的说法',
}

export function emptySections(): NoteSections {
  return { facts: [], interpretation: [], toVerify: [] }
}

/** 把任意（服务端/本地）输入归一化为三栏结构：未知键丢弃、非字符串
 * 条目丢弃、空白条目修剪、每栏 ≤50 条。损坏数据诚实降级，不抛错。 */
export function normalizeSections(input: unknown): NoteSections {
  const out = emptySections()
  if (typeof input !== 'object' || input === null) return out
  const raw = input as Record<string, unknown>
  for (const key of SECTION_KEYS) {
    const value = raw[key]
    if (!Array.isArray(value)) continue
    for (const entry of value) {
      if (typeof entry !== 'string') continue
      const text = entry.trim()
      if (text === '') continue
      out[key].push(text)
      if (out[key].length >= 50) break
    }
  }
  return out
}

/** 把 textarea 按行文本拆成条目（空行丢弃、行内首尾空白修剪）。 */
export function parseSectionText(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

/** 条目列表 → textarea 文本（每条一行；与 parseSectionText 互逆）。 */
export function sectionTextOf(items: string[]): string {
  return items.join('\n')
}

export function sectionsIsEmpty(sections: NoteSections): boolean {
  return SECTION_KEYS.every((key) => sections[key].length === 0)
}

/** AI/导出面的唯一渲染：逐条带类型标签。空栏不出现；全空 → ''。 */
export function renderTypedSections(sections: NoteSections): string {
  const lines: string[] = []
  for (const key of SECTION_KEYS) {
    const label = SECTION_LABELS[key]
    for (const item of sections[key]) {
      lines.push(`[${label}] ${item}`)
    }
  }
  return lines.join('\n')
}

/** 导出（.md）形态：正文 + 类型化分栏。类型随导出走，不丢失。 */
export function exportNoteMarkdown(title: string, contentMd: string, sections: NoteSections): string {
  const parts: string[] = [`# ${title}`, '', contentMd]
  const rendered = renderTypedSections(sections)
  if (rendered !== '') {
    parts.push('', '## 分栏', '', rendered)
  }
  return parts.join('\n') + '\n'
}
