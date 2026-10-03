/** P07 — 用户可配置的阅读器工具栏（注册表 + 设备本地持久化）行为证明。
 *
 * - normalizeReaderToolbarOrder：去重 / 丢未知 / 缺项按默认序补全 /
 *   隐藏 '-id' 占位不被补全复活 / 锁定动作（收藏、更多操作）强制可见 /
 *   空数组与非数组回退断点默认序；
 * - 默认渲染序 = 既有视觉序的忠实快照（桌面平铺序 + O127 移动收纳序）；
 * - 自定义对话框（更多操作 → 自定义工具栏）：上移/下移、显隐开关、
 *   锁定动作开关禁用、恢复默认 / 取消 / 保存；
 * - 持久化：保存 → store（两断点各自记忆，R25 起随 portable 同步上云）→
 *   重挂载 / loadSettings 模拟重启后仍生效；
 * - jsdom 无 matchMedia → useIsMobile 视为移动端（与既有约定一致）；
 *   桌面按钮仍渲染在 DOM（max-lg:hidden 折叠组），菜单为移动端收纳。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import {
  DEFAULT_APP_SETTINGS,
  PORTABLE_KEYS,
  loadSettings,
  normalizeSettings,
  useAppSettings,
} from '../store/app-settings'
import {
  defaultReaderToolbarOrder,
  normalizeReaderToolbarOrder,
  parseReaderToolbarEntry,
  resolveReaderToolbarVisible,
} from '../lib/reader-toolbar'
import type { EntryDetail } from '../api/types'

// ---- 公共 fixture / harness ----

function detailFixture(over: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: '<p>正文</p>',
    ...over,
  }
}

const allCallbacks = {
  onViewModeChange: () => {},
  onOpenAiConversation: () => {},
  onOpenFind: () => {},
  onOpenLinks: () => {},
  collectSpeechBlocks: () => ({ texts: ['第一段正文'], startIndex: 0 }),
  onAutoScrollToggle: () => {},
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

/** 断言元素在 DOM 文档序中依次出现（工具栏视觉序的 DOM 近似）。 */
function assertDomOrder(elements: HTMLElement[]): void {
  for (let i = 1; i < elements.length; i++) {
    expect(
      elements[i - 1]!.compareDocumentPosition(elements[i]!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  }
}

function stubSpeech(): void {
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => [],
    speak: vi.fn(),
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
  })
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---- normalize 纯函数 ----

const DESKTOP_DEFAULT = [
  'star',
  'open-original',
  'snapshot',
  'ai',
  'language',
  'find',
  'links',
  'speech',
  'share',
  'quote',
  'print',
  // NEW-353/355：位置校准 / 媒体预算（注册表新增，排在锁定「更多操作」前）
  'calibrate',
  'budget',
  'more',
]
const MOBILE_DEFAULT = [
  'star',
  'open-original',
  'language',
  'find',
  'links',
  'ai',
  'snapshot',
  'speech',
  'share',
  'quote',
  'print',
  // NEW-353/355：位置校准 / 媒体预算（注册表新增，排在锁定「更多操作」前）
  'calibrate',
  'budget',
  'more',
]

describe('P07 normalizeReaderToolbarOrder — 不可信存储归一化', () => {
  it('空数组 → 断点默认序（桌面 = 0009 既有视觉序）', () => {
    expect(normalizeReaderToolbarOrder([], 'desktop')).toEqual(DESKTOP_DEFAULT)
    expect(defaultReaderToolbarOrder('desktop')).toEqual(DESKTOP_DEFAULT)
  })

  it('非数组（undefined / 字符串 / 数字）→ 默认序', () => {
    expect(normalizeReaderToolbarOrder(undefined, 'desktop')).toEqual(DESKTOP_DEFAULT)
    expect(normalizeReaderToolbarOrder('garbage', 'desktop')).toEqual(DESKTOP_DEFAULT)
    expect(normalizeReaderToolbarOrder(42, 'mobile')).toEqual(MOBILE_DEFAULT)
  })

  it('移动端默认序 = O127 收纳序（primary 平铺 + 菜单序）', () => {
    expect(normalizeReaderToolbarOrder([], 'mobile')).toEqual(MOBILE_DEFAULT)
    expect(defaultReaderToolbarOrder('mobile')).toEqual(MOBILE_DEFAULT)
  })

  it('未知 id 丢弃；非字符串 / 空串项丢弃', () => {
    expect(normalizeReaderToolbarOrder(['bogus', 'share', '', 42, null], 'desktop')).toEqual([
      'share',
      'star',
      'open-original',
      'snapshot',
      'ai',
      'language',
      'find',
      'links',
      'speech',
      'quote',
      'print',
      'calibrate',
      'budget',
      'more',
    ])
  })

  it('重复 id 去重（首个生效）', () => {
    expect(normalizeReaderToolbarOrder(['star', 'print', 'star'], 'desktop')).toEqual([
      'star',
      'print',
      'open-original',
      'snapshot',
      'ai',
      'language',
      'find',
      'links',
      'speech',
      'share',
      'quote',
      'calibrate',
      'budget',
      'more',
    ])
  })

  it("缺失 id（注册表新增）按默认序追加在可见段末尾", () => {
    expect(normalizeReaderToolbarOrder(['print'], 'desktop')).toEqual([
      'print',
      'star',
      'open-original',
      'snapshot',
      'ai',
      'language',
      'find',
      'links',
      'speech',
      'share',
      'quote',
      'calibrate',
      'budget',
      'more',
    ])
  })

  it("隐藏占位 '-id'：不进可见序列，且不被缺项补全复活（占位保留在存储尾部）", () => {
    const normalized = normalizeReaderToolbarOrder(['star', '-share'], 'desktop')
    expect(normalized).toEqual([...DESKTOP_DEFAULT.filter((id) => id !== 'share'), '-share'])
    expect(resolveReaderToolbarVisible(normalized, 'desktop')).toEqual(
      DESKTOP_DEFAULT.filter((id) => id !== 'share'),
    )
  })

  it("未知隐藏占位 '-bogus' 丢弃", () => {
    expect(normalizeReaderToolbarOrder(['-bogus', 'star'], 'desktop')).toEqual([
      'star',
      ...DESKTOP_DEFAULT.filter((id) => id !== 'star'),
    ])
  })

  it('锁定动作（收藏 / 更多操作）强制可见——不可被移除', () => {
    const normalized = normalizeReaderToolbarOrder(['-star', '-more', '-share'], 'desktop')
    const visible = resolveReaderToolbarVisible(normalized, 'desktop')
    expect(visible).toContain('star')
    expect(visible).toContain('more')
    expect(visible).not.toContain('share')
  })

  it('归一化幂等：normalize(normalize(x)) 深相等（存储往返稳定）', () => {
    const once = normalizeReaderToolbarOrder(['print', 'star', '-share', 'star', 'bogus'], 'desktop')
    expect(normalizeReaderToolbarOrder(once, 'desktop')).toEqual(once)
  })

  it('parseReaderToolbarEntry：可见 / 隐藏 / 非法三元', () => {
    expect(parseReaderToolbarEntry('star')).toEqual({ id: 'star', visible: true })
    expect(parseReaderToolbarEntry('-share')).toEqual({ id: 'share', visible: false })
    expect(parseReaderToolbarEntry('nope')).toBeNull()
    expect(parseReaderToolbarEntry(42)).toBeNull()
    expect(parseReaderToolbarEntry('  ')).toBeNull()
  })

  it('resolveReaderToolbarVisible：输入即归一化值 → 纯可见 id 序列', () => {
    expect(resolveReaderToolbarVisible(MOBILE_DEFAULT, 'mobile')).toEqual(MOBILE_DEFAULT)
    expect(
      resolveReaderToolbarVisible(['star', '-print', 'nope', 'star'], 'desktop'),
    ).toEqual(['star', ...DESKTOP_DEFAULT.filter((id) => id !== 'star' && id !== 'print')])
  })
})

describe('P07 app-settings 集成 — 设备本地两键', () => {
  it('normalizeSettings：非法工具栏序 → 默认；合法值保留', () => {
    const bad = normalizeSettings({ readerToolbarDesktopOrder: 'nope' })
    expect(bad.readerToolbarDesktopOrder).toEqual(DESKTOP_DEFAULT)
    expect(bad.readerToolbarMobileOrder).toEqual(MOBILE_DEFAULT)
    const good = normalizeSettings({
      readerToolbarDesktopOrder: ['print', 'star'],
      readerToolbarMobileOrder: ['-share'],
    })
    expect(good.readerToolbarDesktopOrder).toEqual([
      'print',
      'star',
      ...DESKTOP_DEFAULT.filter((id) => id !== 'print' && id !== 'star'),
    ])
    expect(good.readerToolbarMobileOrder).toEqual([
      ...MOBILE_DEFAULT.filter((id) => id !== 'share'),
      '-share',
    ])
  })

  it('normalizeSettings(null) 深等于 DEFAULT_APP_SETTINGS（默认序稳定）', () => {
    expect(normalizeSettings(null)).toEqual(DEFAULT_APP_SETTINGS)
  })

  it('工具栏键进 PORTABLE_KEYS（R25 起随 portable 同步；服务端透传 -id 占位）', () => {
    // R25 迁移：工具栏排布从设备本地升级为云端偏好。存储格式不变
    // （'-id' 隐藏占位），服务端只做 ^[a-z0-9-]+$ 透传校验。
    expect(PORTABLE_KEYS).toContain('readerToolbarDesktopOrder')
    expect(PORTABLE_KEYS).toContain('readerToolbarMobileOrder')
  })

  it('persistSettings → loadSettings 往返保留自定义（重启语义）', () => {
    const storage = window.localStorage
    storage.setItem(
      'lumirss-settings',
      JSON.stringify({
        ...DEFAULT_APP_SETTINGS,
        readerToolbarDesktopOrder: ['print', '-share'],
      }),
    )
    const loaded = loadSettings(storage)
    expect(loaded.readerToolbarDesktopOrder).toEqual([
      'print',
      'star',
      'open-original',
      'snapshot',
      'ai',
      'language',
      'find',
      'links',
      'speech',
      'quote',
      'calibrate',
      'budget',
      'more',
      '-share',
    ])
    expect(loaded.readerToolbarMobileOrder).toEqual(MOBILE_DEFAULT)
  })
})

// ---- ReaderHeader 渲染 ----

describe('P07 — 默认渲染序 = 既有视觉序', () => {
  it('桌面平铺序（DOM 序快照）：收藏→打开原文→快照→AI→语言→查找→链接→朗读→分享→引用→打印→更多', () => {
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    // jsdom 无 navigator.share → 诚实降级标签「复制链接」；无 speechSynthesis → 朗读禁用按钮仍在 DOM
    assertDomOrder([
      screen.getByRole('button', { name: '收藏' }),
      screen.getByRole('link', { name: '打开原文' }),
      screen.getByRole('button', { name: '保存快照' }),
      screen.getByRole('button', { name: 'AI 对话' }),
      screen.getByRole('button', { name: '语言视图：当前 原文' }),
      screen.getByRole('button', { name: '文内查找' }),
      screen.getByRole('button', { name: '文中链接' }),
      screen.getByRole('button', { name: '朗读' }),
      screen.getByRole('button', { name: '复制链接' }),
      screen.getByRole('button', { name: '复制引用' }),
      screen.getByRole('button', { name: '打印' }),
      screen.getByRole('button', { name: '更多操作' }),
    ])
  })

  it('移动端收纳：primary 动作裸渲染；非 primary 仍在 DOM 但位于 max-lg:hidden 折叠组', () => {
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    expect(
      screen.getByRole('button', { name: '收藏' }).closest('[class*="max-lg:hidden"]'),
    ).toBeNull()
    expect(
      screen.getByRole('button', { name: '打印' }).closest('[class*="max-lg:hidden"]'),
    ).not.toBeNull()
    expect(
      screen.getByRole('button', { name: '保存快照' }).closest('[class*="max-lg:hidden"]'),
    ).not.toBeNull()
  })

  it('移动端菜单默认序 = R23 五组小标题（阅读/整理/笔记/分享与导出/高级）内的 O127 序', async () => {
    // 有意迁移（R23）：旧断言为扁平菜单序；分组后 section 小标题由
    // ActionMenu GroupLabel 承载（非 menuitem），条目 = 组固定顺序 ×
    // 组内用户移动端相对序。空组（如桌面整理组）不渲染小标题。
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    const menu = await screen.findByRole('menu')
    const names = within(menu)
      .getAllByRole('menuitem')
      .map((el) => el.textContent ?? '')
    expect(names).toEqual([
      // 阅读（朗读未入菜单：jsdom 无 speechSynthesis；位置校准/媒体预算
      // 未入：allCallbacks 未提供对应回调——可用性门槛与旧契约一致）
      '文内查找',
      '文中链接',
      'AI 对话',
      '自动滚屏',
      // 整理
      '保存快照',
      // 笔记
      '导出到 Obsidian',
      // 分享与导出
      '复制链接', // jsdom 无 navigator.share
      '复制为纯文本',
      '复制为 Markdown',
      '打印',
      '导出 Markdown',
      '导出 HTML',
      // 高级
      '自定义工具栏',
    ])
    // 五组小标题按固定组序出现（jsdom 全部组非空）
    const labels = within(menu)
      .getAllByText(/^(阅读|整理|笔记|分享与导出|高级)$/)
      .map((el) => el.textContent)
    expect(labels).toEqual(['阅读', '整理', '笔记', '分享与导出', '高级'])
  })
})

describe('P07 — 自定义工具栏对话框', () => {
  let unmountReader: () => void = () => {}

  async function openCustomize(): Promise<HTMLElement> {
    const view = render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    unmountReader = view.unmount
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '自定义工具栏' }))
    return await screen.findByRole('dialog', { name: '自定义工具栏' })
  }

  it('打开：桌面 Tab 列出全部动作；锁定动作开关禁用 + 不可移除标记；边界上下移禁用', async () => {
    const dialog = await openCustomize()
    expect(within(dialog).getByRole('tab', { name: '桌面端' })).toHaveAttribute('aria-selected', 'true')
    // 锁定：收藏（首行）/ 更多操作（末行）不可移除（Base UI Switch 用 aria-disabled）
    expect(within(dialog).getByRole('switch', { name: '显示收藏' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(within(dialog).getByRole('switch', { name: '显示更多操作' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(within(dialog).getAllByText('不可移除')).toHaveLength(2)
    // 可解锁动作开关可用
    expect(within(dialog).getByRole('switch', { name: '显示打印' })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    )
    // 44×44 上移/下移：首行上移禁用、末行下移禁用
    expect(within(dialog).getByRole('button', { name: '上移收藏' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: '下移更多操作' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: '上移朗读' })).toBeEnabled()
  })

  it('移动端 Tab：primary 标记「工具栏」、其余「菜单」；独立开关状态', async () => {
    const dialog = await openCustomize()
    fireEvent.click(within(dialog).getByRole('tab', { name: '移动端' }))
    expect(within(dialog).getByRole('tab', { name: '移动端' })).toHaveAttribute('aria-selected', 'true')
    // 4 个 primary（收藏/打开原文/语言视图/更多操作）标「工具栏」，其余 10 个标「菜单」（NEW-353/355 注册表新增 2 个非 primary）
    expect(within(dialog).getAllByText('工具栏')).toHaveLength(4)
    expect(within(dialog).getAllByText('菜单')).toHaveLength(10)
    // 两套键独立：桌面隐藏不影响移动端开关
    expect(within(dialog).getByRole('switch', { name: '显示打印' })).toBeChecked()
  })

  it('桌面上移朗读 → 工具栏 DOM 序与存储同步反映', async () => {
    const dialog = await openCustomize()
    const up = within(dialog).getByRole('button', { name: '上移朗读' })
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))
    // 朗读从第 8 位上移 4 次 → 「保存快照」之后、「AI 对话」之前
    assertDomOrder([
      screen.getByRole('button', { name: '保存快照' }),
      screen.getByRole('button', { name: '朗读' }),
      screen.getByRole('button', { name: 'AI 对话' }),
    ])
    expect(useAppSettings.getState().settings.readerToolbarDesktopOrder).toEqual([
      'star',
      'open-original',
      'snapshot',
      'speech',
      'ai',
      'language',
      'find',
      'links',
      'share',
      'quote',
      'print',
      'calibrate',
      'budget',
      'more',
    ])
  })

  it('移动端上移朗读（菜单内）→ 菜单序反映；隐藏分享 → 工具栏与菜单都不再出现', async () => {
    stubSpeech()
    const dialog = await openCustomize()
    fireEvent.click(within(dialog).getByRole('tab', { name: '移动端' }))
    // 朗读上移 3 次：快照之前 → 菜单第二位（查找之后）
    const up = within(dialog).getByRole('button', { name: '上移朗读' })
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(up)
    // 隐藏分享（移动端）
    fireEvent.click(within(dialog).getByRole('switch', { name: '显示分享' }))
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    const menu = await screen.findByRole('menu')
    const names = within(menu)
      .getAllByRole('menuitem')
      .map((el) => el.textContent ?? '')
    expect(names).toEqual([
      // 阅读（朗读上移后在组内居查找之后；自动滚屏固定组尾）
      '文内查找',
      '朗读', // 上移后的菜单位置
      '文中链接',
      'AI 对话',
      '自动滚屏',
      // 整理
      '保存快照',
      // 笔记
      '导出到 Obsidian',
      // 分享与导出（分享已隐藏：不在菜单）
      '复制为纯文本',
      '复制为 Markdown',
      '打印',
      '导出 Markdown',
      '导出 HTML',
      // 高级
      '自定义工具栏',
    ])
    // 隐藏以 '-share' 占位持久化（不被缺项补全复活）
    expect(useAppSettings.getState().settings.readerToolbarMobileOrder.at(-1)).toBe('-share')
  })

  it('桌面隐藏打印 → 按钮从 DOM 消失；重挂载 + loadSettings 模拟重启后仍隐藏', async () => {
    const dialog = await openCustomize()
    fireEvent.click(within(dialog).getByRole('switch', { name: '显示打印' }))
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))
    expect(screen.queryByRole('button', { name: '打印' })).toBeNull()
    expect(useAppSettings.getState().settings.readerToolbarDesktopOrder).toContain('-print')

    // 模拟应用重启：从 localStorage 重新加载（update 已持久化）
    useAppSettings.setState({ settings: loadSettings(window.localStorage) })
    unmountReader()
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    expect(screen.queryByRole('button', { name: '打印' })).toBeNull()
    // 其余默认动作不受影响
    expect(screen.getByRole('button', { name: '收藏' })).toBeInTheDocument()
  })

  it('移动端重排持久化：保存 → 重挂载（store 状态延续）→ 菜单序保持', async () => {
    stubSpeech()
    const dialog = await openCustomize()
    fireEvent.click(within(dialog).getByRole('tab', { name: '移动端' }))
    const up = within(dialog).getByRole('button', { name: '上移朗读' })
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))

    // 重挂载 ReaderHeader（app-settings store 状态延续）
    unmountReader()
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    const menu = await screen.findByRole('menu')
    const names = within(menu)
      .getAllByRole('menuitem')
      .map((el) => el.textContent ?? '')
    expect(names.indexOf('朗读')).toBe(1)
    expect(names.indexOf('文内查找')).toBe(0)
  })

  it('恢复默认：工作副本复位（仍需保存提交），保存后回到默认序与默认显隐', async () => {
    const dialog = await openCustomize()
    // 先改乱：隐藏打印 + 上移朗读
    fireEvent.click(within(dialog).getByRole('switch', { name: '显示打印' }))
    const up = within(dialog).getByRole('button', { name: '上移朗读' })
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(up)
    fireEvent.click(up)
    expect(within(dialog).getByRole('switch', { name: '显示打印' })).not.toBeChecked()

    fireEvent.click(within(dialog).getByRole('button', { name: '恢复默认' }))
    expect(within(dialog).getByRole('switch', { name: '显示打印' })).toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))

    expect(screen.getByRole('button', { name: '打印' })).toBeInTheDocument()
    expect(useAppSettings.getState().settings.readerToolbarDesktopOrder).toEqual(DESKTOP_DEFAULT)
    expect(useAppSettings.getState().settings.readerToolbarMobileOrder).toEqual(MOBILE_DEFAULT)
  })

  it('取消：丢弃改动（store 与工具栏不变）', async () => {
    const dialog = await openCustomize()
    fireEvent.click(within(dialog).getByRole('switch', { name: '显示打印' }))
    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: '打印' })).toBeInTheDocument()
    expect(useAppSettings.getState().settings.readerToolbarDesktopOrder).toEqual(DESKTOP_DEFAULT)
  })

  it('Escape 关闭对话框（Base UI Dialog 原语行为），改动不落库', async () => {
    const dialog = await openCustomize()
    fireEvent.click(within(dialog).getByRole('switch', { name: '显示打印' }))
    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '自定义工具栏' })).toBeNull()
    })
    expect(useAppSettings.getState().settings.readerToolbarDesktopOrder).toEqual(DESKTOP_DEFAULT)
    expect(screen.getByRole('button', { name: '打印' })).toBeInTheDocument()
  })

  it('不可见动作仍守可用性门槛：朗读能力缺失 → 菜单不出「朗读」项', async () => {
    render(withProviders(<ReaderHeader detail={detailFixture()} {...allCallbacks} />))
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    const menu = await screen.findByRole('menu')
    expect(within(menu).queryByRole('menuitem', { name: '朗读' })).toBeNull()
  })
})
