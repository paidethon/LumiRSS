/** N063 — 宽表面板行列聚焦：表头/首列 sticky（class 接线）、悬停/点按
 * 高亮当前行+列（事件委托 + class 切换）、复制/导出仍来自数据矩阵
 * （与高亮无关、内容不变）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { WideTablePanel } from '../components/WideTablePanel'

function makeTable(): HTMLTableElement {
  const host = document.createElement('div')
  host.innerHTML = `<table>
    <tr><th>名称</th><th>数量</th><th>备注</th></tr>
    <tr><td>甲</td><td>1,000</td><td>说明</td></tr>
    <tr><td>乙</td><td>250</td><td>=SUM(A1)</td></tr>
    <tr><td>丙</td><td>300</td><td>普通</td></tr>
  </table>`
  return host.querySelector('table') as HTMLTableElement
}

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
})

afterEach(() => {
  const nav = window.navigator as unknown as Record<string, unknown>
  delete nav.clipboard
})

describe('N063 表格行列聚焦', () => {
  it('表头 sticky class + 首列 sticky class 接线（左上角两向 sticky）', () => {
    render(<WideTablePanel table={makeTable()} />)
    const table = document.querySelector('[data-testid="table-view"]')!
    const heads = table.querySelectorAll('thead th')
    expect(heads).toHaveLength(3)
    for (const th of heads) {
      expect(th.classList.contains('lumi-wt-head')).toBe(true)
    }
    // 首列：表头 + 数据行都带 lumi-wt-col0；其余列没有
    expect(heads[0]!.classList.contains('lumi-wt-col0')).toBe(true)
    expect(heads[1]!.classList.contains('lumi-wt-col0')).toBe(false)
    const firstCells = table.querySelectorAll('tbody td:first-child')
    expect(firstCells).toHaveLength(3)
    for (const td of firstCells) {
      expect(td.classList.contains('lumi-wt-col0')).toBe(true)
    }
    expect(table.querySelector('tbody td:nth-child(2)')!.classList.contains('lumi-wt-col0')).toBe(false)
    // 触控 44px 行高的 cell class
    expect(table.querySelector('tbody td')!.classList.contains('lumi-wt-cell')).toBe(true)
  })

  it('悬停高亮当前行+列；移出清除；点按（触屏）同样高亮', () => {
    render(<WideTablePanel table={makeTable()} />)
    const table = document.querySelector('[data-testid="table-view"]')!

    const focused = () => Array.from(table.querySelectorAll('.lumi-wt-focus')).map((el) => el.textContent)
    // 悬停「1,000」（甲行，第 2 列）：甲行 3 个格子 + 第 2 列 4 个格子（含表头）
    fireEvent.mouseOver(screen.getByText('1,000'))
    const hovered = focused()
    expect(hovered).toHaveLength(3 + 4 - 1)
    expect(hovered).toContain('甲')
    expect(hovered).toContain('说明')
    expect(hovered).toContain('数量')
    expect(hovered).toContain('250')
    expect(hovered).toContain('300')
    expect(hovered).not.toContain('乙')
    expect(hovered).not.toContain('备注')

    // 移出表格 → 清除
    fireEvent.mouseLeave(document.querySelector('[data-lumi-table-host]')!)
    expect(focused()).toHaveLength(0)

    // 点按（触屏合成路径）：「普通」（丙行，第 3 列）
    fireEvent.click(screen.getByText('普通'))
    const tapped = focused()
    expect(tapped).toContain('丙')
    expect(tapped).toContain('300')
    expect(tapped).toContain('备注')
    expect(tapped).not.toContain('甲')
  })

  it('复制/导出与高亮无关：复制表格仍输出原矩阵 TSV', async () => {
    render(<WideTablePanel table={makeTable()} />)
    // 先制造高亮状态
    fireEvent.mouseOver(screen.getByText('1,000'))
    fireEvent.click(screen.getByRole('button', { name: '复制表格' }))
    await vi.waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1)
    })
    const tsv = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string
    // 与数据矩阵一致（表头行不在复制范围——既有行为不变）
    expect(tsv).toBe('甲\t1,000\t说明\n乙\t250\t\'=SUM(A1)\n丙\t300\t普通')
  })
})
