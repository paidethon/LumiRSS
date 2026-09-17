/** M4：GPT 日报设置 UI 行为测试。
 *
 * 断言 DOM 语义与交互：设置渲染、保存 PUT 载荷、立即生成的成功/失败
 * 透出、订阅地址展示与轮换。fetch 全部 stub，绝不触网（真实 GPT 调用
 * 与真实订阅端在集成层另行验证）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { GptDigestSection } from '../components/settings/GptDigestSection'

const SETTINGS = {
  enabled: false,
  hour: 8,
  timezone: 'Asia/Shanghai',
  windowHours: 24,
  limitCount: 12,
  lastIssueKey: null,
  lastError: null,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderSection(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    handler(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <GptDigestSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('GptDigestSection', () => {
  it('渲染设置与订阅地址；轮换后显示新地址', async () => {
    let token = 'tok-1'
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/settings')) return jsonResponse(SETTINGS)
      if (url.endsWith('/gpt-digest/issues')) return jsonResponse({ items: [] })
      if (url.endsWith('/gpt-digest/feed') && (!init || !init.method || init.method === 'GET')) {
        return jsonResponse({ atomPath: `/feeds/gpt-digest/${token}.atom` })
      }
      if (url.endsWith('/gpt-digest/feed/rotate')) {
        token = 'tok-2'
        return jsonResponse({ atomPath: `/feeds/gpt-digest/${token}.atom` })
      }
      throw new Error(`unexpected fetch: ${url}`)
    })

    expect(await screen.findByText('启用每日自动生成')).toBeInTheDocument()
    expect(screen.getByText(/feeds\/gpt-digest\/tok-1\.atom/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '轮换 token' }))
    await waitFor(() => {
      expect(screen.getByText(/tok-2\.atom/)).toBeInTheDocument()
    })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/gpt-digest/feed/rotate'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('修改设置后保存发出 PUT 载荷', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/settings')) {
        if (init?.method === 'PUT') return jsonResponse({ ...SETTINGS, hour: 7 })
        return jsonResponse(SETTINGS)
      }
      if (url.endsWith('/gpt-digest/issues')) return jsonResponse({ items: [] })
      if (url.endsWith('/gpt-digest/feed')) return jsonResponse({ atomPath: '/feeds/gpt-digest/tok.atom' })
      throw new Error(`unexpected fetch: ${url}`)
    })

    await screen.findByText('启用每日自动生成')
    const hourInput = screen.getByLabelText('发布小时')
    fireEvent.change(hourInput, { target: { value: '7' } })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/gpt-digest/settings'),
        expect.objectContaining({ method: 'PUT' }),
      )
    })
    const putCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/gpt-digest/settings') && init?.method === 'PUT',
    )
    expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({ hour: 7 })
  })

  it('立即生成失败原样透出服务端消息', async () => {
    renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/settings')) return jsonResponse(SETTINGS)
      if (url.endsWith('/gpt-digest/issues')) return jsonResponse({ items: [] })
      if (url.endsWith('/gpt-digest/feed')) return jsonResponse({ atomPath: '/feeds/gpt-digest/tok.atom' })
      if (url.endsWith('/gpt-digest/generate')) {
        return jsonResponse(
          { error: { type: 'no_material', message: '窗口内没有可用材料；未生成空日报。' } },
          422,
        )
      }
      throw new Error(`unexpected fetch: ${url}`)
    })

    await screen.findByText('启用每日自动生成')
    fireEvent.click(screen.getByRole('button', { name: /立即生成/ }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('窗口内没有可用材料')
    })
  })
})
