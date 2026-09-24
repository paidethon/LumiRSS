/** P16 导出到 Obsidian — ReaderHeader / ObsidianExportDialog 接线测试。
 *
 * 「更多操作」菜单出现「导出到 Obsidian」；点击打开对话框；选设备后
 * 校验（N139 只读）→ handoff 请求携带 entryRef+deviceId（N137 增量
 * 开关）；outcome 诚实上屏（「已打开 Obsidian（请在 Obsidian 确认保
 * 存）」，绝无「已写入」）；校验发现问题时先展示报告、绝不静默交接；
 * 无设备档案时空态引导。交接执行逻辑见 p16-obsidian-handoff-lib。 */

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
  validateObsidianExport: vi.fn(),
  getObsidianExportTemplate: vi.fn(),
  getAnnotationsExportDelta: vi.fn(),
  getAiSettings: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listObsidianDevices: mocks.listObsidianDevices,
    requestObsidianExportHandoff: mocks.requestObsidianExportHandoff,
    validateObsidianExport: mocks.validateObsidianExport,
    getObsidianExportTemplate: mocks.getObsidianExportTemplate,
    getAnnotationsExportDelta: mocks.getAnnotationsExportDelta,
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
    mocks.getObsidianExportTemplate.mockResolvedValue({
      template: '',
      defaultTemplate: '{{title}}',
      allowedVars: ['title'],
      exportNamePolicy: 'timestamp_suffix',
    })
    mocks.getAnnotationsExportDelta.mockResolvedValue({
      lastExportedAt: null,
      addedCount: 0,
      modifiedCount: 0,
      total: 0,
    })
    mocks.validateObsidianExport.mockResolvedValue({ issues: [], vaultChecked: false })
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
      annotationCount: 0,
    })

    render(withProviders(<ReaderHeader detail={entryFixture()} />))
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    const menu = await screen.findByRole('menu')
    fireEvent.click(within(menu).getByRole('menuitem', { name: '导出到 Obsidian' }))

    const dialog = await screen.findByRole('dialog', { name: '导出到 Obsidian' })
    expect(dialog).toBeInTheDocument()
    expect(await screen.findByText('Windows 台式机')).toBeInTheDocument()

    // 默认选中第一台 → 点击「打开 Obsidian」→ 先只读校验（N139），
    // 通过后 handoff 携带 entryRef+deviceId（N137 增量开关默认关）。
    fireEvent.click(screen.getByRole('button', { name: /打开 Obsidian/ }))
    await waitFor(() =>
      expect(mocks.validateObsidianExport).toHaveBeenCalledWith(
        'e1.YQ',
        'device-1',
        { onlySinceLastExport: false },
      ),
    )
    await waitFor(() =>
      expect(mocks.requestObsidianExportHandoff).toHaveBeenCalledWith(
        'e1.YQ',
        'device-1',
        { onlySinceLastExport: false },
      ),
    )
    await waitFor(() => expect(runHandoff).toHaveBeenCalled())
    // 诚实文案上屏；「已写入」永不出现。
    expect(await screen.findByRole('status')).toHaveTextContent(
      '已打开 Obsidian（请在 Obsidian 确认保存）',
    )
    expect(screen.queryByText(/已写入/)).toBeNull()
  })

  it('N139 校验发现问题：先诚实展示报告，交接必须显式二次确认', async () => {
    mocks.listObsidianDevices.mockResolvedValue({ items: [DEVICE] })
    mocks.validateObsidianExport.mockResolvedValue({
      issues: [
        {
          kind: 'broken_wikilink',
          detail: '[[幽灵笔记]]：投影索引中没有匹配的笔记。',
          suggestion: '确认目标笔记已同步，或修正链接名。',
        },
      ],
      vaultChecked: false,
    })
    mocks.requestObsidianExportHandoff.mockResolvedValue({
      mode: 'uri',
      uri: 'obsidian://new?vault=V&file=x.md&content=hi',
      reason: null,
      filename: 'x.md',
      content: '# 文章',
      unknownVars: [],
      deviceLabel: 'Windows 台式机',
      annotationCount: 0,
    })

    render(withProviders(<ObsidianExportDialog open detail={entryFixture()} onClose={() => {}} />))
    // 等设备档案就绪（未就绪时主按钮禁用，点击无效）。
    expect(await screen.findByText('Windows 台式机')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /打开 Obsidian/ }))

    // 校验报告上屏（role=alert），此时【没有】发生交接。
    expect(await screen.findByRole('alert')).toHaveTextContent('断链 wikilink')
    expect(mocks.requestObsidianExportHandoff).not.toHaveBeenCalled()
    expect(runHandoff).not.toHaveBeenCalled()

    // 显式「仍然继续导出」→ 才真正交接。
    fireEvent.click(screen.getByRole('button', { name: '仍然继续导出' }))
    await waitFor(() => expect(mocks.requestObsidianExportHandoff).toHaveBeenCalled())
    expect(await screen.findByRole('status')).toHaveTextContent(
      '已打开 Obsidian（请在 Obsidian 确认保存）',
    )
  })

  it('无设备档案：空态引导去设置（不假装可以导出）', async () => {
    mocks.listObsidianDevices.mockResolvedValue({ items: [] })
    render(withProviders(<ObsidianExportDialog open detail={entryFixture()} onClose={() => {}} />))
    expect(await screen.findByText('还没有设备档案')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /打开 Obsidian/ })).toBeDisabled()
  })
})
