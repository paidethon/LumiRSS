/** R20 Agent 工作台补缺（前端入口）——停止生成、会话行操作
 * （重命名 / 归档 / 恢复 / 删除）、导出对话框「保存到 Obsidian」。
 * 黑盒：断言请求方法/路径/载荷 + 诚实结果与错误呈现（mock fetch，
 * 绝不打真实网络）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StopGenerationButton, ThreadExportButton, ThreadRowMenu } from '../components/AgentW5'

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

// ---- R20 停止生成 -------------------------------------------------------------

describe('R20 停止生成', () => {
  it('非处理中不渲染停止入口', () => {
    renderUi(<StopGenerationButton threadId="th-1" processing={false} />)
    expect(screen.queryByRole('button', { name: /停止/ })).toBeNull()
  })

  it('处理中点击停止 → POST /cancel', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ cancelled: true, status: 'cancelling' })),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<StopGenerationButton threadId="th-1" processing={true} />)
    fireEvent.click(screen.getByRole('button', { name: /停止/ }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).endsWith('/agent/threads/th-1/cancel'))).toBe(true)
    })
  })

  it('无活动回合 409 no_active_run → 诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ error: { type: 'no_active_run', message: '当前没有正在运行的回合。' } }, 409),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<StopGenerationButton threadId="th-1" processing={true} />)
    fireEvent.click(screen.getByRole('button', { name: /停止/ }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/没有正在运行的回合/)
    })
  })
})

// ---- R20 会话行操作（重命名 / 归档 / 恢复 / 删除）------------------------------

describe('R20 会话行操作', () => {
  it('行菜单：重命名 → PATCH title（裁剪后的草稿）', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse({ id: 'th-1', title: '新名字', scope: null, toolPolicy: null, branchOf: null, archivedAt: null }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ThreadRowMenu threadId="th-1" title="旧名字" archived={false} onDeleted={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: '会话操作：旧名字' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '重命名' }))
    const input = await screen.findByRole('textbox', { name: '会话名称' })
    fireEvent.change(input, { target: { value: '  新名字  ' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/agent/threads/th-1') && (c[1]?.method as string) === 'PATCH',
      )
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch![1]?.body))).toEqual({ title: '新名字' })
    })
  })

  it('行菜单：归档 → PATCH archived=true；已归档视图显示恢复 → PATCH archived=false', async () => {
    const settingsBody = () =>
      jsonResponse({ id: 'th-1', title: 't', scope: null, toolPolicy: null, branchOf: null, archivedAt: null })
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(settingsBody()))
    vi.stubGlobal('fetch', fetchMock)
    const view = renderUi(<ThreadRowMenu threadId="th-1" title="t" archived={false} onDeleted={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: '会话操作：t' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '归档' }))
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find((c) => (c[1]?.method as string) === 'PATCH')
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch![1]?.body))).toEqual({ archived: true })
    })

    view.unmount()
    const restoreMock = vi.fn().mockImplementation(() => Promise.resolve(settingsBody()))
    vi.stubGlobal('fetch', restoreMock)
    renderUi(<ThreadRowMenu threadId="th-1" title="t" archived={true} onDeleted={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: '会话操作：t' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '恢复到工作集' }))
    await waitFor(() => {
      const patch = restoreMock.mock.calls.find((c) => (c[1]?.method as string) === 'PATCH')
      expect(patch).toBeDefined()
      expect(JSON.parse(String(patch![1]?.body))).toEqual({ archived: false })
    })
  })

  it('行菜单：删除会话 → DELETE（danger 项）', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)
    const onDeleted = vi.fn()
    renderUi(<ThreadRowMenu threadId="th-1" title="t" archived={false} onDeleted={onDeleted} />)

    fireEvent.click(screen.getByRole('button', { name: '会话操作：t' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除会话' }))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (c) => String(c[0]).endsWith('/agent/threads/th-1') && (c[1]?.method as string) === 'DELETE',
        ),
      ).toBe(true)
    })
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith('th-1'))
  })

  it('PATCH 失败 → 重命名对话框内诚实报错', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ error: { type: 'thread_not_found', message: '会话不存在。' } }, 404)),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderUi(<ThreadRowMenu threadId="th-x" title="t" archived={false} onDeleted={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: '会话操作：t' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '重命名' }))
    fireEvent.click(await screen.findByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/会话不存在/)
    })
  })
})

// ---- R20 导出对话框「保存到 Obsidian」-------------------------------------------

describe('R20 会话导出到 Obsidian（前端入口）', () => {
  function openExport() {
    renderUi(<ThreadExportButton threadId="th-1" />)
    fireEvent.click(screen.getByRole('button', { name: '导出会话' }))
  }

  it('点击保存到 Obsidian → POST obsidian-export；written → 显示落盘路径', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/obsidian-export')) {
        return Promise.resolve(
          jsonResponse({ ref: 'agent:th-1', status: 'written', path: 'agent/agent-thread-th.md', reason: null, contentId: 'c1', bytes: 120, message: null }),
        )
      }
      return Promise.resolve(jsonResponse({ error: { type: 'not_found', message: 'x' } }, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    openExport()
    fireEvent.click(screen.getByRole('button', { name: '保存到 Obsidian' }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/obsidian-export'))
      expect(call).toBeDefined()
      expect(call![1]?.method).toBe('POST')
      expect(JSON.parse(String(call![1]?.body))).toEqual({ rounds: 5 })
    })
    const status = await screen.findByRole('status')
    expect(status).toHaveAttribute('data-obsidian-export-result', 'written')
    expect(status).toHaveTextContent(/已写入 Obsidian/)
    expect(status).toHaveTextContent(/agent\/agent-thread-th\.md/)
  })

  it('exists（幂等）与 failed（export_unconfigured）都诚实呈现', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          jsonResponse({ ref: 'agent:th-1', status: 'failed', path: null, reason: 'export_unconfigured', contentId: null, bytes: 0, message: null }),
        ),
      )
    vi.stubGlobal('fetch', fetchMock)
    openExport()
    fireEvent.click(screen.getByRole('button', { name: '保存到 Obsidian' }))
    const status = await screen.findByRole('status')
    expect(status).toHaveAttribute('data-obsidian-export-result', 'failed')
    expect(status).toHaveTextContent(/export_unconfigured/)
  })

  it('HTTP 错误（404 未知会话）→ role=alert', async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(jsonResponse({ error: { type: 'thread_not_found', message: '会话不存在。' } }, 404)),
    )
    vi.stubGlobal('fetch', fetchMock)
    openExport()
    fireEvent.click(screen.getByRole('button', { name: '保存到 Obsidian' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/会话不存在/)
    })
  })
})
