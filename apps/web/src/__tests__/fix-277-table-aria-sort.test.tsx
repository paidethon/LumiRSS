/**
 * FIX-277 — 宽表面头列语义与排序状态（辅助技术可确定）。
 *
 * 修复前：可排序表头只有视觉 ↑/↓ 箭头与 aria-label「排序 X」，th 无
 * scope、无 aria-sort——读屏既无法把表头关联到数据列，也无法得知当前
 * 排序方向（箭头 glyph 还会被当文本重复朗读）。
 * 修复后：th scope="col"；aria-sort=ascending/descending 只在当前排序列；
 * 方向箭头 aria-hidden（状态由 aria-sort 播报，不重复朗读）。
 */

import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { WideTablePanel } from '../components/WideTablePanel'

function makeTable(): HTMLTableElement {
  const host = document.createElement('div')
  host.innerHTML = `<table>
    <tr><th>名称</th><th>数量</th><th>备注</th></tr>
    <tr><td>甲</td><td>1,000</td><td>说明</td></tr>
    <tr><td>乙</td><td>250</td><td>普通</td></tr>
  </table>`
  return host.querySelector('table') as HTMLTableElement
}

describe('FIX-277: 表头 scope 与 aria-sort', () => {
  it('每个表头 th 带 scope="col"；未排序时无 aria-sort', () => {
    render(<WideTablePanel table={makeTable()} />)
    const heads = document.querySelectorAll('[data-testid="table-view"] thead th')
    expect(heads).toHaveLength(3)
    for (const th of heads) {
      expect(th.getAttribute('scope')).toBe('col')
      expect(th.getAttribute('aria-sort')).toBeNull()
    }
  })

  it('点击排序后 aria-sort 反映方向：首次升序、再点降序；其余列不受污染', () => {
    render(<WideTablePanel table={makeTable()} />)
    const heads = document.querySelectorAll('[data-testid="table-view"] thead th')
    const sortButton = (col: number) =>
      heads[col]!.querySelector('button') as HTMLButtonElement

    fireEvent.click(sortButton(1)) // 数量列升序
    expect(heads[1]!.getAttribute('aria-sort')).toBe('ascending')
    expect(heads[0]!.getAttribute('aria-sort')).toBeNull()
    expect(heads[2]!.getAttribute('aria-sort')).toBeNull()

    fireEvent.click(sortButton(1)) // 再点 = 降序
    expect(heads[1]!.getAttribute('aria-sort')).toBe('descending')

    fireEvent.click(sortButton(0)) // 换列：aria-sort 跟随
    expect(heads[0]!.getAttribute('aria-sort')).toBe('ascending')
    expect(heads[1]!.getAttribute('aria-sort')).toBeNull()
  })

  it('方向箭头 glyph aria-hidden（不与 aria-sort 重复朗读）', () => {
    render(<WideTablePanel table={makeTable()} />)
    const heads = document.querySelectorAll('[data-testid="table-view"] thead th')
    fireEvent.click(heads[1]!.querySelector('button') as HTMLButtonElement)
    const arrow = heads[1]!.querySelector('button span[aria-hidden="true"]')
    expect(arrow).not.toBeNull()
    expect(arrow!.textContent).toMatch(/^[↑↓]$/)
  })
})
