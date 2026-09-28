/** FIX-059 基线验证 — 后台轮询在离开视图（卸载）后必须停止请求。
 *
 * 审计项「管理页后台轮询在切换分区后仍持续请求」对照当前实现为
 * BASELINE_OK：
 * - 管理台（components/admin/）没有任何轮询（无 refetchInterval /
 *   setInterval）；
 * - 全部 refetchInterval 站点（useBackups / useBackupJob /
 *   useAgentMessages / RagW5Panels）都随组件卸载由 TanStack 自动停止，
 *   且前三者为条件轮询（仅活动任务/进行中的会话才轮询）。
 *
 * 本文件用假计时器对该语义做真实回归防线：条件轮询 hook 在有活动
 * 任务时按间隔请求；组件卸载后时间前进 10s 请求计数不变。若未来
 * 引入不随卸载停止的轮询（手动 interval、外层常挂组件等），本用例
 * 失败。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useBackups } from '../api/queries'

function Probe(): null {
  useBackups()
  return null
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('FIX-059 基线：轮询随卸载停止', () => {
  it('useBackups 有活动任务时按间隔轮询；卸载后时间前进 10s 无新增请求', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify([
          {
            id: 'b1',
            type: 'local',
            status: 'queued',
            startedAt: null,
            finishedAt: null,
            error: null,
            include: null,
          },
        ]),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const view = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <Probe />
      </QueryClientProvider>,
    )

    // 挂载：首拉一次。
    await vi.advanceTimersByTimeAsync(0)
    const afterMount = fetchMock.mock.calls.length
    expect(afterMount).toBeGreaterThan(0)

    // 有 queued 任务 → 2s 条件轮询持续发请求。
    await vi.advanceTimersByTimeAsync(4500)
    const whilePolling = fetchMock.mock.calls.length
    expect(whilePolling).toBeGreaterThan(afterMount)

    // 离开视图（卸载）→ 时间前进 10s，请求计数不变。
    view.unmount()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock.mock.calls.length).toBe(whilePolling)
  })
})
