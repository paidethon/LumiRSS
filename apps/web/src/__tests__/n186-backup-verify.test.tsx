/** N186 —— 备份完整性自检独立（Web 层）。
 *
 * 恢复向导「仅校验」按钮 → 独立自检报告（四项发现 + 具体问题），
 * 绝不进入恢复流程（无 restore/preview 请求）。fetch 全部 stub。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RestoreWizard } from '../components/settings/backup/RestoreWizard'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const JOBS = [
  {
    id: 'job-ok',
    type: 'full',
    status: 'succeeded',
    stage: 'completed',
    target: 'local',
    createdAt: '2026-09-24T10:00:00+00:00',
    startedAt: '2026-09-24T10:00:01+00:00',
    finishedAt: '2026-09-24T10:00:05+00:00',
    summary: { filename: 'lumirss-20260924.backup', sizeBytes: 1024, components: ['lumi.sqlite'], fileCount: 1 },
    safeError: null,
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

function setup(report: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/backups') && (init?.method ?? 'GET') === 'GET') {
      return jsonResponse(JOBS)
    }
    if (url.endsWith('/backups/remote')) {
      return jsonResponse({ backups: [] })
    }
    if (url.endsWith('/backups/verify') && init?.method === 'POST') {
      return jsonResponse(report)
    }
    return jsonResponse({}, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <RestoreWizard open={true} onClose={() => {}} />
    </QueryClientProvider>,
  )
  return fetchMock
}

describe('N186 仅校验（独立完整性自检）', () => {
  it('健康备份：四项发现全部通过，且不触发 restore/preview', async () => {
    const fetchMock = setup({
      ok: true,
      findings: { checksumOk: true, manifestCountsMatch: true, readable: true, versionCompatible: true },
      issues: { corruptFile: [], missingAttachment: [], versionIncompatible: null },
      manifest: {
        createdAt: '2026-09-24T10:00:00+00:00',
        lumiVersion: '0.2.0',
        lumiDbSchemaVersion: 113,
        currentDbSchemaVersion: 113,
        components: ['lumi.sqlite'],
      },
    })
    await screen.findByText('本机备份')
    const verifyButton = await screen.findAllByRole('button', { name: /仅校验/ })
    fireEvent.click(verifyButton[0])
    await waitFor(() => {
      expect(document.querySelector('[data-verify-report]')?.textContent).toContain('完整性自检通过')
    })
    expect(document.querySelector('[data-verify-finding="checksumOk"]')?.textContent).toContain('通过')
    expect(document.querySelector('[data-verify-finding="readable"]')?.textContent).toContain('通过')
    // 关键负向断言：仅校验绝不走 preview/execute 恢复路径
    const restoreCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/restore'))
    expect(restoreCalls).toEqual([])
  })

  it('问题备份：损坏/缺失/版本不兼容具体列出', async () => {
    setup({
      ok: false,
      findings: { checksumOk: false, manifestCountsMatch: false, readable: true, versionCompatible: false },
      issues: {
        corruptFile: ['lumi.sqlite'],
        missingAttachment: ['library-assets/shot.png'],
        versionIncompatible: { field: 'lumiDbSchemaVersion', backup: 99999, current: 113 },
      },
      manifest: null,
    })
    await screen.findByText('本机备份')
    const verifyButtons = await screen.findAllByRole('button', { name: /仅校验/ })
    fireEvent.click(verifyButtons[0])
    await waitFor(() => {
      expect(document.querySelector('[data-verify-report]')?.textContent).toContain('完整性自检发现问题')
    })
    const issues = document.querySelector('[data-verify-issues]')?.textContent ?? ''
    expect(issues).toContain('lumi.sqlite')
    expect(issues).toContain('library-assets/shot.png')
    expect(issues).toContain('lumiDbSchemaVersion')
    expect(document.querySelector('[data-verify-finding="checksumOk"]')?.textContent).toContain('未通过')
    expect(document.querySelector('[data-verify-finding="versionCompatible"]')?.textContent).toContain('未通过')
  })
})
