/** F012/F013 宽表格 —— 导出防护（util）+ 排序/筛选/重置与复制下载（组件）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import {
  guardCell,
  looksLikeFormula,
  matrixToCsv,
  matrixToTsv,
  tableToMatrix,
} from '../lib/table-export'
import {
  isNumericColumn,
  parseNumericValue,
  sortRows,
  filterRows,
} from '../lib/table-view'
import { WideTablePanel } from '../components/WideTablePanel'

describe('F012 公式注入防护（util）', () => {
  it('F012: =SUM(A1) / +cmd / -2+3 / @x 前置撇号；纯数字与中文不动', () => {
    expect(guardCell('=SUM(A1)')).toBe("'=SUM(A1)")
    expect(guardCell('+cmd')).toBe("'+cmd")
    expect(guardCell('-2+3')).toBe("'-2+3")
    expect(guardCell('@x')).toBe("'@x")
    expect(guardCell('-2')).toBe('-2') // 纯负数不防护
    expect(guardCell('+3.5')).toBe('+3.5')
    expect(guardCell('12%')).toBe('12%')
    expect(guardCell('中文值')).toBe('中文值')
    expect(guardCell('')).toBe('')
  })

  it('F012: looksLikeFormula 判定边界（空格/千分位数字不误报）', () => {
    expect(looksLikeFormula('=1+1')).toBe(true)
    expect(looksLikeFormula('1,234')).toBe(false)
    expect(looksLikeFormula('- 1,234.5')).toBe(false) // 负号+空格+数字 = 数值
  })

  it('F012: TSV/CSV 空单元格保留空位、引号转义、整表防护', () => {
    const matrix = [
      ['名称', '公式', '空'],
      ['中文', '=SUM(A1)', ''],
      ['引"号', '@cmd', '+2'],
    ]
    const tsv = matrixToTsv(matrix)
    expect(tsv.split('\n')[0]).toBe('名称\t公式\t空') // 空单元格保留空位
    expect(tsv).toContain("'=SUM(A1)")
    expect(tsv).toContain("'@cmd")

    const csv = matrixToCsv(matrix)
    expect(csv).toContain('"引""号"')
    expect(csv).toContain("'=SUM(A1)")
    expect(csv.endsWith('\r\n')).toBe(true)
  })

  it('F012: tableToMatrix 提取 th/td 文本', () => {
    const host = document.createElement('div')
    host.innerHTML = '<table><tr><th>列A</th><th>列B</th></tr><tr><td>1</td><td>2</td></tr></table>'
    const table = host.querySelector('table') as HTMLTableElement
    expect(tableToMatrix(table)).toEqual([
      ['列A', '列B'],
      ['1', '2'],
    ])
  })
})

describe('F013 排序与筛选（util）', () => {
  it('F013: 数值列识别 —— "12%"、"1,234" 可解析；≥80% 阈值', () => {
    expect(parseNumericValue('12%')).toBe(12)
    expect(parseNumericValue('1,234')).toBe(1234)
    expect(parseNumericValue('-2.5')).toBe(-2.5)
    expect(parseNumericValue('十二')).toBeNull()
    expect(isNumericColumn(['12%', '1,234', '-2.5', ''])).toBe(true) // 空不计入分母
    expect(isNumericColumn(['10', '二十', '三十', '40', '50'])).toBe(false) // 1/5 < 80%
  })

  it('F013: 排序稳定性（相等值保持相对序）与三态语义', () => {
    const rows = [
      { i: 0, v: '5' },
      { i: 1, v: '3' },
      { i: 2, v: '5' },
      { i: 3, v: '1' },
    ]
    const asc = sortRows(rows, 'asc', (r) => r.v)
    expect(asc.map((r) => r.i)).toEqual([3, 1, 0, 2]) // 相等的 5：0 在 2 前
    const desc = sortRows(rows, 'desc', (r) => r.v)
    expect(desc.map((r) => r.i)).toEqual([0, 2, 1, 3]) // 相等值相对序保持
    expect(sortRows(rows, null, (r) => r.v)).toEqual(rows) // 原序
  })

  it('F013: 数值筛选（空/不可解析单元格保留，不丢数据）', () => {
    const rows = [{ v: '10' }, { v: '5' }, { v: '' }, { v: 'N/A' }, { v: '20' }]
    const filters = new Map([[0, { op: 'gt' as const, value: 6 }]])
    expect(filterRows(rows, filters, (r) => r.v).map((r) => r.v)).toEqual([
      '10',
      '',
      'N/A',
      '20',
    ])
  })
})

// ---- 组件交互 ----

function makeTable(): HTMLTableElement {
  const host = document.createElement('div')
  host.innerHTML = `<table>
    <tr><th>名称</th><th>数量</th><th>备注</th></tr>
    <tr><td>甲</td><td>1,000</td><td>说明</td></tr>
    <tr><td>乙</td><td>250</td><td>=SUM(A1)</td></tr>
    <tr><td>丙</td><td>300</td><td>普通</td></tr>
    <tr><td>丁</td><td>20%</td><td>+cmd</td></tr>
  </table>`
  return host.querySelector('table') as HTMLTableElement
}

beforeEach(() => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:mock'),
    revokeObjectURL: vi.fn(),
  })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('F012/F013 WideTablePanel', () => {
  it('F013: 点击表头三态排序（升→降→原序）；非数值列不显示筛选', () => {
    render(<WideTablePanel table={makeTable()} />)
    // 数量列（数值列）有筛选输入；名称列没有
    expect(screen.getByLabelText('筛选 大于 数量')).toBeInTheDocument()
    expect(screen.queryByLabelText('筛选 大于 名称')).toBeNull()

    const sortBtn = screen.getByRole('button', { name: '排序 数量' })
    fireEvent.click(sortBtn) // 升序：250, 20%(=20), 1000, =SUM 不可解析在末尾
    let rows = screen.getAllByTestId('table-view')[0]!.querySelectorAll('tbody tr')
    expect(rows[0]!.textContent).toContain('丁') // 20% → 20 最小
    fireEvent.click(sortBtn) // 降序：1000 在前
    rows = screen.getAllByTestId('table-view')[0]!.querySelectorAll('tbody tr')
    expect(rows[0]!.textContent).toContain('甲')
    fireEvent.click(sortBtn) // 原序：甲乙丙丁
    rows = screen.getAllByTestId('table-view')[0]!.querySelectorAll('tbody tr')
    expect(rows[0]!.textContent).toContain('甲')
  })

  it('F013: 数值筛选与重置恢复', () => {
    render(<WideTablePanel table={makeTable()} />)
    fireEvent.change(screen.getByLabelText('筛选 大于 数量'), { target: { value: '100' } })
    const table = screen.getAllByTestId('table-view')[0]!
    let rows = table.querySelectorAll('tbody tr')
    const texts = Array.from(rows).map((r) => r.textContent)
    expect(texts.some((t) => t!.includes('甲'))).toBe(true) // 1,000 > 100 保留
    expect(texts.some((t) => t!.includes('乙'))).toBe(true) // 250 > 100 保留
    expect(texts.some((t) => t!.includes('丁'))).toBe(false) // 20% → 20 不大于 100 → 移除
    // 重置
    fireEvent.click(screen.getByRole('button', { name: /重置/ }))
    rows = table.querySelectorAll('tbody tr')
    expect(rows.length).toBe(4)
  })

  it('F012: 复制表格 → 剪贴板收到防护后的 TSV；下载 CSV 触发 blob 下载', async () => {
    render(<WideTablePanel table={makeTable()} />)
    fireEvent.click(screen.getByRole('button', { name: /复制表格/ }))
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled())
    const written = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock
      .calls[0]![0] as string
    expect(written).toContain("'=SUM(A1)")

    fireEvent.click(screen.getByRole('button', { name: /下载 CSV/ }))
    await waitFor(() => {
      expect(URL.createObjectURL).toHaveBeenCalled()
    })
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls[0]![0] as Blob
    expect(blob).toBeInstanceOf(Blob)
  })

  it('F012: 剪贴板权限失败 → 错误反馈（诚实失败）', async () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    render(<WideTablePanel table={makeTable()} />)
    fireEvent.click(screen.getByRole('button', { name: /复制表格/ }))
    expect(await screen.findByText('复制失败：请检查剪贴板权限')).toBeInTheDocument()
  })
})
