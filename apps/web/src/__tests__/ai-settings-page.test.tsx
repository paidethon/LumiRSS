/** AI 设置页测试（浏览器管理的多 Profile + 用途分配）。
 *
 * 全部 fetch stub：验证表单加载、非机密字段保存（PUT 载荷）、Profile
 * CRUD 载荷、Key write-only（输入框存在但任何 GET 响应不含 Key 值）、
 * 用途分配载荷与错误路径。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AiSettingsSection } from '../components/settings/AiSettingsPage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const DEFAULT_PURPOSE_STATUS = {
  profileId: 'default',
  source: 'default',
  profileLabel: null,
  baseUrl: '',
  model: '',
  keyConfigured: false,
  keySource: 'missing',
  configured: false,
}

const DEFAULT_SETTINGS = {
  provider: 'openai_compatible',
  baseUrl: '',
  model: '',
  summaryLanguage: 'zh-CN',
  translationLanguage: 'zh-CN',
  configured: false,
  envKeyConfigured: false,
  defaultKeyConfigured: false,
  purposes: { summary: 'default', translation: 'default', chat: 'default' },
  purposeStatus: {
    summary: DEFAULT_PURPOSE_STATUS,
    translation: DEFAULT_PURPOSE_STATUS,
    chat: DEFAULT_PURPOSE_STATUS,
  },
}

const PROFILE = {
  id: 'p1',
  label: 'GLM 摘要',
  provider: 'openai_compatible',
  baseUrl: 'https://api.example.com/v1',
  model: 'glm-x',
  enabled: true,
  keyConfigured: true,
  createdAt: '2026-09-05T00:00:00Z',
  updatedAt: '2026-09-05T00:00:00Z',
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>

function renderSection(
  handler: Handler,
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
) {
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
    handler(String(input), init),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={queryClient}>
      <AiSettingsSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AiSettingsSection — 加载与结构', () => {
  it('渲染用途分配 / Profile / 默认 Key / 默认配置四个区块', async () => {
    renderSection((url) => {
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([])
      throw new Error(`unexpected fetch: ${url}`)
    })

    expect(await screen.findByText('用途分配')).toBeInTheDocument()
    expect(screen.getByLabelText('摘要使用的配置')).toBeInTheDocument()
    expect(screen.getByLabelText('翻译使用的配置')).toBeInTheDocument()
    expect(screen.getByLabelText('AI 对话使用的配置')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新建 Profile/ })).toBeInTheDocument()
    expect(screen.getByText('默认 API Key')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '默认配置' })).toBeInTheDocument()
    expect(screen.getByLabelText('默认 Base URL')).toBeInTheDocument()
    expect(screen.getByLabelText('默认 Model')).toBeInTheDocument()
  })

  it('Profile 列表展示名称 / Key 状态 / Base URL / model（绝不回显 Key 值）', async () => {
    renderSection((url) => {
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([PROFILE])
      throw new Error(`unexpected fetch: ${url}`)
    })

    expect(await screen.findByText('GLM 摘要', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getAllByText('Key 已配置').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/https:\/\/api.example.com\/v1 · glm-x/)).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '启用 Profile GLM 摘要' })).toBeEnabled()
    // 用途分配下拉里出现该 Profile
    expect(
      Array.from(screen.getByLabelText('摘要使用的配置').querySelectorAll('option')).some(
        (o) => o.textContent === 'GLM 摘要',
      ),
    ).toBe(true)
  })
})

describe('AiSettingsSection — 默认配置保存（仅非机密字段）', () => {
  it('编辑 → 保存发出 PUT；载荷不含任何 key 字段', async () => {
    const putBodies: unknown[] = []
    renderSection((url, init) => {
      if (url === '/api/v1/settings/ai' && init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)))
        return jsonResponse({ ...DEFAULT_SETTINGS, baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-chat' })
      }
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([])
      throw new Error(`unexpected fetch: ${url}`)
    })

    await screen.findByRole('heading', { name: '默认配置' })
    fireEvent.change(screen.getByLabelText('默认 Base URL'), {
      target: { value: 'https://api.deepseek.com/v1' },
    })
    fireEvent.change(screen.getByLabelText('默认 Model'), { target: { value: 'deepseek-chat' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(putBodies.length).toBe(1))
    expect(putBodies[0]).toEqual({
      baseUrl: 'https://api.deepseek.com/v1',
      model: 'deepseek-chat',
      summaryLanguage: 'zh-CN',
      translationLanguage: 'zh-CN',
    })
    expect(putBodies[0]).not.toHaveProperty('apiKey')
    expect(putBodies[0]).not.toHaveProperty('key')
  })

  it('保存失败（400 invalid_ai_settings）：显示服务端错误信息', async () => {
    renderSection((url, init) => {
      if (url === '/api/v1/settings/ai' && init?.method === 'PUT') {
        return jsonResponse(
          { error: { type: 'invalid_ai_settings', message: 'Invalid ai.base_url: must be an absolute http(s) URL' } },
          400,
        )
      }
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([])
      throw new Error(`unexpected fetch: ${url}`)
    })

    await screen.findByRole('heading', { name: '默认配置' })
    fireEvent.change(screen.getByLabelText('默认 Base URL'), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(
      await screen.findByText(/Invalid ai.base_url/),
    ).toBeInTheDocument()
  })
})

describe('AiSettingsSection — Profile 管理', () => {
  it('新建 Profile：POST 载荷只含元数据，成功后表单关闭', async () => {
    const postBodies: unknown[] = []
    renderSection((url, init) => {
      if (url === '/api/v1/settings/ai/profiles' && init?.method === 'POST') {
        postBodies.push(JSON.parse(String(init.body)))
        return jsonResponse({ ...PROFILE, id: 'p2', label: 'DeepSeek 翻译', keyConfigured: false }, 201)
      }
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([])
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      throw new Error(`unexpected fetch: ${url}`)
    })

    fireEvent.click(await screen.findByRole('button', { name: /新建 Profile/ }))
    fireEvent.change(screen.getByLabelText('新 Profile 名称'), { target: { value: 'DeepSeek 翻译' } })
    fireEvent.change(screen.getByLabelText('新 Profile Base URL'), {
      target: { value: 'https://api.deepseek.com/v1' },
    })
    fireEvent.change(screen.getByLabelText('新 Profile Model'), { target: { value: 'deepseek-chat' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))

    await waitFor(() => expect(postBodies.length).toBe(1))
    expect(postBodies[0]).toEqual({
      label: 'DeepSeek 翻译',
      baseUrl: 'https://api.deepseek.com/v1',
      model: 'deepseek-chat',
    })
    expect(postBodies[0]).not.toHaveProperty('apiKey')
  })

  it('设置 Key：PUT secret write-only；保存后输入框清空且 GET 不可见', async () => {
    const secretBodies: unknown[] = []
    renderSection((url, init) => {
      if (url === '/api/v1/settings/ai/profiles/p1/secret' && init?.method === 'PUT') {
        secretBodies.push(JSON.parse(String(init.body)))
        return new Response(null, { status: 204 })
      }
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([PROFILE])
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      throw new Error(`unexpected fetch: ${url}`)
    })

    fireEvent.click(await screen.findByRole('button', { name: '更换 Key' }))
    const keyInput = screen.getByLabelText('Profile GLM 摘要 的 API Key')
    fireEvent.change(keyInput, { target: { value: 'sk-test-123456' } })
    fireEvent.click(screen.getByRole('button', { name: /保存 Key/ }))

    await waitFor(() => expect(secretBodies.length).toBe(1))
    expect(secretBodies[0]).toEqual({ value: 'sk-test-123456' })
    // 保存成功后输入框关闭（key 不留在 DOM）
    await waitFor(() =>
      expect(screen.queryByLabelText('Profile GLM 摘要 的 API Key')).toBeNull(),
    )
  })

  it('用途分配：选择 Profile → PUT purposes 载荷正确', async () => {
    const putBodies: unknown[] = []
    renderSection((url, init) => {
      if (url === '/api/v1/settings/ai/purposes' && init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)))
        return jsonResponse({ ...DEFAULT_SETTINGS.purposes, translation: 'p1' })
      }
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([PROFILE])
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      throw new Error(`unexpected fetch: ${url}`)
    })

    const select = await screen.findByLabelText('翻译使用的配置')
    fireEvent.change(select, { target: { value: 'p1' } })
    await waitFor(() => expect(putBodies.length).toBe(1))
    expect(putBodies[0]).toEqual({ translation: 'p1' })
  })

  it('删除 Profile：两步确认后发 DELETE', async () => {
    const deleteCalls: string[] = []
    renderSection((url, init) => {
      if (url === '/api/v1/settings/ai/profiles/p1' && init?.method === 'DELETE') {
        deleteCalls.push(url)
        return new Response(null, { status: 204 })
      }
      if (url === '/api/v1/settings/ai/profiles') return jsonResponse([PROFILE])
      if (url === '/api/v1/settings/ai') return jsonResponse(DEFAULT_SETTINGS)
      throw new Error(`unexpected fetch: ${url}`)
    })

    fireEvent.click(await screen.findByRole('button', { name: '删除 Profile GLM 摘要' }))
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => expect(deleteCalls.length).toBe(1))
  })
})
