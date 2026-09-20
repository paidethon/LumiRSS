/** F117 —— 版本更新确认（Web 层）。
 *
 * checkVersionOnce：新 build → onNewVersion（404/网络失败/相同版本/已
 * 忽略版本 → 静默）；「稍后」后同版本不再提示。
 * VersionUpdateToast：立即更新（无草稿 → reload；有活跃草稿 → 草稿
 * 保护确认）。fetch/stub 全局部替。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import VersionUpdateToast from '../components/VersionUpdateToast'
import {
  applyUpdate,
  checkVersionOnce,
  dismissVersion,
  startVersionCheck,
  type VersionCheckHandlers,
} from '../lib/version-check'
import { clearAllDrafts, flushDraftForTests } from '../lib/draft-store'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const handlers = (): VersionCheckHandlers & { builds: string[] } => {
  const builds: string[] = []
  return { builds, onNewVersion: (build) => builds.push(build) }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('F117 版本检查', () => {
  it('F117: 版本不同触发一次提示；同版本/404/网络失败静默', async () => {
    const h = handlers()
    // vitest 下 __APP_BUILD__ = 'dev'（vite define；NODE_ENV=test → 'dev'）
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ build: 'dev' })),
    )
    const same = await checkVersionOnce(h)
    expect(same).toBe('dev')
    expect(h.builds.length).toBe(0) // 相同版本 → 静默

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ build: 'remote-1' })),
    )
    const first = await checkVersionOnce(h)
    expect(h.builds.length).toBe(1)
    expect(first).toBe('remote-1')

    // 404 静默
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('', { status: 404 })),
    )
    const notFound = await checkVersionOnce(h)
    expect(notFound).toBeNull()
    expect(h.builds.length).toBe(1)

    // 网络失败静默
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const offline = await checkVersionOnce(h)
    expect(offline).toBeNull()
    expect(h.builds.length).toBe(1)
  })

  it('F117: 「稍后」忽略该版本；startVersionCheck 返回清理函数', async () => {
    const h = handlers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ build: 'v-next' })),
    )
    dismissVersion('v-next') // 已忽略 → 不提示
    await checkVersionOnce(h)
    expect(h.builds.length).toBe(0)

    const stop = startVersionCheck(h)
    expect(typeof stop).toBe('function')
    stop()
  })
})

describe('F117 版本更新确认 toast', () => {
  it('F117: 无草稿 → 立即更新直接刷新（reload 接缝被调用）', async () => {
    clearAllDrafts()
    const reload = vi.fn()
    render(<VersionUpdateToast newVersion="v-2" reloadFn={reload} />)
    const toast = await screen.findByTestId('version-update-toast')
    expect(toast.textContent).toContain('v-2')
    fireEvent.click(screen.getByRole('button', { name: '立即更新' }))
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
    expect(screen.queryByTestId('version-update-draft-guard')).toBeNull()
  })

  it('F117: 有活跃草稿 → 先弹草稿保护确认，确认后才刷新', async () => {
    clearAllDrafts()
    flushDraftForTests('note-editor', { title: '草稿' })
    const reload = vi.fn()
    render(<VersionUpdateToast newVersion="v-3" reloadFn={reload} />)
    fireEvent.click(await screen.findByRole('button', { name: '立即更新' }))
    // 不直接刷新 → 草稿保护确认
    const guard = await screen.findByTestId('version-update-draft-guard')
    expect(guard.textContent).toContain('未保存的草稿')
    expect(reload).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '保留草稿并更新' }))
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
  })

  it('F117: applyUpdate 语义（lib 级）：无草稿 reload / 有草稿 confirm-draft', () => {
    clearAllDrafts()
    const reloadA = vi.fn()
    expect(applyUpdate(reloadA)).toBe('reload')
    expect(reloadA).toHaveBeenCalledTimes(1)
    flushDraftForTests('annotation-editor', { body: '批注草稿' })
    const reloadB = vi.fn()
    expect(applyUpdate(reloadB)).toBe('confirm-draft')
    expect(reloadB).not.toHaveBeenCalled()
  })
})
