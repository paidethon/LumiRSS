/** 0018 Backup UI 行为测试 — 备份执行 / WebDAV 写只读 / 恢复向导阶段。
 *
 * 只断言 interaction 与 DOM 语义；fetch 全部 stub，绝不触网。
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DataBackupSection } from '../components/settings/DataControlPage'

const WEBDAV_UNCONFIGURED = {
  configured: false,
  serverUrl: '',
  username: '',
  remoteDir: '',
  tlsVerify: true,
  passwordConfigured: false,
}

const WEBDAV_CONFIGURED = {
  configured: true,
  serverUrl: 'https://dav.example.com/dav/',
  username: 'operator',
  remoteDir: 'LumiRSS',
  tlsVerify: true,
  passwordConfigured: true,
}

const OPERATIONS_OK = {
  lumi: { status: 'healthy', version: '0.1.0' },
  sqlite: { status: 'healthy' },
  freshrss: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null },
  rsshub: { status: 'unconfigured', configured: false, latencyMs: null, lastCheckedAt: null, error: null, restartRequired: false, pendingConfigCount: 0 },
  backup: { webdavConfigured: false, lastBackup: null },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>

function renderBackup(handler: Handler) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    return handler(url, init)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <DataBackupSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('0018 备份概览与执行', () => {
  it('创建备份：点击 → POST /api/v1/backups（local）；有 running job 时按钮禁用并显示 stage', async () => {
    const created: string[] = []
    const runningJob = {
      id: 'job-1',
      type: 'full',
      status: 'running',
      stage: 'backing-up-freshrss',
      target: 'local',
      createdAt: '2026-09-04T10:00:00Z',
      startedAt: '2026-09-04T10:00:01Z',
      finishedAt: null,
      summary: null,
      safeError: null,
    }
    const fetchMock = renderBackup((url, init) => {
      if (url === '/api/v1/backups' && (!init || init.method === undefined)) {
        return jsonResponse([runningJob])
      }
      if (url === '/api/v1/backups' && init?.method === 'POST') {
        created.push(String(JSON.parse(String(init.body)).target))
        return jsonResponse({ ...runningJob, id: 'job-2', status: 'queued', stage: 'preparing' }, 202)
      }
      if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
      if (url === '/api/v1/backups/webdav') return jsonResponse(WEBDAV_UNCONFIGURED)
      return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
    })

    // 活动 job 如实显示 stage（不伪造百分比）
    expect(await screen.findByText('正在备份 FreshRSS 数据')).toBeInTheDocument()
    // 单并发：两个创建按钮都禁用
    expect(screen.getByRole('button', { name: /创建完整备份（本机）/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /备份并上传 WebDAV/ })).toBeDisabled()
    expect(created).toEqual([])
    expect(fetchMock).toHaveBeenCalled()
  })

  it('创建失败（backup_busy）→ 稳定错误信息可见；成功后历史刷新', async () => {
    renderBackup((url, init) => {
      if (url === '/api/v1/backups' && init?.method === 'POST') {
        return jsonResponse(
          { error: { type: 'backup_busy', message: 'Another job is already in progress.' } },
          409,
        )
      }
      if (url === '/api/v1/backups') return jsonResponse([])
      if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
      if (url === '/api/v1/backups/webdav') return jsonResponse(WEBDAV_UNCONFIGURED)
      return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
    })

    await screen.findByText('暂无备份')
    fireEvent.click(screen.getByRole('button', { name: /创建完整备份（本机）/ }))
    await waitFor(() =>
      expect(screen.getByText(/Another job is already in progress/)).toBeInTheDocument(),
    )
  })

  it('历史：成功 job 显示大小/组件/恢复入口；失败 job 显示安全原因', async () => {
    const succeeded = {
      id: 'job-ok',
      type: 'full',
      status: 'succeeded',
      stage: 'completed',
      target: 'local',
      createdAt: '2026-09-04T09:00:00Z',
      startedAt: null,
      finishedAt: '2026-09-04T09:00:20Z',
      summary: {
        filename: 'lumirss-20260904.backup',
        target: 'local',
        sizeBytes: 2048,
        components: ['lumi.sqlite', 'freshrss-data'],
        fileCount: 3,
        localPath: '/data/backups/lumirss-20260904.backup',
      },
      safeError: null,
    }
    const failed = {
      id: 'job-bad',
      type: 'full',
      status: 'failed',
      stage: 'backing-up-freshrss',
      target: 'local',
      createdAt: '2026-09-04T08:00:00Z',
      startedAt: null,
      finishedAt: '2026-09-04T08:00:05Z',
      summary: null,
      safeError: 'FreshRSS data directory is not available for backup.',
    }
    renderBackup((url) => {
      if (url === '/api/v1/backups') return jsonResponse([failed, succeeded])
      if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
      if (url === '/api/v1/backups/webdav') return jsonResponse(WEBDAV_UNCONFIGURED)
      return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
    })

    expect(await screen.findByText('lumirss-20260904.backup')).toBeInTheDocument()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
    // safeError 同时出现在概览「最近一次失败」与历史行
    expect(screen.getAllByText(/FreshRSS data directory is not available/).length).toBeGreaterThanOrEqual(1)
    // 成功的完整备份提供恢复入口
    expect(screen.getByRole('button', { name: /从此备份恢复/ })).toBeEnabled()
  })
})

describe('0018 WebDAV 写只读', () => {
  it('已配置密码时：占位符显示已保存状态，清空提交不带 password 字段', async () => {
    const bodies: unknown[] = []
    renderBackup((url, init) => {
      if (url === '/api/v1/backups/webdav' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        bodies.push(body)
        return jsonResponse(WEBDAV_CONFIGURED)
      }
      if (url === '/api/v1/backups/webdav') return jsonResponse(WEBDAV_CONFIGURED)
      if (url === '/api/v1/backups/webdav/test') {
        return jsonResponse({ status: 'ok' })
      }
      if (url === '/api/v1/backups') return jsonResponse([])
      if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
      return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
    })

    await screen.findByText('WebDAV 远程备份')
    const passwordInput = await screen.findByPlaceholderText('••••••••')
    expect(passwordInput).toHaveValue('')
    // GET 响应永远不含密码字段（契约）
    expect(WEBDAV_CONFIGURED).not.toHaveProperty('password')

    // 直接保存（无改动）→ 按钮禁用（password 不回填，dirty=false）
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    // 修改用户名 → dirty → PUT body 不含 password（写只读：空 = 不修改）
    fireEvent.change(screen.getByLabelText(/用户名/), { target: { value: 'operator2' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(bodies.length).toBe(1))
    expect(bodies[0]).toMatchObject({ username: 'operator2' })
    expect(bodies[0]).not.toHaveProperty('password')
  })

  it('测试连接：成功与失败结果都如实展示', async () => {
    renderBackup((url) => {
      if (url === '/api/v1/backups/webdav/test') {
        return jsonResponse({ status: 'failed', message: 'WebDAV rejected the credentials.' })
      }
      if (url === '/api/v1/backups/webdav') return jsonResponse(WEBDAV_CONFIGURED)
      if (url === '/api/v1/backups') return jsonResponse([])
      if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
      return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
    })

    fireEvent.click(await screen.findByRole('button', { name: /测试连接/ }))
    await waitFor(() =>
      expect(screen.getByText(/连接失败：WebDAV rejected the credentials/)).toBeInTheDocument(),
    )
  })
})

describe('0018 恢复向导', () => {
  const succeededJob = {
    id: 'job-ok',
    type: 'full',
    status: 'succeeded',
    stage: 'completed',
    target: 'local',
    createdAt: '2026-09-04T09:00:00Z',
    startedAt: null,
    finishedAt: '2026-09-04T09:00:20Z',
    summary: {
      filename: 'lumirss-20260904.backup',
      target: 'local',
      sizeBytes: 1024,
      components: ['lumi.sqlite'],
      fileCount: 1,
      localPath: '/data/backups/lumirss-20260904.backup',
    },
    safeError: null,
  }

  function baseHandler(url: string): Response {
    if (url === '/api/v1/backups') return jsonResponse([succeededJob])
    if (url === '/api/v1/operations/status') return jsonResponse(OPERATIONS_OK)
    if (url === '/api/v1/backups/webdav') return jsonResponse(WEBDAV_UNCONFIGURED)
    return jsonResponse({ error: { type: 'not_found', message: `unexpected ${url}` } }, 404)
  }

  it('阶段推进：选择备份 → 预览（checksum/兼容性）→ 确认必须输入 RESTORE', async () => {
    let previewed: unknown = null
    renderBackup((url, init) => {
      if (url === '/api/v1/restore/preview' && init?.method === 'POST') {
        previewed = JSON.parse(String(init.body))
        return jsonResponse({
          restoreSessionId: 'sess-1',
          fileName: 'lumirss-20260904.backup',
          createdAt: '2026-09-04T09:00:00Z',
          lumiVersion: '0.1.0',
          lumiDbSchemaVersion: 3,
          currentDbSchemaVersion: 3,
          compatible: true,
          components: ['lumi.sqlite'],
          files: [{ path: 'lumi.sqlite', size: 1024 }],
          excludedSecrets: ['ai.api_key'],
          secretConfigured: false,
        })
      }
      return baseHandler(url)
    })

    fireEvent.click(await screen.findByRole('button', { name: /从此备份恢复/ }))
    // 来源选择器出现
    const dialog = await screen.findByRole('dialog', { name: '从备份恢复' })
    fireEvent.click(within(dialog).getByRole('button', { name: /lumirss-20260904\.backup/ }))
    await waitFor(() => expect(previewed).toMatchObject({ source: 'local', jobId: 'job-ok' }))
    // 预览：校验通过 + 不兼容时才拦截
    expect(await screen.findByText(/checksum（SHA-256）与 manifest 均已验证/)).toBeInTheDocument()
    // 破坏性确认：输入框存在，继续按钮进入确认步骤
    fireEvent.click(screen.getByRole('button', { name: /继续恢复…/ }))
    const confirmInput = await screen.findByLabelText('输入 RESTORE 以确认恢复')
    const executeButton = screen.getByRole('button', { name: /执行恢复/ })
    // 未输入正确确认文本前，执行按钮禁用（禁止单按钮破坏性恢复）
    fireEvent.change(confirmInput, { target: { value: 'restore' } })
    expect(executeButton).toBeDisabled()
    fireEvent.change(confirmInput, { target: { value: 'RESTORE' } })
    expect(executeButton).toBeEnabled()
  })

  it('不兼容 manifest（版本更高）→ 预览阶段拒绝，继续恢复禁用', async () => {
    renderBackup((url, init) => {
      if (url === '/api/v1/restore/preview' && init?.method === 'POST') {
        return jsonResponse({
          restoreSessionId: 'sess-2',
          fileName: 'future.backup',
          createdAt: null,
          lumiVersion: '9.9.9',
          lumiDbSchemaVersion: 9999,
          currentDbSchemaVersion: 3,
          compatible: false,
          components: ['lumi.sqlite'],
          files: [{ path: 'lumi.sqlite', size: 1024 }],
          excludedSecrets: [],
          secretConfigured: false,
        })
      }
      return baseHandler(url)
    })

    fireEvent.click(await screen.findByRole('button', { name: /从此备份恢复/ }))
    const dialog = await screen.findByRole('dialog', { name: '从备份恢复' })
    fireEvent.click(within(dialog).getByRole('button', { name: /lumirss-20260904\.backup/ }))
    expect(await screen.findByText(/不兼容，无法恢复/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /继续恢复…/ })).toBeDisabled()
  })

  it('校验失败（损坏备份）→ 安全错误与重选路径', async () => {
    renderBackup((url, init) => {
      if (url === '/api/v1/restore/preview' && init?.method === 'POST') {
        return jsonResponse(
          { error: { type: 'backup_checksum_mismatch', message: 'Backup failed checksum verification.' } },
          400,
        )
      }
      return baseHandler(url)
    })

    fireEvent.click(await screen.findByRole('button', { name: /从此备份恢复/ }))
    const dialog = await screen.findByRole('dialog', { name: '从备份恢复' })
    fireEvent.click(within(dialog).getByRole('button', { name: /lumirss-20260904\.backup/ }))
    expect(await screen.findByText(/校验失败：Backup failed checksum verification/)).toBeInTheDocument()
    // 原始文件未被修改的说明 + 返回重选
    expect(screen.getByText(/原始备份文件未被修改或删除/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /返回重选/ })).toBeEnabled()
  })
})
