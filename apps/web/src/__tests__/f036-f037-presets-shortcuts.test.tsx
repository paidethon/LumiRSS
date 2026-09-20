/** F036 阅读预设设备适用 + F037 快捷键自定义（纯逻辑核心场景）。 */

import { describe, expect, it } from 'vitest'
import {
  applyPresetForDevice,
  migrateLegacyPreset,
  serializePresetV2,
  upsertPreset,
} from '../lib/reader-preset-device'
import {
  assignShortcut,
  detectConflict,
  effectiveBinding,
  formatCombo,
  isReservedCombo,
  normalizeCombo,
  resetShortcut,
} from '../lib/custom-shortcuts'

describe('F036 阅读布局预设设备适用', () => {
  it('F036: 旧预设无字段迁移（deviceScope=all，版本 +1）', () => {
    const legacy = { id: 'p1', name: '旧预设', builtin: false, vars: { readerFontSize: 18 } }
    const migrated = migrateLegacyPreset(legacy)
    expect(migrated.vars.deviceScope).toBe('all')
    expect(migrated.schemaVersion).toBe(2)
  })

  it('F036: mobile 应用 desktop-only 忽略宽度/栏数并标注', () => {
    const result = applyPresetForDevice(
      {
        readerFontSize: 18,
        readerContentWidth: 880,
        readerColumns: 2,
        deviceScope: 'desktop',
      },
      true,
    )
    expect(result.vars.readerContentWidth).toBeUndefined()
    expect(result.vars.readerColumns).toBeUndefined()
    expect(result.vars.readerFontSize).toBe(18)
    expect(result.notice).toContain('桌面端生效')
    expect(result.ignored).toContain('宽度')

    // 桌面端不忽略；scope=all 的 mobile 也不忽略
    expect(applyPresetForDevice({ readerColumns: 2, deviceScope: 'desktop' }, false).ignored).toEqual([])
    expect(applyPresetForDevice({ readerColumns: 2, deviceScope: 'all' }, true).ignored).toEqual([])
  })

  it('F036: 覆盖同名 / 重名校验 / 导入导出往返含新字段', () => {
    const list = [{ id: 'a', name: '夜间' }, { id: 'b', name: '护眼' }]
    // 同 id 覆盖
    const covered = upsertPreset(list, { id: 'a', name: '夜间·改' })
    expect(covered.error).toBeNull()
    expect(covered.list.find((p) => p.id === 'a')?.name).toBe('夜间·改')
    // 同名不同 id → 重名校验拒绝
    const dup = upsertPreset(list, { id: 'c', name: '护眼' })
    expect(dup.error).toBe('duplicate-name')

    // 往返：序列化含 width/columns/scope
    const roundtrip = JSON.parse(JSON.stringify(
      serializePresetV2({
        id: 'x',
        name: '宽版',
        builtin: false,
        vars: { readerContentWidth: 920, readerColumns: 2, deviceScope: 'desktop' },
      }),
    ))
    expect(roundtrip.vars.readerContentWidth).toBe(920)
    expect(roundtrip.vars.readerColumns).toBe(2)
    expect(roundtrip.vars.deviceScope).toBe('desktop')
    expect(roundtrip.schemaVersion).toBe(2)
  })
})

