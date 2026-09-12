/** P0-07/P0-12 — 设置 → AI → 语义检索（RAG）控制面测试。
 *
 * RagSettingsSection 是 enableRag/rebuildRag/getRagStatus 的首批真实
 * UI 消费者（此前只有 Agent 页只读 chip）：
 * - 状态渲染：enabled / chunks / model / lastRebuildAt；
 * - 启用：POST /rag/enable；fastembed 未安装 → 按钮禁用 + 说明；
 * - 重建：POST /rag/rebuild，完成报告 chunks/elapsedMs（role=status）；
 * - lastError：danger 小字诚实展示；重建冲突（RagRebuildBusy）message 原样透出。
 *
 * 统一 vi.mock('../api/client')（保留 ApiError 等真实导出）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { RagStatus } from '../api/client'
import { ApiError } from '../api/client'
import { RagSettingsSection } from '../components/settings/RagSettingsSection'

const mocks = vi.hoisted(() => ({
  getRagStatus: vi.fn(),
  enableRag: vi.fn(),
  rebuildRag: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getRagStatus: mocks.getRagStatus,
    enableRag: mocks.enableRag,
    rebuildRag: mocks.rebuildRag,
  }
})

function statusFixture(over: Partial<RagStatus> = {}): RagStatus {
  return {
    enabled: false,
    chunks: 0,
    model: 'bge-small-zh-v1.5',
    vecTable: true,
    lastRebuildAt: null,
    lastError: null,
    fastembedAvailable: true,
    ...over,
  }
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getRagStatus.mockResolvedValue(statusFixture())
})

describe('RagSettingsSection', () => {
  it('状态渲染：未启用 + 已索引块 + 模型 + 上次重建「从未」；启用/重建按钮在', async () => {
    render(withProviders(<RagSettingsSection />))
    expect(await screen.findByText('未启用')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText('bge-small-zh-v1.5')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '启用语义检索' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重建索引/ })).toBeInTheDocument()
  })

  it('启用：点击 → POST enable；状态查询被失效刷新', async () => {
    mocks.enableRag.mockResolvedValue({ enabled: true })
    mocks.getRagStatus
      .mockResolvedValueOnce(statusFixture())
      .mockResolvedValue(statusFixture({ enabled: true, chunks: 12 }))
    render(withProviders(<RagSettingsSection />))
    fireEvent.click(await screen.findByRole('button', { name: '启用语义检索' }))
    await waitFor(() => expect(mocks.enableRag).toHaveBeenCalledTimes(1))
    // 失效后重取 → 徽标翻「已启用」
    expect(await screen.findByText('已启用')).toBeInTheDocument()
    expect(await screen.findByText('12')).toBeInTheDocument()
  })

  it('fastembed 未安装：启用按钮禁用 + 诚实说明', async () => {
    mocks.getRagStatus.mockResolvedValue(statusFixture({ fastembedAvailable: false }))
    render(withProviders(<RagSettingsSection />))
    expect(await screen.findByRole('button', { name: '启用语义检索' })).toBeDisabled()
    expect(screen.getByText(/当前服务端未安装 fastembed/)).toBeInTheDocument()
  })

  it('重建：busy 后报告 chunks/elapsedMs（role=status）', async () => {
    let resolveRebuild: (v: { chunks: number; elapsedMs: number }) => void = () => {}
    mocks.rebuildRag.mockReturnValue(new Promise((resolve) => { resolveRebuild = resolve }))
    render(withProviders(<RagSettingsSection />))
    fireEvent.click(await screen.findByRole('button', { name: /重建索引/ }))
    // busy 态：按钮文案切换为重建中
    expect(await screen.findByRole('button', { name: /重建中/ })).toBeDisabled()
    resolveRebuild({ chunks: 34, elapsedMs: 1500 })
    const report = await screen.findByText(/上次重建：34 块 · 1\.5s/)
    expect(report).toHaveAttribute('role', 'status')
    expect(mocks.rebuildRag).toHaveBeenCalledTimes(1)
  })

  it('重建冲突（RagRebuildBusy）与 lastError 原样透出', async () => {
    mocks.rebuildRag.mockRejectedValue(new ApiError(409, 'rag_rebuild_busy', '重建已在进行中。'))
    mocks.getRagStatus.mockResolvedValue(statusFixture({ lastError: '上次模型加载失败' }))
    render(withProviders(<RagSettingsSection />))
    fireEvent.click(await screen.findByRole('button', { name: /重建索引/ }))
    expect(await screen.findByText(/重建失败：重建已在进行中。/)).toBeInTheDocument()
    expect(screen.getByText(/上次错误：上次模型加载失败/)).toBeInTheDocument()
  })
})
