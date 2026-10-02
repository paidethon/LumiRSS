/** R14 设置文案测试 — 三遍精简的规则式守护。
 *
 * 1) 标签长度约束：16 个分类全部声明式条目（title/select/toggle/action）
 *    的标签按规则式断言——汉字数 2–8（规则：标签 2–8 汉字；纯缩写如
 *    「API 来源」按汉字计）。
 * 2) 渲染输出卫生：走遍 16 个分类（真实错误态/空态渲染），断言用户可见
 *    文本不含开发编号（NEW-xxx / FIX-xxx）与历史名 GPT（CONTRACT §0：
 *    开发编号不进用户可见 UI；日报统一「AI 日报」措辞）。
 */

import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsModal from '../components/settings/SettingsModal'
import { CATEGORIES, useCategoryItems, type CategoryId } from '../components/settings/categories'
import { useAppSettings } from '../store/app-settings'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

/** renderHook 专用 wrapper（接收 children 的标准组件形态）。 */
function HookWrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

/** 规则式计数：只数汉字（CJK 统一表意文字），缩写/数字不计入。 */
function hanziCount(text: string): number {
  return (text.match(/[\u4e00-\u9fff]/g) ?? []).length
}

describe('R14 — 设置条目标签长度规则（2–8 汉字）', () => {
  it.each(CATEGORIES.map((c) => [c.id, c.label] as const))(
    '分类「%s」全部条目标签合规',
    (id) => {
      const { result } = renderHook(() => useCategoryItems(id as CategoryId), {
        wrapper: HookWrapper,
      })
      expect(result.current.length).toBeGreaterThan(0)
      for (const item of result.current) {
        if (item.type === 'custom') continue
        const label = item.type === 'title' ? item.value : item.label
        // 规则式：标签汉字数在 2–8 之间（不硬编码具体文案，防止漂移复发）
        expect(hanziCount(label)).toBeGreaterThanOrEqual(2)
        expect(hanziCount(label)).toBeLessThanOrEqual(8)
        if (item.type !== 'title' && item.description !== undefined) {
          // 帮助文案不携带开发编号（NEW-xxx / FIX-xxx / GPT）
          expect(item.description).not.toMatch(/NEW-\d|FIX-\d|GPT/i)
        }
      }
    },
  )

  it('左侧导航分类标签 ≤ 8 字（含缩写）', () => {
    for (const category of CATEGORIES) {
      expect(category.label.length).toBeLessThanOrEqual(8)
    }
  })
})

describe('R14 — 设置渲染输出无开发编号 / GPT 字样', () => {
  beforeEach(() => {
    localStorage.clear()
    useAppSettings.getState().reset()
    // 全部网络请求按离线拒绝：走真实 loading → error 态渲染路径。
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('network unavailable (r14 copy scan)')
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAppSettings.getState().reset()
    localStorage.clear()
  })

  it('走遍 16 个分类，用户可见文本无 NEW-xxx / FIX-xxx / GPT', async () => {
    render(withQueryClient(<SettingsModal open onClose={vi.fn()} />))

    const seen: string[] = []
    for (const category of CATEGORIES) {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${category.label}$`) }))
      await waitFor(() => {
        expect(screen.getByRole('heading', { level: 2, name: category.label })).toBeInTheDocument()
      })
      // 等待该分类的异步错误/空态落定（fetch 全拒，重试已关）
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 200))
      })
      seen.push(document.body.textContent ?? '')
    }

    expect(seen).toHaveLength(CATEGORIES.length)
    for (const text of seen) {
      expect(text).not.toMatch(/NEW-\d/)
      expect(text).not.toMatch(/FIX-\d/)
      expect(text).not.toMatch(/GPT/i)
    }
  })
})