describe('F037 快捷键自定义', () => {
  it('F037: 组合归一化/格式化与覆盖生效（解析顺序 用户→默认）', () => {
    expect(normalizeCombo('Ctrl+Shift+K')).toBe('mod+shift+k')
    expect(normalizeCombo('⌘+j')).toBe('mod+j')
    expect(normalizeCombo('ArrowDown')).toBe('down')
    expect(formatCombo('mod+shift+k')).toBe('Ctrl/⌘+Shift+K')
    expect(formatCombo('down')).toBe('↓')

    const defaults = { next: 'j', help: '?' }
    const custom = { next: 'down' }
    expect(effectiveBinding('next', defaults, custom)).toBe('down')
    expect(effectiveBinding('help', defaults, custom)).toBe('?')
  })

  it('F037: 冲突检测与显式覆盖确认流', () => {
    const custom = { next: 'n' }
    // 冲突：把 prev 也分配到 n → 检出冲突，且未直接写入
    const first = assignShortcut(custom, 'prev', 'n')
    expect(first.error).toBe('conflict')
    expect(first.conflictWith).toBe('next')
    expect(first.custom.prev).toBeUndefined()
    // 显式覆盖 → 写入成功
    const overwritten = assignShortcut(custom, 'prev', 'n', { overwrite: true })
    expect(overwritten.error).toBeNull()
    expect(overwritten.custom.prev).toBe('n')
    // detectConflict 直接查询
    expect(detectConflict(overwritten.custom, 'next', 'n').conflictWith).toBe('prev')
  })

  it('F037: 黑名单拒绝（浏览器必备组合）', () => {
    expect(isReservedCombo('Ctrl+T')).toBe(true)
    expect(isReservedCombo('mod+w')).toBe(true)
    expect(isReservedCombo('Ctrl+Tab')).toBe(true)
    const result = assignShortcut({}, 'next', 'Ctrl+N')
    expect(result.error).toBe('reserved')
    expect(Object.keys(result.custom)).toHaveLength(0)
  })

  it('F037: 恢复默认（单项/全部）与 localStorage 持久化语义', () => {
    const custom = { next: 'down', prev: 'up', help: 'h' }
    const one = resetShortcut(custom, 'prev')
    expect(one).toEqual({ next: 'down', help: 'h' })
    expect(resetShortcut(custom)).toEqual({})
    // 存储层（save/load）在浏览器 localStorage 模拟下验证
    const store = new Map<string, string>()
    const fakeWindow = {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
        clear: () => store.clear(),
      },
    }
    const originalWindow = (globalThis as { window?: unknown }).window
    ;(globalThis as { window?: unknown }).window = fakeWindow
    // 动态导入以命中 window；结束后恢复真实 window（避免污染同文件后续用例）
    return import('../lib/custom-shortcuts')
      .then((mod) => {
        mod.saveCustomShortcuts({ next: 'down' })
        expect(mod.loadCustomShortcuts()).toEqual({ next: 'down' })
      })
      .finally(() => {
        ;(globalThis as { window?: unknown }).window = originalWindow
      })
  })
})

// ---- W2 收尾补测：F036 预设编辑器 UI + F037 帮助弹窗生效绑定 ----

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, vi } from 'vitest'
import { ReaderPresetPicker } from '../components/settings/AppearanceControls'
import ShortcutsHelpDialog from '../components/ShortcutsHelpDialog'
import { useKeyboardShortcuts } from '../lib/keyboard-shortcuts'
import { effectiveShortcuts } from '../lib/keyboard-shortcuts'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'

function withQc(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: useAppSettings.getState().settings })
})

describe('F036 预设编辑器 UI（W2 收尾）', () => {
  it('F036: 用户预设暴露 宽度/栏数/设备适用，desktop 标注「桌面端生效」', () => {
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        readerPresetId: 'user-x',
        readerPresets: [
          {
            id: 'user-x',
            name: '宽版',
            builtin: false,
            vars: {
              readerFontFamily: 'system',
              readerFontSize: 17,
              readerLineHeight: 1.85,
              readerBackground: 'follow',
              readerParagraphSpacing: 0.85,
              readerJustify: false,
              readerContentWidth: 920,
              readerColumns: 2,
              deviceScope: 'desktop',
            },
          },
        ],
      },
    })
    render(withQc(<ReaderPresetPicker />))
    // 编辑器暴露三个字段
    expect(screen.getByText('布局宽度')).toBeInTheDocument()
    expect(screen.getByText('栏数')).toBeInTheDocument()
    expect(screen.getByText('设备适用')).toBeInTheDocument()
    // desktop 标注
    expect(screen.getByText(/桌面端生效：移动端应用此预设时忽略布局宽度与栏数/)).toBeInTheDocument()
    // 切回「全部设备」标注消失
    fireEvent.click(screen.getByRole('button', { name: '全部设备' }))
    expect(screen.queryByText(/桌面端生效/)).not.toBeInTheDocument()
  })

  it('F036: 移动端（jsdom 视为 mobile）应用 desktop-only 预设忽略宽度并诚实标注', () => {
    useAppSettings.setState({
      settings: {
        ...useAppSettings.getState().settings,
        readerPresetId: 'default',
        readerContentWidth: 720,
        readerPresets: [
          {
            id: 'user-x',
            name: '宽版',
            builtin: false,
            vars: {
              readerFontFamily: 'system',
              readerFontSize: 17,
              readerLineHeight: 1.85,
              readerBackground: 'follow',
              readerParagraphSpacing: 0.85,
              readerJustify: false,
              readerContentWidth: 920,
              deviceScope: 'desktop',
            },
          },
        ],
      },
    })
    render(withQc(<ReaderPresetPicker />))
    fireEvent.click(screen.getByText('宽版').closest('button')!)
    // jsdom 无 matchMedia → useIsMobile 回退 true：宽度被忽略、字号仍生效
    expect(useAppSettings.getState().settings.readerContentWidth).toBe(720)
    expect(useAppSettings.getState().settings.readerFontSize).toBe(17)
    expect(screen.getByRole('status').textContent).toContain('桌面端生效')
  })
})

