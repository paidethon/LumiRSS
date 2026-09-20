/** 宽表格展开面板工具（F012 复制/下载 + F013 列排序与数值筛选）。
 *
 * 只作用于面板内的克隆表格（DOM 层展示：重排/隐藏行），原文
 * （ArticleContent 的 sanitize 输出）不受影响；「重置」恢复原序。 */

import { useMemo, useRef, useState } from 'react'
import { ArrowDownAZ, Copy, Download, RotateCcw } from 'lucide-react'
import { tableToMatrix, matrixToTsv, matrixToCsv } from '../lib/table-export'
import {
  isNumericColumn,
  parseNumericValue,
  sortRows,
  filterRows,
  type NumericFilter,
  type SortDir,
} from '../lib/table-view'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

interface ViewRow {
  /** 行在原表中的序号（稳定排序决胜 + 重置）。 */
  index: number
  cells: string[]
}

export function WideTablePanel({ table }: { table: HTMLTableElement }) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [filters, setFilters] = useState<Map<number, NumericFilter>>(new Map())
  const [feedback, setFeedback] = useState<string | null>(null)

  const matrix = useMemo(() => tableToMatrix(table), [table])
  const header = matrix[0] ?? []
  const numericCols = useMemo(
    () =>
      new Set(
        header
          .map((_, col) => col)
          .filter((col) =>
            isNumericColumn(matrix.slice(1).map((row) => row[col] ?? '')),
          ),
      ),
    [matrix, header],
  )

  const dataRows = matrix.slice(1)
  const visibleRows = useMemo(() => {
    const rows: ViewRow[] = dataRows.map((cells, index) => ({ index, cells }))
    let out = rows
    if (sortCol !== null && sortDir !== null) {
      out = sortRows(out, sortDir, (row) => row.cells[sortCol] ?? '')
    }
    out = filterRows(out, filters, (row, col) => row.cells[col] ?? '')
    return out
  }, [dataRows, sortCol, sortDir, filters])

  function cycleSort(col: number) {
    setSortCol((prevCol) => {
      setSortDir((prevDir) => {
        if (prevCol !== col) return 'asc'
        if (prevDir === 'asc') return 'desc'
        return null // 降 → 原序
      })
      return col
    })
  }

  function setFilter(col: number, op: 'gt' | 'lt', text: string) {
    setFilters((prev) => {
      const next = new Map(prev)
      const value = parseNumericValue(text)
      if (text.trim() === '' || value === null) next.delete(col)
      else next.set(col, { op, value })
      return next
    })
  }

  function resetView() {
    setSortCol(null)
    setSortDir(null)
    setFilters(new Map())
  }

  async function copyTable() {
    const tsv = matrixToTsv(visibleRows.map((row) => row.cells))
    try {
      await navigator.clipboard.writeText(tsv)
      setFeedback('已复制（TSV，含注入防护）')
    } catch {
      setFeedback('复制失败：请检查剪贴板权限')
    }
    window.setTimeout(() => setFeedback(null), 2000)
  }

  function downloadCsv() {
    const csv = matrixToCsv(visibleRows.map((row) => row.cells))
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'table.csv'
    anchor.click()
    URL.revokeObjectURL(url)
    setFeedback('已下载 CSV')
    window.setTimeout(() => setFeedback(null), 2000)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 工具栏：F012 复制/下载 + F013 排序/筛选/重置 */}
      <div
        className="flex flex-wrap items-center gap-2 border-b border-[var(--lumi-border)] px-4 py-2"
        data-testid="table-toolbar"
      >
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">表格（可横向滚动）</span>
        <span className="flex-1" />
        <Button size="sm" variant="secondary" onClick={() => void copyTable()}>
          <Copy aria-hidden className="size-3.5" />
          复制表格
        </Button>
        <Button size="sm" variant="secondary" onClick={downloadCsv}>
          <Download aria-hidden className="size-3.5" />
          下载 CSV
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={resetView}
          disabled={sortCol === null && filters.size === 0}
        >
          <RotateCcw aria-hidden className="size-3.5" />
          重置
        </Button>
        {feedback !== null && (
          <span role="status" className="text-xs text-[var(--lumi-accent-text)]">
            {feedback}
          </span>
        )}
      </div>
      {/* F013：数值列筛选输入（仅数值列显示；大于/小于） */}
      {numericCols.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--lumi-border)] px-4 py-1.5">
          {[...numericCols].map((col) => (
            <span key={col} className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
              {header[col] || `第 ${col + 1} 列`}
              <input
                type="text"
                inputMode="decimal"
                placeholder=">"
                aria-label={`筛选 大于 ${header[col] || col + 1}`}
                onChange={(e) => setFilter(col, 'gt', e.target.value)}
                className="h-7 w-14 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs"
              />
              <input
                type="text"
                inputMode="decimal"
                placeholder="<"
                aria-label={`筛选 小于 ${header[col] || col + 1}`}
                onChange={(e) => setFilter(col, 'lt', e.target.value)}
                className="h-7 w-14 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs"
              />
            </span>
          ))}
        </div>
      )}
      <div ref={hostRef} data-lumi-table-host="" className="min-h-0 flex-1 overflow-auto p-4">
        <table data-testid="table-view" className="w-full border-collapse text-sm">
          <thead>
            <tr>
              {header.map((label, col) => (
                <th
                  key={col}
                  className="border-b border-[var(--lumi-border)] px-2 py-1.5 text-left font-semibold"
                >
                  <button
                    type="button"
                    onClick={() => cycleSort(col)}
                    className={cx(
                      'inline-flex min-h-11 items-center gap-1 text-left',
                      sortCol === col
                        ? 'text-[var(--lumi-accent-text)]'
                        : 'text-[var(--lumi-text-primary)]',
                    )}
                    aria-label={`排序 ${label || col + 1}`}
                  >
                    {label || `第 ${col + 1} 列`}
                    <ArrowDownAZ
                      aria-hidden
                      className={cx(
                        'size-3.5 transition-opacity',
                        sortCol === col && sortDir !== null ? 'opacity-100' : 'opacity-30',
                      )}
                    />
                    {sortCol === col && sortDir !== null && (
                      <span className="text-[10px]">{sortDir === 'asc' ? '↑' : '↓'}</span>
                    )}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row) => (
              <tr key={row.index} data-row-index={row.index}>
                {header.map((_, col) => (
                  <td key={col} className="border-b border-[var(--lumi-separator)] px-2 py-1.5">
                    {row.cells[col] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
