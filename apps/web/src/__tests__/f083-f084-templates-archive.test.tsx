/** F083/F084 UI — 工作区模板（列表/从模板创建/删除、同名 409）与
 * 归档条（归档列表显式可见 + 恢复）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TemplatesDialog } from '../components/WorkspaceExtras'
import { ArchivedBar } from '../components/WorkspaceExtras'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderUi(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F083 工作区模板', () => {
  const TEMPLATE = { id: 'tpl-1', name: '周报模板', config: { description: 'd' }, createdAt: '2026-09-19T00:00:00Z' }

  it('F083: 模板列表→选择→从模板创建（带示例条目开关）', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/workspace-templates')) {
        return Promise.resolve(jsonResponse({ items: [TEMPLATE] }))
      }
      if (method === 'POST' && url.endsWith('/from-template')) {
        return Promise.resolve(
          jsonResponse({
            workspace: { id: 'ws-new', name: '我的周报', position: 9, itemCount: 0, reserved: false, description: null, archived: false, archivedAt: null },
            addedExampleRefs: [],
            skippedExampleRefs: ['library:dead'],
          }),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<TemplatesDialog onClose={() => {}} />)

    expect(await screen.findByText('周报模板')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('选择模板：周报模板'))
    fireEvent.change(screen.getByLabelText('新工作区名'), { target: { value: '我的周报' } })
    fireEvent.click(screen.getByLabelText(/加入示例条目/))
    fireEvent.click(screen.getByRole('button', { name: '从模板创建' }))

    await waitFor(() => {
      expect(screen.getByText(/跳过失效示例 ref/)).toBeInTheDocument()
    })
    const call = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/from-template'))
    const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as Record<string, unknown>
    expect(body.templateId).toBe('tpl-1')
    expect(body.name).toBe('我的周报')
    expect(body.includeExampleItems).toBe(true)
  })

  it('F083: 同名模板 409 诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/workspace-templates')) {
        return Promise.resolve(jsonResponse({ items: [TEMPLATE] }))
      }
      if (method === 'POST' && url.endsWith('/from-template')) {
        return Promise.resolve(
          jsonResponse({ error: { type: 'template_name_conflict', message: '同名模板已存在。' } }, 409),
        )
      }
      return Promise.resolve(jsonResponse({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<TemplatesDialog onClose={() => {}} />)

    fireEvent.click(await screen.findByLabelText('选择模板：周报模板'))
    fireEvent.change(screen.getByLabelText('新工作区名'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: '从模板创建' }))
    await waitFor(() => {
      expect(screen.getByText(/同名模板已存在/)).toBeInTheDocument()
    })
  })
})

describe('F084 工作区归档（归档条）', () => {
  it('F084: 归档列表显式可见 + 恢复按钮调用 restore', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'GET' && url.endsWith('/workspace-archive')) {
        return Promise.resolve(
          jsonResponse([{
            id: 'ws-arch', name: '旧项目', position: 8, itemCount: 3, reserved: false,
            description: null, archived: true, archivedAt: '2026-09-18T00:00:00Z',
            revision: 1,
            // N119：归档摘要卡（服务端真实行派生）。
            summary: {
              itemCount: 3, doneCount: 2,
              goalProgress: { targetCount: 5, doneCount: 2 },
              archivedAt: '2026-09-18T00:00:00Z', daysActive: 12,
            },
          }]),
        )
      }
      if (method === 'PATCH' && url.endsWith('/workspaces/ws-arch/archive')) {
        return Promise.resolve(
          jsonResponse({ id: 'ws-arch', name: '旧项目', position: 8, itemCount: 3, reserved: false, description: null, archived: false, archivedAt: null }),
        )
      }
      return Promise.resolve(jsonResponse([]))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ArchivedBar />)

    expect(await screen.findByText('已归档：')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '恢复工作区 旧项目' }))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/workspaces/ws-arch/archive') && c[1]?.method === 'PATCH',
      )
      expect(call).toBeDefined()
      const body = JSON.parse(String(call?.[1]?.body ?? '{}')) as { archived: boolean }
      expect(body.archived).toBe(false)
    })
  })
})
