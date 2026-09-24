/** P16 导出模板编辑器 —— 变量 chips、实时预览（防抖 → 服务端渲染）、
 * 未知变量诚实报错（role=alert，不静默透传）、保存 / 恢复默认。
 *
 * 统一 vi.mock('../api/client')（保留真实导出）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ObsidianDevicesSection from '../components/obsidian/ObsidianDevicesSection'

const mocks = vi.hoisted(() => ({
  listObsidianDevices: vi.fn(),
  getObsidianExportTemplate: vi.fn(),
  updateObsidianExportTemplate: vi.fn(),
  previewObsidianExportTemplate: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listObsidianDevices: mocks.listObsidianDevices,
    getObsidianExportTemplate: mocks.getObsidianExportTemplate,
    updateObsidianExportTemplate: mocks.updateObsidianExportTemplate,
    previewObsidianExportTemplate: mocks.previewObsidianExportTemplate,
  }
})

const DEFAULT_TEMPLATE =
  '{{title}}\n\n> 摘自 LumiRSS: {{url}}\n\n{{content}}\n\n— {{source}} {{date}}'

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function renderEditor() {
  render(withProviders(<ObsidianDevicesSection envRootConfigured={false} />))
  fireEvent.click(screen.getByRole('button', { name: /设备与导出/ }))
}

describe('ObsidianDevicesSection 模板编辑器（P16）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listObsidianDevices.mockResolvedValue({ items: [] })
    mocks.getObsidianExportTemplate.mockResolvedValue({
      template: '',
      defaultTemplate: DEFAULT_TEMPLATE,
      allowedVars: ['title', 'url', 'source', 'date', 'content', 'annotations', 'published'],
      exportNamePolicy: 'timestamp_suffix',
    })
    mocks.previewObsidianExportTemplate.mockResolvedValue({
      text: '渲染结果',
      unknownVars: [],
      source: 'fixture',
    })
  })

  it('空模板 = 跟随默认：占位展示默认模板 + 状态说明；变量 chips 齐全', async () => {
    renderEditor()
    // 状态行只有模板数据到达后才渲染 —— 先等它，再做其余断言。
    expect(await screen.findByText(/当前使用默认模板/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '导出模板' })).toBeInTheDocument()
    const editor = screen.getByLabelText('导出模板')
    expect(editor).toHaveAttribute('placeholder', DEFAULT_TEMPLATE)
    for (const v of ['title', 'annotations', 'published']) {
      expect(screen.getByText(`{{${v}}}`)).toBeInTheDocument()
    }
    // 实时预览对初始（空=默认）模板也会触发一次（客户端函数收位置参数）。
    await waitFor(() =>
      expect(mocks.previewObsidianExportTemplate).toHaveBeenCalledWith('', undefined),
    )
  })

  it('未知变量：预览结果 unknownVars 以 role=alert 诚实列出（不静默）', async () => {
    mocks.previewObsidianExportTemplate.mockResolvedValue({
      text: '标题（变量已移除）',
      unknownVars: ['oops', 'nickname'],
      source: 'fixture',
    })
    renderEditor()
    const editor = await screen.findByLabelText('导出模板')
    fireEvent.change(editor, { target: { value: '{{title}} {{oops}} {{nickname}}' } })
    // 防抖 400ms 后才请求 → 等待服务端返回的未知变量清单上屏。
    expect(
      await screen.findByText(/模板含不支持的变量：\{\{oops\}\}、\{\{nickname\}\}/),
    ).toHaveAttribute('role', 'alert')
    expect(screen.getByRole('alert')).toHaveTextContent('按空值渲染')
  })

  it('保存模板：updateObsidianExportTemplate 收到草稿；保存成功提示', async () => {
    mocks.updateObsidianExportTemplate.mockResolvedValue({
      template: '{{title}}-自定义',
      defaultTemplate: DEFAULT_TEMPLATE,
      allowedVars: ['title'],
      exportNamePolicy: 'timestamp_suffix',
    })
    renderEditor()
    const editor = await screen.findByLabelText('导出模板')
    fireEvent.change(editor, { target: { value: '{{title}}-自定义' } })
    const save = await screen.findByRole('button', { name: /保存模板/ })
    await waitFor(() => expect(save).not.toBeDisabled())
    fireEvent.click(save)
    await waitFor(() =>
      expect(mocks.updateObsidianExportTemplate).toHaveBeenCalledWith('{{title}}-自定义'),
    )
    expect(await screen.findByText('模板已保存')).toBeInTheDocument()
  })

  it('恢复默认：提交空模板（服务端回退默认）', async () => {
    mocks.getObsidianExportTemplate.mockResolvedValue({
      template: '{{title}}-自定义',
      defaultTemplate: DEFAULT_TEMPLATE,
      allowedVars: ['title'],
      exportNamePolicy: 'timestamp_suffix',
    })
    mocks.updateObsidianExportTemplate.mockResolvedValue({
      template: '',
      defaultTemplate: DEFAULT_TEMPLATE,
      allowedVars: ['title'],
      exportNamePolicy: 'timestamp_suffix',
    })
    renderEditor()
    const reset = await screen.findByRole('button', { name: /恢复默认/ })
    await waitFor(() => expect(reset).not.toBeDisabled())
    fireEvent.click(reset)
    await waitFor(() => expect(mocks.updateObsidianExportTemplate).toHaveBeenCalledWith(''))
  })

  it('预览失败：错误诚实透出（不显示旧结果冒充成功）', async () => {
    mocks.previewObsidianExportTemplate.mockRejectedValue(new Error('preview down'))
    renderEditor()
    expect(await screen.findByText(/预览失败：preview down/)).toBeInTheDocument()
  })
})
