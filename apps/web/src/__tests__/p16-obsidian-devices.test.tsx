/** P16 设备档案设置区（Obsidian 库 → 设备与导出）—— CRUD UI 测试。
 *
 * - 列表渲染（label / 平台 / vault 名）+ 展开/收起；
 * - 添加设备：表单校验（名称与 vault 必填）→ createObsidianDevice 载荷；
 * - 编辑：回填表单 → updateObsidianDevice 携带 deviceId；
 * - 删除：deleteObsidianDevice 携带 id；
 * - 两种 Vault 模式的诚实说明（env 挂载 vs 手动路径）分别渲染；
 * - ObsidianPage 集成：页面尾部出现「设备与导出」区。
 *
 * 统一 vi.mock('../api/client')（保留真实导出）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ObsidianDeviceProfile } from '../api/client'
import ObsidianDevicesSection from '../components/obsidian/ObsidianDevicesSection'
import ObsidianPage from '../components/pages/ObsidianPage'

const mocks = vi.hoisted(() => ({
  listObsidianDevices: vi.fn(),
  createObsidianDevice: vi.fn(),
  updateObsidianDevice: vi.fn(),
  deleteObsidianDevice: vi.fn(),
  getObsidianStatus: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    listObsidianDevices: mocks.listObsidianDevices,
    createObsidianDevice: mocks.createObsidianDevice,
    updateObsidianDevice: mocks.updateObsidianDevice,
    deleteObsidianDevice: mocks.deleteObsidianDevice,
    getObsidianStatus: mocks.getObsidianStatus,
  }
})

// 模板编辑器在设备区之下；本文件聚焦设备 CRUD，把模板接口 mock 成空态。
mocks.getObsidianStatus.mockResolvedValue({
  vaultPath: '/vault',
  lastScanAt: null,
  lastError: null,
  noteCount: 0,
  envRootConfigured: false,
})

function deviceFixture(over: Partial<ObsidianDeviceProfile> = {}): ObsidianDeviceProfile {
  return {
    id: 'device-1',
    label: 'Windows 台式机',
    vaultName: '我的笔记库',
    vaultIdentifier: '',
    platform: 'windows',
    createdAt: '2026-09-23T00:00:00Z',
    ...over,
  }
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function renderSection(props: Partial<{ envRootConfigured: boolean }> = {}) {
  return render(withProviders(<ObsidianDevicesSection envRootConfigured={false} {...props} />))
}

describe('ObsidianDevicesSection（P16 设备档案 CRUD）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listObsidianDevices.mockResolvedValue({ items: [] })
  })

  it('折叠态展开后渲染设备列表；手动路径模式的诚实说明可见', async () => {
    mocks.listObsidianDevices.mockResolvedValue({ items: [deviceFixture()] })
    renderSection()
    expect(screen.getByRole('button', { name: /设备与导出/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    fireEvent.click(screen.getByRole('button', { name: /设备与导出/ }))
    expect(await screen.findByText('Windows 台式机')).toBeInTheDocument()
    expect(screen.getByText(/Vault：我的笔记库/)).toBeInTheDocument()
    expect(
      screen.getByText(/当前为手动路径模式：服务器上配置的 Vault 路径只用于只读索引。/),
    ).toBeInTheDocument()
    expect(screen.getByText(/仅用于生成 obsidian:\/\/ 打开链接/)).toBeInTheDocument()
  })

  it('env 挂载模式说明（与设备档案解耦的诚实文案）', () => {
    renderSection({ envRootConfigured: true })
    expect(
      screen.getByText(/当前为环境挂载模式：宿主 Vault 以只读方式挂载进服务器/),
    ).toBeInTheDocument()
  })

  it('添加设备：必填校验 + createObsidianDevice 收到规范化载荷', async () => {
    mocks.createObsidianDevice.mockResolvedValue(deviceFixture())
    renderSection()
    fireEvent.click(screen.getByRole('button', { name: /设备与导出/ }))
    fireEvent.click(await screen.findByRole('button', { name: '新增设备档案' }))

    // 必填：vault 名为空时按钮禁用（label 也必填）。
    fireEvent.change(screen.getByLabelText('设备名称'), { target: { value: 'iPhone 15' } })
    expect(screen.getByRole('button', { name: /^添加设备$/ })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Vault 名称'), { target: { value: '移动库' } })
    fireEvent.change(screen.getByLabelText('平台'), { target: { value: 'ios' } })
    fireEvent.click(screen.getByRole('button', { name: /^添加设备$/ }))

    await waitFor(() =>
      expect(mocks.createObsidianDevice).toHaveBeenCalledWith({
        label: 'iPhone 15',
        vaultName: '移动库',
        vaultIdentifier: '',
        platform: 'ios',
      }),
    )
  })

  it('编辑设备：表单回填，update 携带 deviceId；删除：delete 携带 id', async () => {
    mocks.updateObsidianDevice.mockResolvedValue(deviceFixture())
    mocks.deleteObsidianDevice.mockResolvedValue(undefined)
    mocks.listObsidianDevices.mockResolvedValue({ items: [deviceFixture()] })
    renderSection()
    fireEvent.click(screen.getByRole('button', { name: /设备与导出/ }))
    expect(await screen.findByText('Windows 台式机')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '编辑设备 Windows 台式机' }))
    const labelInput = await screen.findByLabelText('设备名称')
    expect(labelInput).toHaveValue('Windows 台式机')
    fireEvent.change(labelInput, { target: { value: 'Windows 台式机（新）' } })
    fireEvent.click(screen.getByRole('button', { name: /保存修改/ }))
    await waitFor(() =>
      expect(mocks.updateObsidianDevice).toHaveBeenCalledWith(
        'device-1',
        {
          label: 'Windows 台式机（新）',
          vaultName: '我的笔记库',
          vaultIdentifier: '',
          platform: 'windows',
        },
      ),
    )

    fireEvent.click(screen.getByRole('button', { name: '删除设备 Windows 台式机' }))
    await waitFor(() => expect(mocks.deleteObsidianDevice).toHaveBeenCalledWith('device-1'))
  })

  it('列表加载失败：错误原样透出 + 重试', async () => {
    mocks.listObsidianDevices.mockRejectedValue(new Error('network down'))
    renderSection()
    fireEvent.click(screen.getByRole('button', { name: /设备与导出/ }))
    expect(await screen.findByText(/设备列表加载失败：network down/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(mocks.listObsidianDevices).toHaveBeenCalledTimes(2))
  })
})

describe('ObsidianPage 集成（P16）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listObsidianDevices.mockResolvedValue({ items: [] })
    mocks.getObsidianStatus.mockResolvedValue({
      vaultPath: '/vault',
      lastScanAt: null,
      lastError: null,
      noteCount: 3,
      envRootConfigured: false,
    })
  })

  it('已配置 Vault 的页面尾部出现「设备与导出」区', async () => {
    render(withProviders(<ObsidianPage />))
    expect(await screen.findByText('Obsidian 库')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /设备与导出/ })).toBeInTheDocument()
  })
})
