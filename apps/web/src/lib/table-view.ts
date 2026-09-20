/** F013 表格列排序与数值筛选 —— 纯函数（仅 DOM 层展示用，不改原文）。
 *
 * - 数值列识别：该列 ≥80% 的非空单元格可解析为数字（"12%"、
 *   "1,234"、"-2.5" 均可解析；中文数字不视为阿拉伯数值）；
 * - 三态排序：升 → 降 → 原序；相等值保持相对序（稳定排序，显式
 *   index 决胜）；
 * - 数值筛选：大于/小于输入（空输入 = 不过滤）；可全部重置。 */

export type SortDir = 'asc' | 'desc' | null

/** "12%" → 12；"1,234" → 1234；"-2.5" → -2.5；不可解析 → null。 */
export function parseNumericValue(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  let text = trimmed
  let percent = false
  if (text.endsWith('%')) {
    percent = true
    text = text.slice(0, -1)
  }
  text = text.replace(/,/g, '')
  if (!/^[+-]?(\d+(\.\d+)?|\.\d+)$/.test(text)) return null
  const num = Number(text)
  if (!Number.isFinite(num)) return null
  return percent ? num : num
}

/** 数值列：≥80% 非空单元格可解析；空值不计入分母但允许通过筛选。 */
export function isNumericColumn(values: string[]): boolean {
  const cells = values.map((v) => v.trim()).filter((v) => v !== '')
  if (cells.length === 0) return false
  const numeric = cells.filter((v) => parseNumericValue(v) !== null)
  return numeric.length / cells.length >= 0.8
}

/** 稳定排序（index 决胜保证相等值相对序不变）。返回新数组。 */
export function sortRows<T>(rows: T[], dir: SortDir, key: (row: T) => string): T[] {
  if (dir === null) return rows
  const indexed = rows.map((row, index) => ({ row, index, value: parseNumericValue(key(row)) }))
  indexed.sort((a, b) => {
    const av = a.value
    const bv = b.value
    // 数值列排序：不可解析的空/文本值排在末尾（升序时）
    if (av === null && bv === null) return a.index - b.index
    if (av === null) return 1
    if (bv === null) return -1
    const cmp = av === bv ? 0 : av < bv ? -1 : 1
    return dir === 'asc' ? cmp : -cmp
  })
  return indexed.map((entry) => entry.row)
}

export interface NumericFilter {
  /** 大于（gt）/ 小于（lt）；空值行不过滤直接保留。 */
  op: 'gt' | 'lt'
  value: number
}

/** 数值筛选（单元格不可解析或为空 → 保留该行——不静默丢数据）。 */
export function filterRows<T>(
  rows: T[],
  filters: Map<number, NumericFilter>,
  cellOf: (row: T, col: number) => string,
): T[] {
  if (filters.size === 0) return rows
  return rows.filter((row) => {
    for (const [col, filter] of filters) {
      const parsed = parseNumericValue(cellOf(row, col))
      if (parsed === null) continue // 空/不可解析：不参与筛选判定
      if (filter.op === 'gt' && !(parsed > filter.value)) return false
      if (filter.op === 'lt' && !(parsed < filter.value)) return false
    }
    return true
  })
}
