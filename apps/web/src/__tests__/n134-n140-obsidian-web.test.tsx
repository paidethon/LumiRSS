/** N134-N140 Obsidian 交接闭环 — Web 面板测试。
 *
 * - N138：ObsidianPage 诊断显示最近一次扫描受影响文件（有界 + 截断
 *   诚实标注）；从未扫描 → 不冒充诊断。
 * - N140：交接记录面板 — pending/confirmed 状态徽章；confirmed 只能
 *   由显式点击产生（渲染 / 重载【绝不】自动确认）；清理按钮。
 * - N135：导出重名策略 UI + 「URI 无法检测同名笔记」诚实文案。
 * - N137：导出对话框「仅导出上次以来」开关 + 新增/修改增量预览。

 * 统一 vi.mock('../api/client')（保留真实导出）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { EntryDetail } from '../api/types'
import ObsidianPage from '../components/pages/ObsidianPage'
import ObsidianDevicesSection from '../components/obsidian/ObsidianDevicesSection'
import ObsidianHandoffLogSection from '../components/obsidian/ObsidianHandoffLogSection'
import ObsidianExportDialog from '../components/ObsidianExportDialog'

const mocks = vi.hoisted(() => ({
  getObsidianStatus: vi.fn(),
  listObsidianNotes: vi.fn(),
  listObsidianDevices: vi.fn(),
  getObsidianExportTemplate: vi.fn(),
  updateObsidianExportTemplate: vi.fn(),
  listObsidianHandoffLog: vi.fn(),
  confirmObsidianHandoff: vi.fn(),
  clearObsidianHandoffLog: vi.fn(),
  getAnnotationsExportDelta: vi.fn(),
  validateObsidianExport: vi.fn(),
  requestObsidianExportHandoff: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getObsidianStatus: mocks.getObsidianStatus,
    listObsidianNotes: mocks.listObsidianNotes,
    listObsidianDevices: mocks.listObsidianDevices,
    getObsidianExportTemplate: mocks.getObsidianExportTemplate,
    updateObsidianExportTemplate: mocks.updateObsidianExportTemplate,
    listObsidianHandoffLog: mocks.listObsidianHandoffLog,
    confirmObsidianHandoff: mocks.confirmObsidianHandoff,
    clearObsidianHandoffLog: mocks.clearObsidianHandoffLog,
    getAnnotationsExportDelta: mocks.getAnnotationsExportDelta,
    validateObsidianExport: mocks.validateObsidianExport,
    requestObsidianExportHandoff: mocks.requestObsidianExportHandoff,
  }
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

const STATUS_BASE = {
  vaultPath: '/vault',
  lastScanAt: '2026-09-23T08:00:00+00:00',
  lastError: null,
  noteCount: 2,
  envRootConfigured: false,
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

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listObsidianNotes.mockResolvedValue({ items: [] })
  mocks.listObsidianDevices.mockResolvedValue({ items: [] })
  mocks.getObsidianExportTemplate.mockResolvedValue({
    template: '',
    defaultTemplate: '{{title}}',
    allowedVars: ['title'],
    exportNamePolicy: 'timestamp_suffix',
  })
  mocks.listObsidianHandoffLog.mockResolvedValue({ items: [] })
  mocks.getAnnotationsExportDelta.mockResolvedValue({
    lastExportedAt: null,
    addedCount: 0,
    modifiedCount: 0,
    total: 0,
  })
  mocks.validateObsidianExport.mockResolvedValue({ issues: [], vaultChecked: false })
})

describe('N138 扫描诊断（ObsidianPage）', () => {
  it('展示最近一次扫描受影响文件；截断诚实标注', async () => {
    mocks.getObsidianStatus.mockResolvedValue({
      ...STATUS_BASE,
      lastScanFiles: {
        added: { items: ['a.md', 'b.md'], truncated: false },
        changed: { items: ['c.md'], truncated: false },
        removed: { items: [], truncated: false },
        skipped: { items: ['bin.md'], truncated: true },
      },
    })
    render(withProviders(<ObsidianPage />))
    const panel = await screen.findByLabelText('上次扫描受影响的文件')
    expect(panel).toHaveAttribute('data-lumi-scan-files')
    expect(panel).toHaveTextContent('新增：a.md、b.md')
    expect(panel).toHaveTextContent('更改：c.md')
    expect(panel).toHaveTextContent('跳过：bin.md（超过 50 项，已截断）')
  })

  it('从未扫描：不渲染诊断（不冒充同步状态）', async () => {
    mocks.getObsidianStatus.mockResolvedValue({ ...STATUS_BASE, lastScanFiles: null })
    render(withProviders(<ObsidianPage />))
    expect(await screen.findByText(/上次扫描/)).toBeInTheDocument()
    expect(document.querySelector('[data-lumi-scan-files]')).toBeNull()
  })
})

describe('N140 交接记录面板', () => {
  const ENTRY = {
    id: 'h1',
    direction: 'export',
    entryRef: 'e1.YQ',
    noteName: '文章.md',
    policy: 'timestamp_suffix',
    status: 'pending',
    createdAt: '2026-09-23T08:00:00+00:00',
    confirmedAt: null,
  }

  it('状态徽章如实展示；确认只能由显式点击产生（渲染不自动确认）', async () => {
    mocks.listObsidianHandoffLog.mockResolvedValue({ items: [ENTRY] })
    mocks.confirmObsidianHandoff.mockResolvedValue({ ...ENTRY, status: 'confirmed', confirmedAt: '2026-09-23T09:00:00+00:00' })
    render(withProviders(<ObsidianHandoffLogSection />))
    fireEvent.click(await screen.findByRole('button', { name: /交接记录/ }))
    const row = await screen.findByLabelText(/交接记录列表/)
    expect(row).toHaveTextContent('待确认')
    expect(row).toHaveTextContent('导出')
    // 渲染 + 列表重读（页面重载等被动事件）不触发确认。
    expect(mocks.confirmObsidianHandoff).not.toHaveBeenCalled()
    await waitFor(() => expect(mocks.listObsidianHandoffLog).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: /确认交接 文章\.md 已在 Obsidian 保存/ }))
    await waitFor(() => expect(mocks.confirmObsidianHandoff).toHaveBeenCalledWith('h1'))
  })

  it('清理按钮：DELETE 后如实显示条数', async () => {
    mocks.listObsidianHandoffLog.mockResolvedValue({ items: [ENTRY] })
    mocks.clearObsidianHandoffLog.mockResolvedValue({ cleared: 1 })
    render(withProviders(<ObsidianHandoffLogSection />))
    fireEvent.click(await screen.findByRole('button', { name: /交接记录/ }))
    fireEvent.click(await screen.findByRole('button', { name: '清理交接记录' }))
    expect(await screen.findByText('已清理 1 条记录')).toBeInTheDocument()
    await waitFor(() => expect(mocks.clearObsidianHandoffLog).toHaveBeenCalled())
  })

  it('空记录：诚实空态（不冒充有历史）', async () => {
    render(withProviders(<ObsidianHandoffLogSection />))
    fireEvent.click(await screen.findByRole('button', { name: /交接记录/ }))
    expect(await screen.findByText(/还没有交接记录/)).toBeInTheDocument()
  })
})

describe('N135 导出重名策略（设备与导出）', () => {
  it('展示策略选择 + 「URI 无法检测同名笔记」诚实文案；切换即保存', async () => {
    mocks.updateObsidianExportTemplate.mockResolvedValue({
      template: '',
      defaultTemplate: '{{title}}',
      allowedVars: ['title'],
      exportNamePolicy: 'exact',
    })
    render(withProviders(<ObsidianDevicesSection envRootConfigured={false} />))
    fireEvent.click(screen.getByRole('button', { name: /设备与导出/ }))
    const select = await screen.findByRole('combobox', { name: '导出重名处理' })
    expect(
      screen.getByText(/obsidian:\/\/ 链接无法检测 Vault 内是否已存在同名笔记/),
    ).toBeInTheDocument()
    fireEvent.change(select, { target: { value: 'exact' } })
    await waitFor(() =>
      expect(mocks.updateObsidianExportTemplate).toHaveBeenCalledWith(null, 'exact'),
    )
  })
})

describe('N137 增量批注导出（导出对话框）', () => {
  const DEVICE = {
    id: 'device-1',
    label: 'Windows 台式机',
    vaultName: 'V',
    vaultIdentifier: '',
    platform: 'windows',
    createdAt: '2026-09-23T00:00:00Z',
  }

  it('增量预览显示新增/修改计数；勾选后交接请求携带 onlySinceLastExport', async () => {
    mocks.listObsidianDevices.mockResolvedValue({ items: [DEVICE] })
    mocks.getAnnotationsExportDelta.mockResolvedValue({
      lastExportedAt: '2026-09-23T08:00:00+00:00',
      addedCount: 2,
      modifiedCount: 1,
      total: 3,
    })
    mocks.requestObsidianExportHandoff.mockResolvedValue({
      mode: 'uri',
      uri: 'obsidian://new?vault=V&file=x.md&content=hi',
      reason: null,
      filename: 'x.md',
      content: '# 文章',
      unknownVars: [],
      deviceLabel: 'Windows 台式机',
      annotationCount: 3,
    })
    render(withProviders(<ObsidianExportDialog open detail={entryFixture()} onClose={() => {}} />))
    expect(await screen.findByText('Windows 台式机')).toBeInTheDocument()
    expect(screen.getByText('上次导出之后：新增 2 · 修改 1')).toHaveAttribute(
      'data-lumi-export-delta',
    )

    fireEvent.click(screen.getByRole('checkbox', { name: '仅导出上次以来的批注' }))
    fireEvent.click(screen.getByRole('button', { name: /打开 Obsidian/ }))
    await waitFor(() =>
      expect(mocks.validateObsidianExport).toHaveBeenCalledWith('e1.YQ', 'device-1', {
        onlySinceLastExport: true,
      }),
    )
    await waitFor(() =>
      expect(mocks.requestObsidianExportHandoff).toHaveBeenCalledWith('e1.YQ', 'device-1', {
        onlySinceLastExport: true,
      }),
    )
  })

  it('从未导出：预览诚实说明（勾选增量将不带批注）', async () => {
    mocks.listObsidianDevices.mockResolvedValue({ items: [DEVICE] })
    render(withProviders(<ObsidianExportDialog open detail={entryFixture()} onClose={() => {}} />))
    expect(
      await screen.findByText(/这篇文章还没有导出记录（勾选增量将不带任何批注）。/),
    ).toBeInTheDocument()
  })
})
