/** R03 服务页五态渲染测试（OperationsSettingsSection 重写验收）。
 *
 * 五态语义（真实证据的最高档，绝不拔高、绝不硬编码绿色）：
 * - 尚未检查：未配置连接 / 后端无探测端点（AI / 邮件 / Obsidian / 备份）；
 * - 接口可达：RSSHub /healthz 200；FreshRSS 401（可达但凭据失败）；
 * - 认证成功：FreshRSS ClientLogin 200；
 * - 业务可用：BFF 本体 + 本地存储（本次请求即真实业务证据）；
 * - 错误：探测失败 / 核心存储异常。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OperationsSettingsSection } from '../components/settings/OperationsSettingsSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Handler = (url: string) => Response

const DIAGNOSTICS = {
  version: '0.1.0',
  schemaVersion: 3,
  authMode: 'session',
  uptimeS: 1,
  deps: [],
  errorCountsByType: {},
  configPresence: { freshrss: true, rsshub: true, aiKey: true, imap: false, obsidian: false },
  counts: { feeds: 0, entriesIndexed: 0, libraryItems: 0 },
}

function renderSection(handler: Handler) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) =>
      Promise.resolve(handler(String(input))),
    ),
  )
  render(
    <QueryClientProvider client={qc}>
      <OperationsSettingsSection />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('服务页五态（R03）', () => {
  it('业务可用（Lumi/本地数据）+ 认证成功（FreshRSS 200）+ 接口可达（RSSHub healthz）', async () => {
    renderSection((url) => {
      if (url === '/api/v1/operations/status') {
        return jsonResponse({
          lumi: { status: 'healthy', version: '0.1.0' },
          sqlite: { status: 'healthy', schemaVersion: 3, lastCheckedAt: '2026-10-02T00:00:00Z' },
          freshrss: { status: 'healthy', configured: true, latencyMs: 12, lastCheckedAt: '2026-10-02T00:00:00Z', error: null },
          rsshub: { status: 'healthy', configured: true, latencyMs: 30, lastCheckedAt: '2026-10-02T00:00:00Z', error: null, restartRequired: false, pendingConfigCount: 0 },
          backup: { webdavConfigured: true, lastBackup: null },
        })
      }
      if (url === '/api/v1/operations/diagnostics') return jsonResponse(DIAGNOSTICS)
      if (url === '/api/v1/rag/status') return jsonResponse({ enabled: false, chunks: 0, model: 'x', vecTable: true, lastRebuildAt: null, lastError: null, fastembedAvailable: false })
      return jsonResponse({ error: { type: 'not_found', message: url } }, 404)
    })

    const rows = await screen.findAllByRole('status')
    const text = rows.map((r) => r.textContent ?? '').join('|')
    expect(text).toContain('业务可用')
    expect(text).toContain('认证成功')
    expect(text).toContain('接口可达')
    // 版本与最后检查如实展示（最后检查在可折叠详情里，展开验证）
    expect(screen.getByText('版本 0.1.0')).toBeInTheDocument()
    for (const button of screen.getAllByRole('button', { name: '详情' })) {
      fireEvent.click(button)
    }
    expect(screen.getAllByText(/最后检查/).length).toBeGreaterThan(0)
  })

  it('未配置 → 尚未检查；FreshRSS 401 → 接口可达（可达但凭据失败）；无探测端点的服务也如实「尚未检查」', async () => {
    renderSection((url) => {
      if (url === '/api/v1/operations/status') {
        return jsonResponse({
          lumi: { status: 'healthy', version: '0.1.0' },
          sqlite: { status: 'healthy', schemaVersion: 3 },
          freshrss: { status: 'unauthenticated', configured: true, latencyMs: 8, lastCheckedAt: null, error: { type: 'authentication_error' } },
          rsshub: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null, restartRequired: false, pendingConfigCount: 0 },
          backup: { webdavConfigured: false, lastBackup: null },
        })
      }
      if (url === '/api/v1/operations/diagnostics') return jsonResponse(DIAGNOSTICS)
      if (url === '/api/v1/rag/status') return jsonResponse({ enabled: false, chunks: 0, model: 'x', vecTable: true, lastRebuildAt: null, lastError: null, fastembedAvailable: false })
      return jsonResponse({ error: { type: 'not_found', message: url } }, 404)
    })

    const rows = await screen.findAllByRole('status')
    const text = rows.map((r) => r.textContent ?? '').join('|')
    expect(text).toContain('尚未检查')
    // FreshRSS 可达但凭据失败：显示「接口可达」+ 凭据说明，不拔高为认证成功
    expect(text).toContain('接口可达')
    expect(screen.getByText('服务可达，但凭据校验失败。')).toBeInTheDocument()
    // AI / 邮件 / Obsidian / 备份没有服务端探测 → 尚未检查 + 配置布尔
    expect(screen.getByText('密钥已配置；尚无服务端健康探测。')).toBeInTheDocument()
    expect(screen.getByText('IMAP 未配置。')).toBeInTheDocument()
    expect(screen.getByText('WebDAV 未配置。')).toBeInTheDocument()
  })

  it('探测失败 → 错误态（连接失败 / 核心存储异常）', async () => {
    renderSection((url) => {
      if (url === '/api/v1/operations/status') {
        return jsonResponse({
          lumi: { status: 'degraded', version: '0.1.0' },
          sqlite: { status: 'unavailable', schemaVersion: null, lastCheckedAt: null, error: { type: 'database_error' } },
          freshrss: { status: 'unavailable', configured: true, latencyMs: null, lastCheckedAt: null, error: { type: 'connection_error' } },
          rsshub: { status: 'unavailable', configured: true, latencyMs: null, lastCheckedAt: null, error: { type: 'connection_error' }, restartRequired: false, pendingConfigCount: 0 },
          backup: { webdavConfigured: false, lastBackup: null },
        })
      }
      if (url === '/api/v1/operations/diagnostics') return jsonResponse(DIAGNOSTICS)
      if (url === '/api/v1/rag/status') return jsonResponse({ enabled: true, chunks: 5, model: 'x', vecTable: true, lastRebuildAt: null, lastError: 'boom', fastembedAvailable: false })
      return jsonResponse({ error: { type: 'not_found', message: url } }, 404)
    })

    const rows = await screen.findAllByRole('status')
    const text = rows.map((r) => r.textContent ?? '').join('|')
    expect(text).toContain('错误')
    expect(screen.getByText(/核心存储异常，服务降级。/)).toBeInTheDocument()
  })

  it('状态端点失败 → 错误 UI（不静默空白）', async () => {
    renderSection(() => jsonResponse({ error: { type: 'upstream_error', message: 'x' } }, 502))
    await waitFor(() => {
      expect(screen.getByText(/无法获取服务状态/)).toBeInTheDocument()
    })
  })

  it('成员口径与管理员边界说明可见；无硬编码颜色类', async () => {
    renderSection((url) => {
      if (url === '/api/v1/operations/status') {
        return jsonResponse({
          lumi: { status: 'healthy', version: '0.1.0' },
          sqlite: { status: 'healthy', schemaVersion: 3 },
          freshrss: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null },
          rsshub: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null, restartRequired: false, pendingConfigCount: 0 },
          backup: { webdavConfigured: false, lastBackup: null },
        })
      }
      if (url === '/api/v1/operations/diagnostics') return jsonResponse(DIAGNOSTICS)
      if (url === '/api/v1/rag/status') return jsonResponse({ enabled: false, chunks: 0, model: 'x', vecTable: true, lastRebuildAt: null, lastError: null, fastembedAvailable: false })
      return jsonResponse({ error: { type: 'not_found', message: url } }, 404)
    })

    expect(await screen.findByText(/按账户隔离/)).toBeInTheDocument()
    expect(screen.getByText(/仅管理员可见/)).toBeInTheDocument()
    // 绝不硬编码绿色：状态点只允许语义 token（danger / tertiary / accent）
    const html = document.body.innerHTML
    expect(html).not.toMatch(/bg-(green|emerald|red)-\d{3}/)
  })
})
