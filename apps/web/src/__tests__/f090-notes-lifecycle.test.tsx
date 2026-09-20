/** F090 UI — 笔记生命周期：新建→列表、编辑乐观锁 409 诚实报错、
 * 预览净化（XSS 负向在 md-preview 单测里）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NotesManager } from '../components/NotesManager'
import { mdPreviewHtml } from '../lib/md-preview'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const NOTE = {
  uuid: 'note-1',
  title: '周会纪要',
  contentMd: '# 标题\n\n正文 **加粗**',
  workspaceId: null,
  createdAt: '2026-09-19T00:00:00Z',
  updatedAt: '2026-09-19T00:00:00Z',
}

function renderManager() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <NotesManager />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F090 Lumi 笔记全生命周期', () => {
  it('F090: 新建→列表出现；md 预览净化渲染', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/notes')) return Promise.resolve(jsonResponse({ items: [NOTE] }))
      if (method === 'POST' && url.endsWith('/notes')) return Promise.resolve(jsonResponse(NOTE, 201))
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderManager()

    expect(await screen.findByText('周会纪要')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '新建笔记' }))
    fireEvent.change(screen.getByLabelText('笔记标题'), { target: { value: '新笔记' } })
    fireEvent.change(screen.getByLabelText('笔记正文'), {
      target: { value: '# 计划\n\n- 第一项\n- 第二项' },
    })
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    const preview = screen.getByTestId('note-preview')
    expect(preview.querySelector('h1')?.textContent).toBe('计划')
    expect(preview.querySelectorAll('li').length).toBe(2)

    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/notes') && c[1]?.method === 'POST')
      expect(call).toBeDefined()
    })
  })

  it('F090: 编辑乐观锁冲突 409 note_conflict 诚实报错；删除走软删', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/notes')) return Promise.resolve(jsonResponse({ items: [NOTE] }))
      if (method === 'GET' && url.endsWith('/notes/note-1')) return Promise.resolve(jsonResponse(NOTE))
      if (method === 'PATCH' && url.endsWith('/notes/note-1')) {
        return Promise.resolve(
          jsonResponse({ error: { type: 'note_conflict', message: '笔记已被其他窗口修改，请刷新后重试。' } }, 409),
        )
      }
      if (method === 'DELETE' && url.endsWith('/notes/note-1')) return Promise.resolve(new Response(null, { status: 204 }))
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderManager()

    expect(await screen.findByText('周会纪要')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '编辑笔记' }))
    await waitFor(() => {
      expect(screen.getByLabelText('笔记正文')).toHaveValue(NOTE.contentMd)
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(screen.getByText(/note_conflict|其他窗口修改/)).toBeInTheDocument()
    })

    // 关闭仍打开的编辑对话框（409 后可重试，不自动丢弃）。
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    fireEvent.click(screen.getByRole('button', { name: '删除笔记（进入回收站）' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/notes/note-1') && c[1]?.method === 'DELETE')
      expect(call).toBeDefined()
    })
  })

  it('F090: md 预览 XSS 净化（script/img/危险协议不可存活；转义文本诚实降级）', () => {
    const html = mdPreviewHtml('# t\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">\n\n[x](javascript:alert(3))')
    expect(html).not.toContain('<script')
    expect(html).toContain('&lt;script&gt;')
    const holder = document.createElement('div')
    holder.innerHTML = html
    // DOM 级负向：注入语法绝不能活成元素/属性。
    expect(holder.querySelector('script')).toBeNull()
    expect(holder.querySelector('img')).toBeNull()
    expect(holder.querySelector('[onerror]')).toBeNull()
    expect(holder.querySelector('a[href^="javascript:"]')).toBeNull()
  })
})
