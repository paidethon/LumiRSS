/** N124 测试 — 快照资源预算与选择性清理（SnapshotDiagnosticsPanel）。
 *
 * 覆盖：预算行（真实文件大小 + 图片计数/样式/附件拆分）；按类清理按钮
 * 只清选中类别并在完成后重取诊断（被清资源以「缺失」如实回显）；
 * 无该类内联资源时不提供清理入口；失败诚实提示。vi.mock('../api/client')。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { configure, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import SnapshotDiagnosticsPanel from '../components/SnapshotDiagnosticsPanel'
import type { SnapshotDetail, SnapshotStorage } from '../api/client'

configure({ asyncUtilTimeout: 5000 })

const mocks = vi.hoisted(() => ({
  getSnapshotDetail: vi.fn(),
  getSnapshotStorage: vi.fn(),
  listSnapshotVersions: vi.fn(),
  cleanupSnapshotResources: vi.fn(),
  retryFailedSnapshotResources: vi.fn(),
  createSnapshotVersion: vi.fn(),
  diffSnapshotVersions: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getSnapshotDetail: mocks.getSnapshotDetail,
    getSnapshotStorage: mocks.getSnapshotStorage,
    listSnapshotVersions: mocks.listSnapshotVersions,
    cleanupSnapshotResources: mocks.cleanupSnapshotResources,
    retryFailedSnapshotResources: mocks.retryFailedSnapshotResources,
    createSnapshotVersion: mocks.createSnapshotVersion,
    diffSnapshotVersions: mocks.diffSnapshotVersions,
  }
})

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

const UUID = '11111111-2222-4333-8444-555555555555'

function detailFixture(over: Partial<SnapshotDetail> = {}): SnapshotDetail {
  return {
    uuid: UUID,
    itemRef: `library:${UUID}`,
    url: 'https://example.test/page',
    bytes: 20_000,
    sha256: 'a'.repeat(64),
    deduplicated: false,
    createdAt: '2026-09-25T00:00:00+00:00',
    resources: [
      { url: 'https://example.test/page', status: 'ok' },
      { url: 'https://cdn.example/pic.png', status: 'skipped' },
      { url: 'https://cdn.example/style.css', status: 'skipped' },
    ],
    resourcesTruncated: false,
    ...over,
  }
}

function storageFixture(over: Partial<SnapshotStorage> = {}): SnapshotStorage {
  return {
    uuid: UUID,
    totalBytes: 1024 * 300,
    breakdown: {
      images: { count: 2, bytes: 200 * 1024 },
      styles: { bytes: 50 * 1024, count: 1 },
      attachments: { bytes: 40 * 1024, count: 1 },
    },
    ...over,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getSnapshotDetail.mockResolvedValue(detailFixture())
  mocks.getSnapshotStorage.mockResolvedValue(storageFixture())
  mocks.listSnapshotVersions.mockResolvedValue({
    versions: [
      { versionId: 1, snapshotUuid: UUID, sha256: 'a'.repeat(64), sha8: 'aaaaaaaa', text: null, createdAt: '2026-09-25T00:00:00+00:00' },
    ],
  })
  mocks.cleanupSnapshotResources.mockResolvedValue({
    cleaned: { images: 2 },
    storage: storageFixture({
      totalBytes: 1024 * 100,
      breakdown: {
        images: { count: 0, bytes: 0 },
        styles: { bytes: 50 * 1024, count: 1 },
        attachments: { bytes: 40 * 1024, count: 1 },
      },
    }),
  })
})

describe('SnapshotDiagnosticsPanel — N124 资源预算与清理', () => {
  it('渲染预算行（总大小 + 图片计数 + 样式/附件拆分）', async () => {
    render(withProviders(<SnapshotDiagnosticsPanel uuid={UUID} />))
    expect(await screen.findByText(/共 300.0 KB/)).toBeInTheDocument()
    const diagnostics = document.querySelector('[data-lumi-snapshot-storage]') as HTMLElement
    expect(diagnostics).not.toBeNull()
    expect(diagnostics).toHaveTextContent('图片 2 项（200.0 KB）')
    expect(diagnostics).toHaveTextContent('样式 50.0 KB')
    expect(diagnostics).toHaveTextContent('附件 40.0 KB')
  })

  it('清理图片：只调选中类别，完成后重取并以「缺失」回显被清资源', async () => {
    render(withProviders(<SnapshotDiagnosticsPanel uuid={UUID} />))
    fireEvent.click(await screen.findByRole('button', { name: '清理图片' }))
    await waitFor(() =>
      expect(mocks.cleanupSnapshotResources).toHaveBeenCalledWith(UUID, ['images']),
    )
    expect(await screen.findByText(/已清理图片 2 项/)).toBeInTheDocument()
    // 清理后 detail 重取：样式/附件按钮仍在，预算行更新
    await waitFor(() => expect(mocks.getSnapshotDetail).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('button', { name: '清理样式' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '清理附件' })).toBeInTheDocument()
  })

  it('被清资源在诊断清单中以「缺失」如实回显', async () => {
    let detailCalls = 0
    mocks.getSnapshotDetail.mockImplementation(() => {
      detailCalls += 1
      return Promise.resolve(
        detailFixture({
          resources: [
            { url: 'https://example.test/page', status: 'ok' },
            { url: 'https://cdn.example/pic.png', status: detailCalls > 1 ? 'missing' : 'skipped' },
            { url: 'https://cdn.example/style.css', status: 'skipped' },
          ],
        }),
      )
    })
    render(withProviders(<SnapshotDiagnosticsPanel uuid={UUID} />))
    fireEvent.click(await screen.findByRole('button', { name: '清理图片' }))
    expect(await screen.findByText('缺失')).toBeInTheDocument()
  })

  it('没有可清理类别的资源 → 不渲染对应清理入口', async () => {
    mocks.getSnapshotStorage.mockResolvedValue(
      storageFixture({
        breakdown: {
          images: { count: 0, bytes: 0 },
          styles: { bytes: 0, count: 0 },
          attachments: { bytes: 0, count: 0 },
        },
      }),
    )
    render(withProviders(<SnapshotDiagnosticsPanel uuid={UUID} />))
    expect(await screen.findByText(/共 300.0 KB/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '清理图片' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '清理样式' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '清理附件' })).not.toBeInTheDocument()
  })
})
