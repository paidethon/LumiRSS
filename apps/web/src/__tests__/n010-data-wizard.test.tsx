/** N010 数据迁出/迁入向导 — 设置（数据控制）Web 测试。
 *
 * 迁出：范围展示（不可用组件诚实标注）+ zip 下载触发；
 * 迁入：文件选择 → 预览（计数 + 冲突）→ 选择组件 → 应用合并结果。
 * api/client 直接函数以 vi.mock 替身（fetch 不参与）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DataWizardSection } from '../components/settings/DataWizardSection'

const clientMocks = vi.hoisted(() => ({
  exportLumiDataZip: vi.fn(),
  previewLumiDataImport: vi.fn(),
  applyLumiDataImport: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    exportLumiDataZip: clientMocks.exportLumiDataZip,
    previewLumiDataImport: clientMocks.previewLumiDataImport,
    applyLumiDataImport: clientMocks.applyLumiDataImport,
  }
})

function renderWizard() {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/export/lumi-data/scope')) {
      return new Response(
        JSON.stringify({
          components: [
            { key: 'sources', label: '订阅来源', count: 0, available: false, reason: 'RSS 源绑定不可用' },
            { key: 'bookmarks', label: '书签与笔记', count: 3, available: true },
          ],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DataWizardSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

beforeEach(() => {
  clientMocks.exportLumiDataZip.mockReset()
  clientMocks.previewLumiDataImport.mockReset()
  clientMocks.applyLumiDataImport.mockReset()
})

describe('N010 数据迁出/迁入向导', () => {
  it('迁出 tab：范围展示（不可用组件诚实标注）+ 触发 zip 下载', async () => {
    clientMocks.exportLumiDataZip.mockResolvedValue(undefined)
    const fetchMock = renderWizard()
    const scope = await screen.findByTestId('lumi-export-scope')
    expect(scope).toHaveTextContent('RSS 源绑定不可用')
    expect(scope).toHaveTextContent('3 项')
    fireEvent.click(screen.getByTestId('lumi-export-zip'))
    await waitFor(() => expect(clientMocks.exportLumiDataZip).toHaveBeenCalled())
    // 范围查询确实走了 scope 端点（不下载前先看范围）
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/export/lumi-data/scope'))).toBe(true)
  })

  it('迁入 tab：预览（计数 + 冲突）→ 勾选组件 → 应用合并', async () => {
    clientMocks.previewLumiDataImport.mockResolvedValue({
      importId: 'imp-abc',
      components: [
        { key: 'bookmarks', label: '书签与笔记', count: 3, conflicts: 1 },
        { key: 'tags', label: '标签与条目绑定', count: 2, conflicts: 0 },
      ],
    })
    clientMocks.applyLumiDataImport.mockResolvedValue({
      components: {
        bookmarks: { added: 0, skipped: 1, failed: 2 },
        tags: { added: 2, skipped: 0, failed: 0 },
      },
    })
    renderWizard()
    fireEvent.click(screen.getByRole('tab', { name: '迁入' }))
    const file = new File(['zip'], 'data.zip', { type: 'application/zip' })
    const input = screen.getByLabelText('选择导出包文件')
    await waitFor(() => {
      fireEvent.change(input, { target: { files: [file] } })
    })
    const previewBox = await screen.findByTestId('lumi-import-preview')
    expect(previewBox).toHaveTextContent('3 项')
    expect(previewBox).toHaveTextContent('1 已存在，将跳过')
    expect(clientMocks.previewLumiDataImport).toHaveBeenCalledWith(file)
    fireEvent.click(screen.getByLabelText('导入 书签与笔记'))
    fireEvent.click(screen.getByLabelText('导入 标签与条目绑定'))
    fireEvent.click(screen.getByTestId('lumi-import-apply'))
    await waitFor(() => {
      expect(clientMocks.applyLumiDataImport).toHaveBeenCalledWith('imp-abc', ['bookmarks', 'tags'])
    })
    const result = await screen.findByTestId('lumi-import-result')
    expect(result).toHaveTextContent('新增 2')
    expect(result).toHaveTextContent('跳过 1')
    expect(result).toHaveTextContent('失败 2')
  })

  it('合并按钮在未选择组件时禁用（防误操作）', async () => {
    clientMocks.previewLumiDataImport.mockResolvedValue({
      importId: 'imp-abc',
      components: [{ key: 'bookmarks', label: '书签与笔记', count: 3, conflicts: 0 }],
    })
    renderWizard()
    fireEvent.click(screen.getByRole('tab', { name: '迁入' }))
    const file = new File(['zip'], 'data.zip', { type: 'application/zip' })
    fireEvent.change(screen.getByLabelText('选择导出包文件'), { target: { files: [file] } })
    const applyButton = await screen.findByTestId('lumi-import-apply')
    // 未选择任何组件 → 禁用（防误操作）
    expect(applyButton).toBeDisabled()
    fireEvent.click(screen.getByLabelText('导入 书签与笔记'))
    expect(applyButton).not.toBeDisabled()
    expect(clientMocks.applyLumiDataImport).not.toHaveBeenCalled()
  })
})
