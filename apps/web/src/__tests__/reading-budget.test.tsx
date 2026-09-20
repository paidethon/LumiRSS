/** F014 定时阅读清单 —— 装填算法单元 + 面板交互（移除/调序/顺序阅读/退出清理）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildReadingBudget,
  DEFAULT_ESTIMATE_MINUTES,
  estimateMinutes,
  type BudgetCandidate,
} from '../lib/reading-budget'
import { ReadingBudgetPanel } from '../components/ReadingBudgetPanel'

function candidate(entryRef: string, title: string, text: string | null): BudgetCandidate {
  return { entryRef, title, text }
}

describe('F014 装填算法', () => {
  it('F014: 预算边界 —— 升序贪心装填，放不下的丢弃', () => {
    const candidates = [
      candidate('a', '甲', '一'.repeat(300)), // 1 分钟
      candidate('b', '乙', '一'.repeat(1200)), // 4 分钟
      candidate('c', '丙', '一'.repeat(1800)), // 6 分钟
    ]
    const result = buildReadingBudget(candidates, 5)
    expect(result.items.map((i) => i.entryRef)).toEqual(['a', 'b']) // 1+4=5 恰好装满
    expect(result.totalMinutes).toBe(5)
    expect(result.underBudget).toBe(false)
  })

  it('F014: 不足预算 → 全收并标注 underBudget', () => {
    const candidates = [candidate('a', '甲', '一'.repeat(300))]
    const result = buildReadingBudget(candidates, 30)
    expect(result.items.length).toBe(1)
    expect(result.underBudget).toBe(true)
  })

  it('F014: 无估算条目按 3 分钟缺省；空结果', () => {
    expect(estimateMinutes(candidate('x', '无正文', null))).toBe(DEFAULT_ESTIMATE_MINUTES)
    const result = buildReadingBudget([], 15)
    expect(result.items).toEqual([])
    expect(result.underBudget).toBe(true) // 空候选也视为未达预算
  })
})

describe('F014 面板交互', () => {
  const candidates = [
    candidate('a', '文章甲', '一'.repeat(300)),
    candidate('b', '文章乙', '一'.repeat(300)),
    candidate('c', '文章丙', '一'.repeat(300)),
  ]

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('F014: 选预算生成清单 → 移除条目 → 上移/下移调序', () => {
    render(
      <ReadingBudgetPanel candidates={candidates} onClose={() => {}} />,
    )
    fireEvent.click(screen.getByRole('button', { name: '5 分钟' }))
    expect(screen.getByRole('status').textContent).toContain('共 3 篇')
    // 移除甲
    fireEvent.click(screen.getByRole('button', { name: '移除「文章甲」' }))
    expect(screen.getByRole('status').textContent).toContain('共 2 篇')
    // 上移乙（在丙之后 → 交换）
    fireEvent.click(screen.getByRole('button', { name: '上移「文章丙」' }))
    const list = screen.getAllByRole('listitem')
    expect(list[0]!.textContent).toContain('文章丙')
  })

  it('F014: 开始阅读 → 顺序模式（打开当前篇/下一篇）；完成清空清单（会话内范围）', () => {
    const onOpenEntry = vi.fn()
    const onClose = vi.fn()
    render(
      <ReadingBudgetPanel candidates={candidates} onOpenEntry={onOpenEntry} onClose={onClose} />,
    )
    fireEvent.click(screen.getByRole('button', { name: '5 分钟' }))
    fireEvent.click(screen.getByRole('button', { name: /开始阅读/ }))
    expect(screen.getByText(/顺序阅读 1 \/ 3/)).toBeInTheDocument()
    expect(screen.getAllByText(/估读时间≠实际/).length).toBeGreaterThan(0)
    // 打开当前篇（不推进游标）
    fireEvent.click(screen.getByRole('button', { name: '打开当前篇' }))
    expect(onOpenEntry).toHaveBeenCalledWith('a')
    // 下一篇
    fireEvent.click(screen.getByRole('button', { name: '下一篇' }))
    expect(screen.getByText(/顺序阅读 2 \/ 3/)).toBeInTheDocument()
    // 完成并清空 → 通知父级关闭（清单状态随面板卸载清理，会话内临时）
    fireEvent.click(screen.getByRole('button', { name: '完成并清空清单' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('F014: 退出（×）直接清理', () => {
    const onClose = vi.fn()
    render(<ReadingBudgetPanel candidates={candidates} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: '5 分钟' }))
    fireEvent.click(screen.getByRole('button', { name: '关闭阅读预算' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
