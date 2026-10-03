/** SettingsRow — 行结构、详情折叠与控件关联守卫。 */

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SettingsRow } from '../SettingsRow'

describe('SettingsRow', () => {
  it('渲染 label + help，控件落在右侧插槽', () => {
    render(
      <SettingsRow label="阅读预算" help="每日提醒到达预算前的剩余篇幅">
        <button type="button">编辑</button>
      </SettingsRow>,
    )
    expect(screen.getByText('阅读预算')).toBeInTheDocument()
    expect(screen.getByText('每日提醒到达预算前的剩余篇幅')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '编辑' })).toBeInTheDocument()
  })

  it('controlId 传入时 label 以 htmlFor 关联控件', () => {
    render(
      <SettingsRow label="刷新频率" controlId="refresh-input">
        <input id="refresh-input" type="text" />
      </SettingsRow>,
    )
    expect(screen.getByLabelText('刷新频率')).toBeInTheDocument()
  })

  it('details：默认收起，点击展开/收起并同步 aria-expanded', () => {
    render(
      <SettingsRow label="清除缓存" details={<p>缓存只含图片与网页快照，不影响文章数据。</p>}>
        <button type="button">清除</button>
      </SettingsRow>,
    )
    const toggle = screen.getByRole('button', { name: '详情' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('缓存只含图片与网页快照，不影响文章数据。')).toBeNull()

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAttribute('aria-controls')
    expect(screen.getByText('缓存只含图片与网页快照，不影响文章数据。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收起详情' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '收起详情' }))
    expect(screen.queryByText('缓存只含图片与网页快照，不影响文章数据。')).toBeNull()
  })

  it('dangerous：不改变行为，仅语义标记（冒烟）', () => {
    const onClick = vi.fn()
    render(
      <SettingsRow label="删除账户" dangerous details={undefined}>
        <button type="button" onClick={onClick}>
          删除
        </button>
      </SettingsRow>,
    )
    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
