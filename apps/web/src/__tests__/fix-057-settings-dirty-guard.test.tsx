/** FIX-057 — 设置中心的统一脏状态守护。
 *
 * 此前：多个分区（邮件 SMTP/IMAP、存储保留、RSSHub 凭据、翻译、
 * GPT 摘要、AI 档案……）各有独立的「本地表单 + 保存按钮」，脏状态
 * 判定口径不一；从分区离开（切分类 / 关闭设置 / 移动端返回）静默
 * 丢弃未保存内容。
 *
 * 契约：
 * - 表单分区经 useSettingsDirtySection(id, dirty) 登记脏状态；
 * - SettingsModal（桌面）与 MobileSettingsScreen（移动端）在分类
 *   切换与壳关闭前统一弹「未保存的更改」确认：继续编辑（留在原地）
 *   / 放弃并离开（执行原导航）；
 * - 无脏分区时一切导航零打扰（行为与旧版完全一致）。
 */

import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SettingsModal from '../components/settings/SettingsModal'
import MobileSettingsScreen from '../components/MobileSettingsScreen'
import { StorageRetentionSection } from '../components/settings/StorageRetentionSection'
import { useSettingsDirtySection, useSettingsDirty } from '../components/settings/settings-dirty'

vi.mock('../lib/use-is-mobile', () => ({ useIsMobile: () => true }))

/** 模拟一个「有未保存表单」的分区（真实分区以自己的 dirty 值调用同
 * 一登记钩子；登记处是全局的，无需真的渲染邮件表单）。 */
function DirtyProbe({ id, dirty }: { id: string; dirty: boolean }): null {
  useSettingsDirtySection(id, dirty)
  return null
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/** 分区挂载时的服务端读取一律给安全空值，测试只关注导航守护。
 * 路径感知：邮件分类真实挂载 MailSection（IMAP/digest 表单），
 * 两个设置的读取必须给契约形状，否则表单以 undefined 初始化崩溃
 * （生产 API 恒返回该形状；这是测试替身的保真度，不是产品缺陷）。 */
function quietBodyFor(url: string): unknown {
  if (url.includes('/mail/imap/settings')) {
    return {
      configured: false,
      enabled: false,
      host: '',
      port: 993,
      user: '',
      folder: 'INBOX',
      ssl: true,
      listUuid: '',
      intervalSeconds: 300,
      passwordConfigured: false,
    }
  }
  if (url.includes('/digest/settings')) {
    return {
      enabled: false,
      hour: 8,
      source: 'read_later',
      limitCount: 20,
      smtpHost: '',
      smtpPort: 587,
      smtpUser: '',
      fromAddr: '',
      toAddr: '',
      timezone: '',
      passwordConfigured: false,
      lastError: null,
      lastSentAt: null,
      nextSendAt: null,
    }
  }
  return { items: [], stored: false, configured: false }
}

function stubFetchQuiet(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) =>
      jsonResponse(quietBodyFor(String(input))),
    ),
  )
}

function renderModal(onClose: () => void) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DirtyProbe id="mail" dirty />
      <SettingsModal open onClose={onClose} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  useSettingsDirty.getState().clearAll()
  stubFetchQuiet()
})

afterEach(() => {
  vi.unstubAllGlobals()
  useSettingsDirty.getState().clearAll()
})

describe('FIX-057 桌面设置中心脏守护', () => {
  it('有脏分区时切分类先确认；继续编辑留在原分类，放弃后切换', async () => {
    renderModal(vi.fn())
    // 基线：初始在「通用」分类。
    expect(screen.getByRole('heading', { name: '通用' })).toBeInTheDocument()

    // 点击目标分类 → 先弹「未保存的更改」确认（导航被拦截）。
    fireEvent.click(screen.getByRole('button', { name: '邮件简报' }))
    const dialog = await screen.findByRole('dialog', { name: '有未保存的更改' })
    expect(dialog).toBeInTheDocument()

    // 继续编辑：弹窗关闭，分类未切换（确认弹窗打开时外层被 aria-hidden，
    // 类别标题在弹窗关闭后断言）。
    fireEvent.click(withinDialog(dialog, '继续编辑'))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '有未保存的更改' })).toBeNull())
    expect(screen.getByRole('heading', { name: '通用' })).toBeInTheDocument()
    // 邮件分类未进入（其标题在 modal h2 与分区 title h3 各出现一次）。
    expect(screen.queryAllByRole('heading', { name: '邮件简报' })).toHaveLength(0)

    // 再次导航 → 放弃并离开：切换到目标分类。
    fireEvent.click(screen.getByRole('button', { name: '邮件简报' }))
    fireEvent.click(await screen.findByRole('button', { name: '放弃并离开' }))
    await waitFor(() =>
      expect(screen.getAllByRole('heading', { name: '邮件简报' }).length).toBeGreaterThan(0),
    )
  })

  it('有脏分区时关闭设置先确认；放弃后才执行 onClose；无脏时零打扰', async () => {
    const onClose = vi.fn()
    const view = renderModal(onClose)

    fireEvent.click(screen.getByRole('button', { name: '关闭设置' }))
    await screen.findByRole('dialog', { name: '有未保存的更改' })
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '放弃并离开' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))

    // 无脏分区（登记清空）→ 关闭零打扰。
    view.unmount()
    useSettingsDirty.getState().clearAll()
    const onClose2 = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SettingsModal open onClose={onClose2} />
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: '关闭设置' }))
    expect(onClose2).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog', { name: '有未保存的更改' })).toBeNull()
  })
})

describe('FIX-057 移动端设置脏守护', () => {
  it('子页返回 / 关闭设置在有脏分区时先确认', async () => {
    const onClose = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <DirtyProbe id="mail" dirty />
        <MobileSettingsScreen open onClose={onClose} openCategory={{ category: 'mail', seq: 1 }} />
      </QueryClientProvider>,
    )

    // 深链已进入「邮件简报」子页；返回设置 → 先确认。
    fireEvent.click(screen.getByRole('button', { name: '返回设置' }))
    await screen.findByRole('dialog', { name: '有未保存的更改' })
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('FIX-057 真实分区登记集成（StorageRetentionSection）', () => {
  it('输入未保存的天数 → 登记脏状态；分区卸载（切走/关闭）→ 自动撤销', async () => {
    // 路径感知 stub：保留策略读服务端值（enabled:false, 天数 null）。
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/storage/retention')) {
          return jsonResponse({ enabled: false, aiVersionsDays: null, taskLogDays: null })
        }
        return jsonResponse({ items: [], stored: false, configured: false })
      }),
    )

    const view = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <StorageRetentionSection />
      </QueryClientProvider>,
    )

    // 服务端值到达后输入不同天数 → 分区向登记处上报脏状态。
    const aiDays = await screen.findByLabelText('AI 历史版本保留天数')
    fireEvent.change(aiDays, { target: { value: '90' } })
    await waitFor(() =>
      expect(useSettingsDirty.getState().dirtySections.has('storage-retention')).toBe(true),
    )

    // 分区卸载（= 设置中心切走分类 / 关闭设置时的真实路径）→ 自动撤销。
    view.unmount()
    expect(useSettingsDirty.getState().dirtySections.has('storage-retention')).toBe(false)
  })
})

/** 对话框内按文案点按钮（footer 按钮在 dialog 容器内）。 */
function withinDialog(dialog: HTMLElement, text: string): HTMLElement {
  const button = Array.from(dialog.querySelectorAll('button')).find(
    (b) => b.textContent === text,
  )
  if (button === undefined) throw new Error(`button ${text} not found in dialog`)
  return button
}
