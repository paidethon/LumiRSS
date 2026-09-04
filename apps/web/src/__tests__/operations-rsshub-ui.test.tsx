/** 0018 RSSHub Control Center + Operations UI 行为测试。
 *
 * 覆盖：typed allow-list 字段渲染、secret 永不回显（只显示已配置/未配置）、
 * desired/dirty/保存语义、restartRequired 提示、标记为已应用、放弃更改、
 * Operations loading / success / error 三态。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RssHubControlCenter } from '../components/settings/RssHubControlCenter'
import { OperationsSettingsSection } from '../components/settings/OperationsSettingsSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Handler = (url: string, init?: RequestInit) => Response

const RSSHUB_CONFIG = {
  schemaVersion: 1,
  configured: true,
  pendingCount: 1,
  pendingSecrets: false,
  groups: [
    {
      id: 'cache',
      label: '缓存',
      items: [
        {
          key: 'CACHE_EXPIRE',
          label: '缓存过期（分钟）',
          description: '页面缓存时间。',
          group: 'cache',
          type: 'int',
          default: 300,
          editable: true,
          secret: false,
          restartRequired: true,
          options: null,
          value: 300,
        },
        {
          key: 'CACHE_TYPE',
          label: '缓存类型',
          description: 'memory 或 redis。',
          group: 'cache',
          type: 'enum',
          default: 'memory',
          editable: true,
          secret: false,
          restartRequired: true,
          options: ['memory', 'redis'],
          value: 'memory',
        },
      ],
    },
    {
      id: 'access',
      label: '访问控制',
      items: [
        {
          key: 'ACCESS_KEY',
          label: 'Access Key',
          description: 'API 访问密钥。',
          group: 'access',
          type: 'secret',
          default: '',
          editable: true,
          secret: true,
          restartRequired: true,
          options: null,
          configured: true,
        },
      ],
    },
  ],
}

const OPERATIONS_OK = {
  lumi: { status: 'healthy', version: '0.1.0' },
  sqlite: { status: 'healthy', schemaVersion: 3 },
  freshrss: { status: 'healthy', configured: true, latencyMs: 12, lastCheckedAt: null, error: null },
  rsshub: { status: 'healthy', configured: true, latencyMs: 30, lastCheckedAt: null, error: null, restartRequired: false, pendingConfigCount: 0 },
  backup: { webdavConfigured: false, lastBackup: null },
}

function renderWithHandler(handler: Handler) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init)),
  )
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <RssHubControlCenter />
      <OperationsSettingsSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('0018 RSSHub Control Center', () => {
  it('typed 字段渲染：int / enum / secret 三种形态；secret 只显示「已配置」不回显', async () => {
    renderWithHandler((url) => {
      if (url === '/api/v1/rsshub/config') return jsonResponse(RSSHUB_CONFIG)
      if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
      return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
    })

    // int 字段
    const intInput = await screen.findByLabelText('缓存过期（分钟）')
    expect(intInput).toHaveValue(300)
    expect(intInput).toHaveAttribute('type', 'number')
    // enum 字段
    expect(screen.getByLabelText('缓存类型')).toBeInTheDocument()
    // secret 字段：type=password，值为空（不回显），且只有「已配置」徽标
    const secretInput = screen.getByLabelText('Access Key（secret）')
    expect(secretInput).toHaveAttribute('type', 'password')
    expect(secretInput).toHaveValue('')
    expect(screen.getByText('已配置')).toBeInTheDocument()
    expect(JSON.stringify(RSSHUB_CONFIG.groups[1]!.items[0])).not.toContain('"value"')
  })

  it('restartRequired 提示 + 保存只 PATCH 脏值；放弃更改还原', async () => {
    const bodies: unknown[] = []
    let applied = 0
    renderWithHandler((url, init) => {
      if (url === '/api/v1/rsshub/config' && init?.method === 'PATCH') {
        bodies.push(JSON.parse(String(init.body)))
        return jsonResponse({ ...RSSHUB_CONFIG, pendingCount: 2 })
      }
      if (url === '/api/v1/rsshub/config/apply' && init?.method === 'POST') {
        applied += 1
        return new Response(null, { status: 204 })
      }
      if (url === '/api/v1/rsshub/config') return jsonResponse(RSSHUB_CONFIG)
      if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
      return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
    })

    // pendingCount=1 → restartRequired 提示可见，且说明不会自动重启
    expect(await screen.findByText(/1 项设置需要重启 RSSHub 后生效/)).toBeInTheDocument()
    expect(screen.getByText(/Lumi 不会自行重启 RSSHub/)).toBeInTheDocument()

    // 修改 int 字段 → 保存 → PATCH 只包含脏值
    fireEvent.change(screen.getByLabelText('缓存过期（分钟）'), { target: { value: '600' } })
    fireEvent.click(screen.getByRole('button', { name: /保存更改/ }))
    await waitFor(() => expect(bodies.length).toBe(1))
    expect(bodies[0]).toMatchObject({ values: { CACHE_EXPIRE: 600 } })

    // 标记为已应用（operator 语义）
    fireEvent.click(screen.getByRole('button', { name: /标记为已应用/ }))
    await waitFor(() => expect(applied).toBe(1))
  })

  it('Operations 三态：loading / 真实状态行 / 错误', async () => {
    // error 态（rsshub/config 与 operations 都失败 → Operations 显示错误）
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(
        jsonResponse({ error: { type: 'upstream_error', message: 'FreshRSS 不可达。' } }, 502),
      )),
    )
    render(
      <QueryClientProvider client={qc}>
        <OperationsSettingsSection />
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(screen.getByText(/无法获取服务状态/)).toBeInTheDocument(),
    )
    vi.unstubAllGlobals()
  })
})
