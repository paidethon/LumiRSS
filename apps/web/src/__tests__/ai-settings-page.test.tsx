/** 0015 Gate 6 — AI 设置页测试。
 *
 * 全部 fetch stub：验证表单加载、非机密字段保存（PUT 载荷）、key
 * 状态诚实呈现（绝不出现 key 输入框）、错误路径。 */

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

const DEFAULT_SETTINGS = {
  provider: 'openai_compatible',
  baseUrl: '',
  model: '',
  summaryLanguage: 'zh-CN',
  configured: false,
}

function renderSection(queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AiSettingsSection />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AiSettingsSection', () => {
  it('加载并展示设置表单；未配置时说明密钥来自服务端环境变量', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(DEFAULT_SETTINGS))),
    )

    renderSection()

    await waitFor(() => {
      expect(screen.getByText('API 密钥未配置')).toBeInTheDocument()
    })
    expect(screen.getByText(/AI_API_KEY/)).toBeInTheDocument()
    expect(screen.getByLabelText('Base URL')).toBeInTheDocument()
    expect(screen.getByLabelText('Model')).toBeInTheDocument()
    expect(screen.getByLabelText('摘要语言')).toBeInTheDocument()
    // Provider 固定展示（0015 唯一实现），不可编辑
    expect(screen.getByLabelText('Provider')).toBeDisabled()
    // 干净表单：保存禁用
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
  })

  it('编辑字段 → 保存发出 PUT（仅非机密字段）并显示已保存', async () => {
    let putBody: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (init?.method === 'PUT') {
          putBody = JSON.parse(String(init.body))
          return Promise.resolve(
            jsonResponse({
              provider: 'openai_compatible',
              baseUrl: 'https://api.deepseek.com/v1',
              model: 'deepseek-chat',
              summaryLanguage: 'zh-CN',
              configured: false,
            }),
          )
        }
        if (url === '/api/v1/settings/ai') {
          return Promise.resolve(jsonResponse(DEFAULT_SETTINGS))
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )

    renderSection()

    await waitFor(() => {
      expect(screen.getByLabelText('Base URL')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'https://api.deepseek.com/v1' },
    })
    fireEvent.change(screen.getByLabelText('Model'), {
      target: { value: 'deepseek-chat' },
    })

    const save = screen.getByRole('button', { name: '保存' })
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() => {
      expect(screen.getByText('已保存')).toBeInTheDocument()
    })
    expect(putBody).toEqual({
      baseUrl: 'https://api.deepseek.com/v1',
      model: 'deepseek-chat',
      summaryLanguage: 'zh-CN',
    })
    expect(JSON.stringify(putBody)).not.toContain('apiKey')
  })

  it('configured=true：显示密钥已配置，且页面没有任何密钥输入框', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        Promise.resolve(jsonResponse({ ...DEFAULT_SETTINGS, configured: true })),
      ),
    )

    renderSection()

    await waitFor(() => {
      expect(screen.getByText('API 密钥已在服务端配置')).toBeInTheDocument()
    })
    expect(screen.queryByLabelText(/密钥|key|Key/)).toBeNull()
    expect(document.querySelector('input[type="password"]')).toBeNull()
  })

  it('保存失败（400 invalid_ai_settings）：显示服务端错误信息', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'PUT') {
          return Promise.resolve(
            jsonResponse(
              { error: { type: 'invalid_ai_settings', message: 'Invalid ai.base_url: bad URL' } },
              400,
            ),
          )
        }
        return Promise.resolve(jsonResponse(DEFAULT_SETTINGS))
      }),
    )

    renderSection()

    await waitFor(() => {
      expect(screen.getByLabelText('Base URL')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'not-a-url' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/保存失败/)
    })
  })
})
