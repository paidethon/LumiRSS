/** F012 宽表格导出 —— TSV（剪贴板）/ CSV（下载）+ 公式注入防护。
 *
 * CSV/TSV 注入防护（保守规则）：单元格值以 = + - @ 开头且「不像纯
 * 数字」（公式特征，如 =SUM(A1)、+cmd、-2+3、@x）时，导出前置 '
 * （撇号），使 Excel/WPS/Numbers 按文本处理；纯数字（-2、+3.5）与
 * 普通文本不受影响；空单元格保留空位；CSV 引号转义遵循 RFC 4180。
 * 剪贴板的 TSV 同样防护（粘贴到表格软件的注入路径一致）。 */

/** 公式特征判定：以 =,+,-,@ 开头且剩余部分不是纯数字。 */
export function looksLikeFormula(value: string): boolean {
  if (value === '') return false
  const first = value[0] ?? ''
  if (!'=+-@'.includes(first)) return false
  const rest = value.slice(1)
  // 纯数字（含小数/千分位/百分号/正负号）= 普通数值，不防护
  const numeric = /^[\d,.\s]+%?$/
  return !numeric.test(rest) || rest.trim() === ''
}

/** 导出防护：公式形似值前置撇号。 */
export function guardCell(value: string): string {
  return looksLikeFormula(value) ? `'${value}` : value
}

/** 从语义表格提取单元格矩阵（thead/th 优先为首行；textContent 原样）。 */
export function tableToMatrix(table: HTMLTableElement): string[][] {
  const matrix: string[][] = []
  const rows = Array.from(table.querySelectorAll('tr'))
  for (const row of rows) {
    const cells = Array.from(row.querySelectorAll('th,td'))
    matrix.push(cells.map((cell) => (cell.textContent ?? '').trim()))
  }
  return matrix
}

/** 矩阵 → TSV（剪贴板用；同样过公式防护；空单元格保留空位）。 */
export function matrixToTsv(matrix: string[][]): string {
  return matrix
    .map((row) => row.map((cell) => guardCell(cell)).join('\t'))
    .join('\n')
}

function csvCell(value: string): string {
  const guarded = guardCell(value)
  if (guarded.includes('"') || guarded.includes(',') || guarded.includes('\n') || guarded.includes('\t')) {
    return `"${guarded.replace(/"/g, '""')}"`
  }
  return guarded
}

/** 矩阵 → CSV（RFC 4180：引号转义；下载用）。 */
export function matrixToCsv(matrix: string[][]): string {
  return matrix.map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
}