describe('F037 帮助弹窗生效绑定（W2 收尾）', () => {
  it('F037: 覆盖项显示生效组合 + 已自定义；单项/全部恢复默认同步', async () => {
    window.localStorage.setItem('lumi.customShortcuts', JSON.stringify({ next: 'down' }))
    const onClose = vi.fn()
    render(<ShortcutsHelpDialog open onClose={onClose} />)
    // 生效绑定：下一篇显示 ↓（覆盖），且带已自定义标注
    const nextRow = screen.getByText('下一篇').closest('div')!
    expect(nextRow.textContent).toContain('↓')
    expect(nextRow.textContent).toContain('已自定义')
    // 未覆盖项显示默认且无标注
    const prevRow = screen.getByText('上一篇').closest('div')!
    expect(prevRow.textContent).toContain('k / ↑')
    expect(prevRow.textContent).not.toContain('已自定义')
    // 单项恢复默认
    fireEvent.click(screen.getByRole('button', { name: '恢复默认：下一篇' }))
    await waitFor(() => {
      expect(screen.getByText('下一篇').closest('div')!.textContent).toContain('j / ↓')
    })
    expect(JSON.parse(window.localStorage.getItem('lumi.customShortcuts') ?? '{}')).toEqual({})
  })

  it('F037: 全部恢复默认清空覆盖；effectiveShortcuts 派生与按键消费一致', async () => {
    window.localStorage.setItem(
      'lumi.customShortcuts',
      JSON.stringify({ next: 'down', toggleUnread: 'x' }),
    )
    render(<ShortcutsHelpDialog open onClose={() => {}} />)
    expect(screen.getAllByText('已自定义')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: /全部恢复默认/ }))
    await waitFor(() => {
      expect(screen.queryByText('已自定义')).not.toBeInTheDocument()
    })
    // 派生函数：覆盖优先 + 展示格式
    const rows = effectiveShortcuts({ next: 'mod+shift+j' })
    expect(rows.find((r) => r.id === 'next')).toMatchObject({ keys: 'Ctrl/⌘+Shift+J', overridden: true })
    expect(rows.find((r) => r.id === 'prev')).toMatchObject({ keys: 'k / ↑', overridden: false })
  })

  it('F037: useKeyboardShortcuts 消费覆盖（x 切未读，u 失效）', () => {
    window.localStorage.setItem('lumi.customShortcuts', JSON.stringify({ toggleUnread: 'x' }))
    useReaderUi.setState({
      section: 'home',
      scope: { kind: 'all' },
      view: 'all',
      selectedEntryRef: null,
    })
    function Host() {
      useKeyboardShortcuts({})
      return null
    }
    render(withQc(<Host />))
    fireEvent(window, new KeyboardEvent('keydown', { key: 'x', bubbles: true }))
    expect(useReaderUi.getState().view).toBe('unread')
    // 覆盖后旧键不再触发
    fireEvent(window, new KeyboardEvent('keydown', { key: 'u', bubbles: true }))
    expect(useReaderUi.getState().view).toBe('unread')
    // x 再切回 all
    fireEvent(window, new KeyboardEvent('keydown', { key: 'x', bubbles: true }))
    expect(useReaderUi.getState().view).toBe('all')
  })
})
