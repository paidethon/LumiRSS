/** Gate E 测试 — 移动端设置重设计 + 通用页补全（AC1–AC9）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import MobileSettingsScreen from '../components/MobileSettingsScreen'
import SettingsModal from '../components/settings/SettingsModal'
import { groupEntriesByDate } from '../lib/entry-groups'
import { DEFAULT_APP_SETTINGS, normalizeSettings, useAppSettings } from '../store/app-settings'

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('entry-groups 纯函数（AC7）', () => {
  const now = new Date('2026-08-30T12:00:00')
  const mk = (ref: string, publishedAt: string | null) =>
    ({
      entryRef: ref,
      title: ref,
      feedTitle: 'f',
      author: null,
      url: null,
      publishedAt,
      read: false,
      starred: false,
    }) as Parameters<typeof groupEntriesByDate>[0][number]

  it('相邻同日期合并、跨日切组（今天/昨天/M月D日）', () => {
    const entries = [
      mk('a', '2026-08-30T08:00:00Z'),
      mk('b', '2026-08-30T07:00:00Z'),
      mk('c', '2026-08-29T09:00:00Z'),
      mk('d', '2026-08-01T09:00:00Z'),
    ]
    const groups = groupEntriesByDate(entries, now)
    expect(groups.map((g) => g.label)).toEqual(['今天', '昨天', '8月1日'])
    expect(groups[0].items).toHaveLength(2)
  })

  it('publishedAt 为 null / 非法值归入「更早」', () => {
    const groups = groupEntriesByDate([mk('a', null), mk('b', 'not-a-date')], now)
    expect(groups).toHaveLength(1)
    expect(groups[0].label).toBe('更早')
    expect(groups[0].items).toHaveLength(2)
  })

  it('不重排：保持传入顺序', () => {
    const entries = [mk('old', '2026-08-01T09:00:00Z'), mk('new', '2026-08-30T08:00:00Z')]
    const groups = groupEntriesByDate(entries, now)
    expect(groups.flatMap((g) => g.items.map((i) => i.entryRef))).toEqual(['old', 'new'])
  })
})

describe('app-settings 新字段（AC28 向后兼容）', () => {
  it('默认值：四个新 toggle 全 false（scrollMarkUnread 默认关）', () => {
    expect(DEFAULT_APP_SETTINGS.dimRead).toBe(false)
    expect(DEFAULT_APP_SETTINGS.groupByDate).toBe(false)
    expect(DEFAULT_APP_SETTINGS.unreadOnly).toBe(false)
    expect(DEFAULT_APP_SETTINGS.scrollMarkUnread).toBe(false)
  })

  it('旧数据（无新字段）归一化无损升级', () => {
    const legacy = { ...DEFAULT_APP_SETTINGS }
    delete (legacy as Record<string, unknown>).dimRead
    const normalized = normalizeSettings({ ...legacy, readerFontSize: 19 })
    expect(normalized.dimRead).toBe(false)
    expect(normalized.readerFontSize).toBe(19)
  })

  it('非法值回退默认', () => {
    expect(normalizeSettings({ dimRead: 'yes' }).dimRead).toBe(false)
    expect(normalizeSettings({ scrollMarkUnread: 1 }).scrollMarkUnread).toBe(false)
  })
})

describe('MobileSettingsScreen — AC1/AC2/AC4/AC5', () => {
  it('首页 = 分组列表（4 组 13 行，图标+标题+chevron），非 chip 横条', () => {
    render(withProviders(<MobileSettingsScreen open onClose={() => {}} />))
    for (const g of ['主设置', '数据', '订阅与增强', '其他']) {
      expect(screen.getByRole('heading', { name: g })).toBeInTheDocument()
    }
    const rows = screen
      .getAllByRole('button')
      .filter((b) => b.textContent?.match(/通用|外观|翻译|文章过滤|RSSHub|订阅与来源|AI|数据控制|备份与恢复|账户与服务|工作区|关于|快捷键/))
    expect(rows.length).toBe(13)
  })

  it('点击分类行 → push 子页（返回按钮 + 标题）→ 返回', () => {
    render(withProviders(<MobileSettingsScreen open onClose={() => {}} />))
    fireEvent.click(screen.getByRole('button', { name: '通用' }))
    expect(screen.getByRole('button', { name: '返回设置' })).toBeInTheDocument()
    // 通用页含新 toggle（AC6–AC9 的控件在子页真实可用）
    expect(screen.getByRole('switch', { name: '已读条目变暗开关' })).toBeEnabled()
    expect(screen.getByRole('switch', { name: '按日期分组开关' })).toBeEnabled()
    expect(screen.getByRole('switch', { name: '启动时仅看未读开关' })).toBeEnabled()
    expect(screen.getByRole('switch', { name: '滚动时标记已读开关' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: '返回设置' }))
    expect(screen.queryByRole('button', { name: '返回设置' })).toBeNull()
  })

  it('子页开关真实生效（AC4：与桌面共享同一 store）', () => {
    render(withProviders(<MobileSettingsScreen open onClose={() => {}} />))
    fireEvent.click(screen.getByRole('button', { name: '通用' }))
    fireEvent.click(screen.getByRole('switch', { name: '已读条目变暗开关' }))
    expect(useAppSettings.getState().settings.dimRead).toBe(true)
    useAppSettings.getState().update({ dimRead: false })
  })

  it('实验性徽标（AC9）：滚动已读带「实验性 · 正式版 0017」且控件可用', () => {
    render(withProviders(<MobileSettingsScreen open onClose={() => {}} />))
    fireEvent.click(screen.getByRole('button', { name: '通用' }))
    expect(screen.getByText('实验性 · 正式版 0017')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '滚动时标记已读开关' })).toBeEnabled()
  })

  it('open=false 不渲染', () => {
    const { container } = render(
      withProviders(<MobileSettingsScreen open={false} onClose={() => {}} />),
    )
    expect(container.querySelector('[role="dialog"]')).toBeNull()
  })
})

describe('桌面/移动共享（AC5）', () => {
  it('桌面 Modal 与移动子页渲染同一分类内容（通用页 4 个新 toggle 在两端都出现）', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { unmount } = render(
      <QueryClientProvider client={qc}>
        <SettingsModal open onClose={() => {}} />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: /通用/ }))
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: '已读条目变暗开关' })).toBeInTheDocument()
    })
    unmount()

    render(
      <QueryClientProvider client={qc}>
        <MobileSettingsScreen open onClose={() => {}} />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: '通用' }))
    expect(screen.getByRole('switch', { name: '已读条目变暗开关' })).toBeInTheDocument()
  })
})
