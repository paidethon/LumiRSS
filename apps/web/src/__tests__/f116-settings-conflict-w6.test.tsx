/** F116 —— 设置冲突解决（Web 层）。
 *
 * settings-sync 的 409 路径调用 reportSettingsConflict 后：
 * - 对话框按字段列出 本地候选 vs 服务端当前（默认服务端）；
 * - 勾选「用本地」提交 → PATCH 只带所选字段 + baseRevision → 解决后
 *   对话框卸载；
 * - 再次 409 → 服务端快照刷新、对话框保持可再选；
 * - 取消 = 全部采用服务端（快照清除）。
 * vi.mock('../api/client')，绝不触网。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SettingsConflictDialog from '../components/SettingsConflictDialog'
import { discardSettingsConflict, reportSettingsConflict } from '../store/settings-conflict'

const mocks = vi.hoisted(() => ({
  patchServerSettings: vi.fn(),
  getServerSettings: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    patchServerSettings: mocks.patchServerSettings,
    getServerSettings: mocks.getServerSettings,
  }
})

function renderDialog(): void {
  const qc = { render: true } as never
  void qc
  render(<SettingsConflictDialog />)
}

beforeEach(() => {
  vi.clearAllMocks()
  discardSettingsConflict()
})

describe('F116 设置冲突解决', () => {
  it('F116: 逐字段展示本地 vs 服务端；仅勾选字段进 PATCH（含 baseRevision）', async () => {
    reportSettingsConflict(
      { themeMode: 'dark', accentColor: 'green', revision: 7 },
      7,
      { themeMode: 'light', accentColor: 'blue' },
    )
    mocks.patchServerSettings.mockResolvedValue({ revision: 8 })
    renderDialog()

    const dialog = await screen.findByTestId('settings-conflict-dialog')
    expect(dialog).toBeTruthy()
    expect(document.querySelector('[data-conflict-local="themeMode"]')?.textContent).toContain('light')
    expect(document.querySelector('[data-conflict-server="themeMode"]')?.textContent).toContain('dark')
    expect(document.querySelector('[data-conflict-local="accentColor"]')?.textContent).toContain('blue')

    // 只勾选 themeMode 用本地
    fireEvent.click(screen.getByLabelText('采用本地值：主题模式'))
    fireEvent.click(screen.getByRole('button', { name: '提交所选' }))

    await waitFor(() => expect(mocks.patchServerSettings).toHaveBeenCalledTimes(1))
    const body = mocks.patchServerSettings.mock.calls[0][0] as Record<string, unknown>
    expect(body.themeMode).toBe('light')
    expect(body.accentColor).toBe('green') // 未勾选 → 服务端当前值
    expect(body.baseRevision).toBe(7)
    // 解决后对话框卸载
    await waitFor(() => expect(screen.queryByTestId('settings-conflict-dialog')).toBeNull())
  })

  it('F116: 再次 409 → 快照刷新、对话框保持再选', async () => {
    reportSettingsConflict({ themeMode: 'dark', revision: 7 }, 7, { themeMode: 'light' })
    // 第一次提交 → 409；刷新快照返回新 revision
    mocks.patchServerSettings.mockRejectedValueOnce(
      Object.assign(new Error('conflict'), { status: 409, type: 'app_settings_conflict' }),
    )
    mocks.getServerSettings.mockResolvedValue({ themeMode: 'solarized', revision: 9 })
    mocks.patchServerSettings.mockResolvedValueOnce({ revision: 10 })
    renderDialog()

    await screen.findByTestId('settings-conflict-dialog')
    fireEvent.click(screen.getByLabelText('采用本地值：主题模式'))
    fireEvent.click(screen.getByRole('button', { name: '提交所选' }))

    // 再次冲突：刷新服务端快照（getServerSettings 被调用）
    await waitFor(() => expect(mocks.getServerSettings).toHaveBeenCalledTimes(1))
    // 对话框保持；服务端列显示新快照值
    await waitFor(() => {
      expect(document.querySelector('[data-conflict-server="themeMode"]')?.textContent).toContain('solarized')
    })
    expect(screen.getByTestId('settings-conflict-dialog')).toBeTruthy()
  })

  it('F116: 取消 = 采用服务端，快照清除（对话框卸载）', async () => {
    reportSettingsConflict({ themeMode: 'dark', revision: 3 }, 3, { themeMode: 'light' })
    renderDialog()
    await screen.findByTestId('settings-conflict-dialog')
    fireEvent.click(screen.getByRole('button', { name: /取消（采用服务端）/ }))
    await waitFor(() => expect(screen.queryByTestId('settings-conflict-dialog')).toBeNull())
    expect(mocks.patchServerSettings).not.toHaveBeenCalled()
  })
})
