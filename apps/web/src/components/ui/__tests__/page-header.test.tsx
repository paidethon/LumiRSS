/** PageHeader — 最小行为守卫（R3 契约 §2：title/subtitle/actions/back）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PageHeader } from '../PageHeader'

describe('PageHeader', () => {
  it('渲染标题与副标题，默认 h1 语义', () => {
    render(<PageHeader title="来源中心" subtitle="全部信息源的注册表总览" />)
    const heading = screen.getByRole('heading', { level: 1, name: '来源中心' })
    expect(heading).toBeInTheDocument()
    expect(screen.getByText('全部信息源的注册表总览')).toBeInTheDocument()
  })

  it('headingLevel="h2" 时降级为二级标题', () => {
    render(<PageHeader title="账户" headingLevel="h2" />)
    expect(screen.getByRole('heading', { level: 2, name: '账户' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 1 })).toBeNull()
  })

  it('actions 插槽渲染在头部内', () => {
    render(<PageHeader title="收件箱" actions={<button type="button">新建规则</button>} />)
    expect(screen.getByRole('button', { name: '新建规则' })).toBeInTheDocument()
  })

  it('back：点击触发回调，箭头不参与可访问名称', () => {
    const onBack = vi.fn()
    render(<PageHeader title="文章" back={{ label: '返回列表', onClick: onBack }} />)
    const back = screen.getByRole('button', { name: '返回列表' })
    fireEvent.click(back)
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('不传 back 时不渲染返回按钮', () => {
    render(<PageHeader title="搜索" />)
    expect(screen.queryByRole('button', { name: /返回/ })).toBeNull()
  })
})
