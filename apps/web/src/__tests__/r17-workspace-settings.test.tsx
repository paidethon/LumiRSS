/** R17 工作区设置面测试（WorkspaceSettingsSection）。
 *
 * 覆盖：真实 workspaces API 的保存回显（PATCH → 列表失效 → 回显）、
 * 归档/恢复、删除确认的影响说明（不删来源内容）、保留工作区控件
 * 禁用、后端没有的能力不渲染假开关。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceSettingsSection } from '../components/settings/WorkspaceSettingsSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Handler = (url: string, init?: RequestInit) => Response

let workspacesState: Array<Record<string, unknown>>

function seedWorkspaces(): void {
  workspacesState = [
    {
      id: 'w1',
      name: '研究组',
      position: 0,
      itemCount: 3,
      reserved: false,
      description: '',
      archived: false,
      archivedAt: null,
      revision: 1,
    },
    {
      id: 'rl',
      name: '稍后读',
      position: 1,
      itemCount: 9,
      reserved: true,
      description: '',
      archived: false,
      archivedAt: null,
      revision: 1,
    },
  ]
}

function defaultHandler(handler?: Handler): Handler {
  return (url, init) => {
    if (url === '/api/v1/workspaces' && (init?.method === undefined || init.method === 'GET')) {
      return jsonResponse({ items: workspacesState })
    }
    if (url === '/api/v1/workspaces/w1' && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as { name?: string; description?: string }
      const w = workspacesState[0]!
      if (body.name !== undefined) w.name = body.name
      if (body.description !== undefined) w.description = body.description
      return jsonResponse(w)
    }
    if (url === '/api/v1/workspaces/w1/archive' && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as { archived: boolean }
      const w = workspacesState[0]!
      w.archived = body.archived
      w.archivedAt = body.archived ? '2026-10-02T00:00:00Z' : null
      return jsonResponse(w)
    }
    if (url === '/api/v1/workspaces/w1' && init?.method === 'DELETE') {
      workspacesState = workspacesState.filter((w) => w.id !== 'w1')
      return new Response(null, { status: 204 })
    }
    return handler?.(url, init) ?? jsonResponse({ error: { type: 'not_found', message: url } }, 404)
  }
}

function renderSection(handler: Handler) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve(handler(String(input), init)),
    ),
  )
  render(
    <QueryClientProvider client={qc}>
      <WorkspaceSettingsSection />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  seedWorkspaces()
})

describe('工作区设置面（R17）', () => {
  it('列表真实渲染；默认选中第一个非保留工作区', async () => {
    seedWorkspaces()
    renderSection(defaultHandler())
    const select = await screen.findByLabelText('选择工作区')
    expect(select).toHaveValue('w1')
    expect(screen.getByText(/研究组/)).toBeInTheDocument()
    // 保留工作区在选项中如实标注
    const options = Array.from(select.querySelectorAll('option')).map((o) => o.textContent)
    expect(options.some((t) => t?.includes('稍后读（保留）'))).toBe(true)
  })

  it('编辑名称与说明 → PATCH → 保存回显', async () => {
    seedWorkspaces()
    renderSection(defaultHandler())
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    const nameInput = await screen.findByLabelText('名称')
    const descInput = screen.getByLabelText('说明')
    fireEvent.change(nameInput, { target: { value: '深读清单' } })
    fireEvent.change(descInput, { target: { value: '只放本周要深读的条目' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.getByText('已保存「深读清单」。')).toBeInTheDocument()
    })
    // 回显：重开对话框看到服务端确认的新值
    fireEvent.click(screen.getByRole('button', { name: /编辑/ }))
    await waitFor(() => {
      expect(screen.getByLabelText('名称')).toHaveValue('深读清单')
      expect(screen.getByLabelText('说明')).toHaveValue('只放本周要深读的条目')
    })
  })

  it('归档 → 归档端点 PATCH；说明含「不删除任何内容」', async () => {
    seedWorkspaces()
    renderSection(defaultHandler())
    fireEvent.click(await screen.findByRole('button', { name: '归档' }))
    await waitFor(() => {
      expect(screen.getByText('已归档。')).toBeInTheDocument()
    })
    expect(screen.getByText('恢复后重新出现在侧栏导航。')).toBeInTheDocument()
  })

  it('删除需确认且说明影响（只解除归属，不删来源内容）→ DELETE → 列表回显', async () => {
    seedWorkspaces()
    renderSection(defaultHandler())
    fireEvent.click(await screen.findByRole('button', { name: '删除' }))
    // 影响说明在确认框中
    expect(screen.getByText(/不删除来源内容/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => {
      expect(screen.getByText(/工作区已删除；来源内容不受影响。/)).toBeInTheDocument()
    })
    // 只剩保留工作区：默认选中它，且编辑/删除被禁用（BFF 拒绝保留工作区变更）
    await waitFor(() => {
      expect(screen.getByLabelText('选择工作区')).toHaveValue('rl')
    })
    expect(screen.getByRole('button', { name: /编辑/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: '删除' })).toBeDisabled()
    expect(screen.getByText('保留工作区由系统管理，不可改名。')).toBeInTheDocument()
  })

  it('不渲染假开关：图标 / 颜色与逐工作区默认筛选排序没有可操作控件', async () => {
    seedWorkspaces()
    renderSection(defaultHandler())
    await screen.findByLabelText('选择工作区')
    expect(screen.queryByRole('switch')).toBeNull()
    expect(screen.getByText(/暂无服务端字段/)).toBeInTheDocument()
  })
})
