/** P16 导出到 Obsidian — ReaderHeader / ObsidianExportDialog 接线测试。
 *
 * 「更多操作」菜单出现「导出到 Obsidian」；点击打开对话框；选设备后
 * handoff 请求携带 entryRef+deviceId；outcome 诚实上屏（「已打开
 * Obsidian（请在 Obsidian 确认保存）」，绝无「已写入」）；无设备档案
 * 时空态引导，不假装可以导出。交接执行逻辑见 p16-obsidian-handoff-lib。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { EntryDetail } from '../api/types'
import ReaderHeader from '../components/ReaderHeader'
import ObsidianExportDialog from '../components/ObsidianExportDialog'

// ---- ReaderHeader / Dialog 接线（mock api client + handoff 执行器） ----

const mocks = vi.hoisted(() => ({
  listObsidianDevices: vi.fn(),
  requestObsidianExportHandoff: vi.fn(),
  getAiSettings: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listObsidianDevices: mocks.listObsidianDevices,
    requestObsidianExportHandoff: mocks.requestObsidianExportHandoff,
    getAiSettings: mocks.getAiSettings,
  }
})

const runHandoff = vi.hoisted(() => vi.fn())

vi.mock('../lib/obsidian-handoff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/obsidian-handoff')>()
  return {
    ...actual,
    runObsidianHandoff: runHandoff,
  }
})

const DEVICE = {
  id: 'device-1',
  label: 'Windows 台式机',
  vaultName: '我的笔记库',
  vaultIdentifier: '',
  platform: 'windows',
  createdAt: '2026-09-23T00:00:00Z',
}

function entryFixture(): EntryDetail {
  return {
    entryRef: 'e1.YQ',
    title: '测试文章',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: '<p>正文</p>',
  } as unknown as EntryDetail
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('ReaderHeader / ObsidianExportDialog 接线（P16）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getAiSettings.mockRejectedValue(new Error('skip'))
    runHandoff.mockResolvedValue({
      kind: 'uri-opened',
      message: '已打开 Obsidian（请在 Obsidian 确认保存）。内容同时已复制到剪贴板备用。',
      fallbackContent: null,
    })
  })

  it('「更多操作」含「导出到 Obsidian」；点击打开对话框并按所选设备交接', async () => {
    mocks.listObsidianDevices.mockResolvedValue({ items: [DEVICE] })
    mocks.requestObsidianExportHandoff.mockResolvedValue({
      mode: 'uri',
      uri: 'obsidian://new?vault=V&file=x.md&content=hi',
      reason: null,
      filename: 'x.md',
      content: '# 文章',
      unknownVars: [],
      deviceLabel: 'Windows 台式机',
    })

    render(withProviders(<ReaderHeader detail={entryFixture()} />))
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    const menu = await screen.findByRole('menu')
    fireEvent.click(within(menu).getByRole('menuitem', { name: '导出到 Obsidian' }))

    const dialog = await screen.findByRole('dialog', { name: '导出到 Obsidian' })
    expect(dialog).toBeInTheDocument()
    expect(await screen.findByText('Windows 台式机')).toBeInTheDocument()

    // 默认选中第一台 → 点击「打开 Obsidian」→ handoff 携带 entryRef+deviceId。
    fireEvent.click(screen.getByRole('button', { name: /打开 Obsidian/ }))
    await waitFor(() =>
      expect(mocks.requestObsidianExportHandoff).toHaveBeenCalledWith('e1.YQ', 'device-1'),
    )
    await waitFor(() => expect(runHandoff).toHaveBeenCalled())
    // 诚实文案上屏；「已写入」永不出现。
    expect(await screen.findByRole('status')).toHaveTextContent(
      '已打开 Obsidian（请在 Obsidian 确认保存）',
    )
    expect(screen.queryByText(/已写入/)).toBeNull()
  })

  it('无设备档案：空态引导去设置（不假装可以导出）', async () => {
    mocks.listObsidianDevices.mockResolvedValue({ items: [] })
    render(withProviders(<ObsidianExportDialog open detail={entryFixture()} onClose={() => {}} />))
    expect(await screen.findByText('还没有设备档案')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /打开 Obsidian/ })).toBeDisabled()
  })
})
