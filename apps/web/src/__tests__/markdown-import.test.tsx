/** F020 Markdown 批量导入面板 —— 预览零请求、部分失败诚实展示、幂等跳过文案。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MarkdownImportPanel } from '../components/MarkdownImportPanel'

const fetchMock = vi.fn()

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function makeFiles(specs: { name: string; size?: number; text?: string }[]): FileList {
  const files = specs.map((spec) => {
    const text = spec.text ?? `${spec.name} 的正文`
    const file = new File([text], spec.name, { type: 'text/markdown' })
    if (spec.size !== undefined) {
      Object.defineProperty(file, 'size', { value: spec.size })
    }
    return file
  })
  return files as unknown as FileList
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MarkdownImportPanel onClose={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

describe('F020 Markdown 导入面板', () => {
  it('F020: 选择文件 → 预览表（零请求）；确认导入才发请求并展示逐项结果', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/library/notes/import')) {
        return Promise.resolve(
          jsonResponse({
            items: [
              { name: '笔记A.md', ok: true, uuid: 'n1', reason: null },
              { name: '重复.md', ok: true, uuid: 'n2', reason: 'duplicate' },
            ],
            imported: 1,
            skipped: 1,
          }),
        )
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })

    renderPanel()
    const input = await screen.findByLabelText('选择 Markdown 文件（可多选）')
    fireEvent.change(input, {
      target: { files: makeFiles([{ name: '笔记A.md' }, { name: '重复.md' }]) },
    })

    // 预览表渲染（纯客户端：不发任何请求）
    expect(await screen.findByText('笔记A.md')).toBeInTheDocument()
    expect(screen.getByText('重复.md')).toBeInTheDocument()
    expect(screen.getAllByText('将导入').length).toBe(2)
    expect(fetchMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /确认导入（2）/ }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(await screen.findByText(/成功 2 \/ 失败 0/)).toBeInTheDocument()
    expect(screen.getByText(/跳过（内容已存在）/)).toBeInTheDocument()

    const call = fetchMock.mock.calls.find(([u]) => String(u).includes('/library/notes/import'))
    expect(call).toBeDefined()
    const payload = JSON.parse(call![1]!.body as string)
    expect(payload.files).toHaveLength(2)
  })

  it('F020: 超 200KB 文件在预览标注「超过 200KB」且不计入可导入数', async () => {
    renderPanel()
    const input = await screen.findByLabelText('选择 Markdown 文件（可多选）')
    fireEvent.change(input, {
      target: {
        files: makeFiles([
          { name: '大文件.md', size: 200 * 1024 + 1 },
          { name: '正常.md', size: 10 },
        ]),
      },
    })
    expect(await screen.findByText('超过 200KB')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /确认导入（1）/ })).toBeInTheDocument()
  })
})
