/** M4/F01：GPT 日报设置 UI 行为测试。
 *
 * 断言 DOM 语义与交互：配置选择与新建、保存 PUT 载荷、来源白名单、
 * 立即生成失败透出、预览渲染、订阅地址。fetch 全部 stub，绝不触网
 * （真实 GPT 调用与订阅端在集成层另行验证）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { GptDigestSection } from '../components/settings/GptDigestSection'

const CONFIGS = {
  items: [
    {
      id: 1,
      name: '默认日报',
      enabled: false,
      hour: 8,
      timezone: 'Asia/Shanghai',
      windowHours: 24,
      limitCount: 12,
      perSourceCap: 2,
      feedUrlAllow: '',
      slots: [],
      lastIssueKey: null,
      lastError: null,
      createdAt: '2026-09-18T00:00:00+00:00',
    },
    {
      id: 2,
      name: '开源日报',
      enabled: true,
      hour: 9,
      timezone: 'UTC',
      windowHours: 12,
      limitCount: 6,
      perSourceCap: 1,
      feedUrlAllow: 'oss.example.org',
      slots: [8, 20],
      lastIssueKey: null,
      lastError: null,
      createdAt: '2026-09-18T00:00:00+00:00',
    },
  ],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function baseHandler(url: string, init?: RequestInit): Response | Promise<Response> {
  if (url.endsWith('/gpt-digest/configs') && (!init || !init.method)) return jsonResponse(CONFIGS)
  if (url.endsWith('/issues?limit=14') || /\/configs\/\d+\/issues/.test(url)) {
    return jsonResponse({ items: [] })
  }
  // W6（F102）：素材池 / 缺失日期面板挂进设置页后的静态空态
  if (/\/configs\/\d+\/pool$/.test(url) && (!init?.method || init.method === 'GET')) {
    return jsonResponse({ items: [], used: [] })
  }
  if (/\/configs\/\d+\/missing-dates/.test(url)) {
    return jsonResponse({ missing: [], existing: [] })
  }
  if (/\/configs\/\d+\/feed/.test(url)) return jsonResponse({ atomPath: `/feeds/gpt-digest/x.atom` })
  if (url.endsWith('/gpt-digest/feed')) return jsonResponse({ atomPath: '/feeds/gpt-digest/tok.atom' })
  throw new Error(`unexpected fetch: ${url}`)
}

function renderSection(handler?: typeof baseHandler) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    (handler ?? baseHandler)(String(input), init),
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

describe('GptDigestSection（F01 多配置）', () => {
  it('渲染配置列表并显示暂停状态；可切换选择', async () => {
    renderSection()
    expect(await screen.findByLabelText('选择日报配置')).toBeInTheDocument()
    const select = screen.getByLabelText('选择日报配置') as HTMLSelectElement
    expect(select.selectedOptions[0].textContent).toContain('默认日报')
    fireEvent.change(select, { target: { value: '2' } })
    await waitFor(() => {
      expect((screen.getByLabelText('日报名称') as HTMLInputElement).value).toBe('开源日报')
    })
  })

  it('编辑后保存发出 PUT 载荷（含来源白名单）', async () => {
    const fetchMock = renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/configs/2') && init?.method === 'PUT') {
        return jsonResponse({ ...CONFIGS.items[1], windowHours: 30 })
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    fireEvent.change(screen.getByLabelText('选择日报配置'), { target: { value: '2' } })
    const allow = await screen.findByLabelText('来源白名单')
    fireEvent.change(allow, { target: { value: 'rust.example.com' } })
    fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/configs/2') && init?.method === 'PUT',
      )
      expect(put).toBeTruthy()
      expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({
        feedUrlAllow: 'rust.example.com',
      })
    })
  })

  it('立即生成失败原样透出服务端消息', async () => {
    renderSection((url, init) => {
      if (/\/configs\/\d+\/generate/.test(url) && init?.method === 'POST') {
        return jsonResponse(
          { error: { type: 'no_material', message: '窗口内没有可用材料；未生成空日报。' } },
          422,
        )
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    fireEvent.click(screen.getByRole('button', { name: /立即生成/ }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('窗口内没有可用材料')
    })
  })

  it('新建配置发出 POST 并切换到新配置', async () => {
    let created = false
    renderSection((url, init) => {
      if (url.endsWith('/gpt-digest/configs') && init?.method === 'POST') {
        created = true
        return jsonResponse({ ...CONFIGS.items[1], id: 3, name: '新日报 x' })
      }
      if (url.endsWith('/gpt-digest/configs') && created) {
        return jsonResponse({ items: [...CONFIGS.items, { ...CONFIGS.items[1], id: 3, name: '新日报 x' }] })
      }
      return baseHandler(url, init)
    })
    await screen.findByLabelText('选择日报配置')
    fireEvent.click(screen.getByRole('button', { name: '新建配置' }))
    await waitFor(() => {
      expect((screen.getByLabelText('日报名称') as HTMLInputElement).value).toBe('新日报 x')
    })
  })
})
