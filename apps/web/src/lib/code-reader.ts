/** code-reader — N057 代码块独立阅读页的纯辅助（无 DOM 副作用）。
 *
 * 长代码块（> CODE_READER_MIN_LINES 行）在正文里出现「展开代码」入口，
 * 打开独立面板：行号栏 + 面板内搜索（匹配跳转）+ 横向滚动保持 +
 * 复制（复用 lib/code-copy 的 codeBlockText，空白原样保留）。
 * 行匹配/计数在此模块保持可测试；DOM 装饰与面板在组件层。 */

/** 长代码块阈值：超过该行数才提供独立阅读页入口。 */
export const CODE_READER_MIN_LINES = 20

/** 代码文本行数：结尾单个换行不计一行（与复制行为一致）；空文本 0 行。 */
export function countCodeLines(text: string): number {
  const trimmed = text.replace(/\n$/, '')
  if (trimmed === '') return 0
  return trimmed.split('\n').length
}

export interface CodeMatch {
  /** 行下标（0 起，对应展示行数组）。 */
  line: number
  /** 行内匹配起点（0 起，包含）。 */
  start: number
  /** 行内匹配终点（0 起，不包含）。 */
  end: number
}

/** 面板内搜索：大小写不敏感的子串匹配，逐行收集，文档序返回。
 * 空查询返回 []（无匹配 ≠ 搜索失败，UI 显示「无结果」）。 */
export function findCodeMatches(lines: string[], query: string): CodeMatch[] {
  const needle = query.toLowerCase()
  if (needle === '') return []
  const matches: CodeMatch[] = []
  for (let line = 0; line < lines.length; line += 1) {
    const haystack = (lines[line] ?? '').toLowerCase()
    let from = 0
    let idx = haystack.indexOf(needle, from)
    while (idx !== -1) {
      matches.push({ line, start: idx, end: idx + needle.length })
      from = idx + needle.length
      idx = haystack.indexOf(needle, from)
    }
  }
  return matches
}

/** 查询为「纯空白」时视为无查询（诚实：不把空格当搜索词）。 */
export function isMeaningfulQuery(query: string): boolean {
  return query.trim() !== ''
}
