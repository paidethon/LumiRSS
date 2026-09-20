/** F030 问答模板（Web）—— 选择填入 / 存为模板 / 管理重命名删除。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QaTemplateBar from '../components/QaTemplateBar'

const TEMPLATES = {
  items: [
    {
      id: 'qt-1',
      name: '总结模板',
      text: '请总结这篇文章的三个要点<script>alert(1)</script>',
      createdAt: '2026-09-19T00:00:00Z',
      updatedAt: '2026-09-19T00:00:00Z',
    },
  ],
}

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const method = init?.method ?? 'GET'
  if (method === 'GET' && url.includes('/qa-templates')) {
    return Promise.resolve(new Response(JSON.stringify(TEMPLATES), { status: 200 }))
  }
  if (method === 'POST' && url.includes('/qa-templates')) {
    return Promise.resolve(new Response(JSON.stringify(TEMPLATES.items[0]), { status: 201 }))
  }
  if (method === 'PATCH' && url.includes('/qa-templates/qt-1')) {
    return Promise.resolve(
      new Response(JSON.stringify({ ...TEMPLATES.items[0], name: '改名后' }), { status: 200 }),
    )
  }
  if (method === 'DELETE' && url.includes('/qa-templates/')) {
    return Promise.resolve(new Response('', { status: 204 }))
  }
  return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }))
})

function renderBar(draft = '') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const onPick = vi.fn()
  const view = render(
    <QueryClientProvider client={qc}>
      <QaTemplateBar draft={draft} onPick={onPick} />
    </QueryClientProvider>,
  )
  return { onPick, view }
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
})

describe('F030 问答模板', () => {
  it('F030: 选择模板即填入输入框（onPick 回调携带文本；XSS 文本不执行）', async () => {
    const { onPick } = renderBar()
    await screen.findAllByText((_, el) => el?.tagName === 'OPTION' && el.textContent === '总结模板')
    fireEvent.change(screen.getByLabelText('问答模板'), {
      target: { value: 'qt-1' },
    })
    await waitFor(() => {
      expect(onPick).toHaveBeenCalledTimes(1)
    })
    const text = onPick.mock.calls[0][0] as string
    expect(text).toContain('<script>')
    // React 转义渲染：管理面板中显示为纯文本（无 script 元素被创建）
    fireEvent.click(screen.getByRole('button', { name: '管理' }))
    expect((await screen.findAllByText((_, el) => /总结模板/.test(el?.textContent ?? ''))).length).toBeGreaterThan(0)
    expect(document.querySelector('script')).toBeNull()
  })

  it('F030: 存为模板 POST 当前输入；重命名/删除生效', async () => {
    renderBar('这篇文章的作者立场是什么？')
    fireEvent.click(await screen.findByRole('button', { name: '存为模板' }))
    fireEvent.change(screen.getByLabelText('模板名称'), { target: { value: '立场模板' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/qa-templates') && (init as RequestInit).method === 'POST',
      )
      expect(post).toBeTruthy()
      const body = JSON.parse(String((post as unknown as [string, RequestInit])[1].body))
      expect(body).toEqual({ name: '立场模板', text: '这篇文章的作者立场是什么？' })
    })
    // 管理：重命名 → PATCH；删除 → DELETE
    fireEvent.click(screen.getByRole('button', { name: '管理' }))
    fireEvent.click(await screen.findByRole('button', { name: '重命名 总结模板' }))
    fireEvent.click(screen.getByRole('button', { name: '确定' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('qt-1') && (init as RequestInit).method === 'PATCH')).toBe(true)
    })
    fireEvent.click(await screen.findByRole('button', { name: '删除模板 总结模板' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('qt-1') && (init as RequestInit).method === 'DELETE')).toBe(true)
    })
  })
})
