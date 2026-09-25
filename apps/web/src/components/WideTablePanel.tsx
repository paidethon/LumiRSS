/** 宽表格展开面板工具（F012 复制/下载 + F013 列排序与数值筛选
 * + N063 行列聚焦）。
 *
 * 只作用于面板内的克隆表格（DOM 层展示：重排/隐藏行），原文
 * （ArticleContent 的 sanitize 输出）不受影响；「重置」恢复原序。
 * N063：表头/首列 sticky（横向滚动时保持可见）；悬停/点按高亮当前
 * 行+列（事件委托 + class 切换，不进 React 状态）；复制/导出仍然
 * 只来自数据矩阵（与高亮无关）。 */

import { useEffect, useMemo, useRef, useState } from 'react'
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

/** N063：当前行/列高亮 class（index.css 提供 sticky 与高亮样式）。 */
const FOCUS_CLASS = 'lumi-wt-focus'

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

  // N063：悬停/点按高亮当前行+列（事件委托挂在滚动宿主上；直接切换
  // class，不进 React 状态——重渲染只由排序/筛选触发，且 className
  // 属性重写天然清掉残留标记）。触屏点按同样命中（click 也委托）。
  useEffect(() => {
    const host = hostRef.current
    if (host === null) return
    let active: HTMLElement[] = []
    const clear = () => {
      for (const el of active) el.classList.remove(FOCUS_CLASS)
      active = []
    }
    const highlight = (cell: Element) => {
      const row = cell.parentElement
      if (!(row instanceof HTMLTableRowElement)) return
      const table = row.parentElement?.parentElement
      if (!(table instanceof HTMLTableElement)) return
      const col = Array.prototype.indexOf.call(row.cells, cell)
      if (col === -1) return
      clear()
      for (const c of Array.from(row.cells)) {
        c.classList.add(FOCUS_CLASS)
        active.push(c)
      }
      for (const r of table.rows) {
        const c = r.cells[col]
        if (c !== undefined && !active.includes(c)) {
          c.classList.add(FOCUS_CLASS)
          active.push(c)
        }
      }
    }
    const onOver = (event: Event) => {
      const target = event.target as Element | null
      const cell = target?.closest('td, th')
      if (cell !== null && cell !== undefined) highlight(cell)
    }
    host.addEventListener('mouseover', onOver)
    host.addEventListener('click', onOver)
    host.addEventListener('mouseleave', clear)
    return () => {
      host.removeEventListener('mouseover', onOver)
      host.removeEventListener('click', onOver)
      host.removeEventListener('mouseleave', clear)
      clear()
    }
  }, [])

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
                  className={cx(
                    // N063：表头 sticky top；首列表头同时 sticky left。
                    'lumi-wt-head border-b border-[var(--lumi-border)] px-2 py-1.5 text-left font-semibold',
                    col === 0 && 'lumi-wt-col0',
                  )}
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
                  <td
                    key={col}
                    className={cx(
                      // N063：首列 sticky left；触控最小行高由
                      // .lumi-wt-cell 保证（44px）。
                      'lumi-wt-cell border-b border-[var(--lumi-separator)] px-2 py-1.5',
                      col === 0 && 'lumi-wt-col0',
                    )}
                  >
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
