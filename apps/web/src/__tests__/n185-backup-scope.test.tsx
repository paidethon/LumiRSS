/** N185 —— 备份内容选择预览（Web 层）。
 *
 * 范围复选框 → 「预览备份内容」显示逐组件计数 + 永远排除清单；
 * 缩小范围后创建备份请求携带 include；默认全包含不带 include。
 * fetch 全部 stub。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BackupOverview } from '../components/settings/backup/BackupOverview'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.endsWith('/operations/status')) {
      return jsonResponse({ sqlite: { status: 'healthy' }, freshrss: { status: 'healthy', configured: true } })
    }
    if (url.endsWith('/backups') && method === 'GET') {
      return jsonResponse([])
    }
    if (url.endsWith('/backups/capabilities')) {
      return jsonResponse({
        fullBackupReady: true,
        includes: ['lumi.sqlite'],
        lumiDatabaseAvailable: true,
        freshrssData: { available: true, reasonCode: null, reason: null, fileCount: 1, sqliteFileCount: 1, dbType: 'sqlite' },
      })
    }
    if (url.endsWith('/backups/preview-scope') && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}')) as {
        include?: { workspaces?: boolean; notes?: boolean; annotations?: boolean; sourceConfig?: boolean }
      }
      return jsonResponse({
        scope: {
          workspaces: body.include?.workspaces ?? true,
          notes: body.include?.notes ?? true,
          annotations: body.include?.annotations ?? true,
          sourceConfig: body.include?.sourceConfig ?? true,
        },
        components: [
          { component: 'workspaces', included: body.include?.workspaces ?? true, count: 3 },
          { component: 'notes', included: body.include?.notes ?? true, count: 12 },
          { component: 'annotations', included: body.include?.annotations ?? true, count: 0 },
          { component: 'sourceConfig', included: body.include?.sourceConfig ?? true, count: 5 },
        ],
        alwaysExcluded: [
          '凭据与密钥（API Key / WebDAV / RSSHub / IMAP 密码；恢复后需重新配置）',
          'FreshRSS 内容（订阅与文章状态由 FreshRSS 持有，不随用户数据范围裁剪）',
        ],
      })
    }
    if (url.endsWith('/backups') && method === 'POST') {
      return jsonResponse({
        id: 'job-1',
        type: 'full',
        status: 'queued',
        stage: 'preparing',
        target: 'local',
        createdAt: '2026-09-24T10:00:00+00:00',
        startedAt: null,
        finishedAt: null,
        summary: null,
        safeError: null,
      })
    }
    return jsonResponse({}, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <BackupOverview />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N185 备份内容选择预览', () => {
  it('预览显示逐组件计数与永远排除清单（凭据 / FreshRSS 内容）', async () => {
    setup()
    await screen.findByText('备份概览')
    fireEvent.click(screen.getByRole('button', { name: '预览备份内容' }))
    await waitFor(() => {
      expect(document.querySelector('[data-scope-preview-result]')).not.toBeNull()
    })
    const result = document.querySelector('[data-scope-preview-result]')?.textContent ?? ''
    expect(result).toContain('工作区 3 行')
    expect(result).toContain('人工笔记 12 行')
    expect(result).toContain('凭据与密钥')
    expect(result).toContain('FreshRSS 内容')
  })

  it('取消某组件 → 预览请求携带 include；创建备份请求也携带 include', async () => {
    const fetchMock = setup()
    await screen.findByText('备份概览')
    fireEvent.click(screen.getByRole('checkbox', { name: '人工笔记' }))
    fireEvent.click(screen.getByRole('button', { name: '预览备份内容' }))
    await waitFor(() => {
      const preview = fetchMock.mock.calls.find(
        ([url]) => String(url).endsWith('/backups/preview-scope'),
      )
      expect(preview).toBeTruthy()
      expect(JSON.parse(String(preview?.[1]?.body)).include).toEqual({
        workspaces: true,
        notes: false,
        annotations: true,
        sourceConfig: true,
      })
    })
    fireEvent.click(screen.getByRole('button', { name: '创建完整备份（本机）' }))
    await waitFor(() => {
      const create = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/backups') && init?.method === 'POST',
      )
      expect(create).toBeTruthy()
      const body = JSON.parse(String(create?.[1]?.body))
      expect(body.target).toBe('local')
      expect(body.include).toEqual({
        workspaces: true,
        notes: false,
        annotations: true,
        sourceConfig: true,
      })
    })
  })

  it('默认全包含 → 创建请求不带 include（行为与历史一致）', async () => {
    const fetchMock = setup()
    await screen.findByText('备份概览')
    fireEvent.click(screen.getByRole('button', { name: '创建完整备份（本机）' }))
    await waitFor(() => {
      const create = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith('/backups') && init?.method === 'POST',
      )
      expect(create).toBeTruthy()
      expect(JSON.parse(String(create?.[1]?.body))).toEqual({ target: 'local' })
    })
  })
})
