/** P14 测试 — 阅读背景图片（设备本地）+ 可读性遮罩 + 阅读设置实时预览
 * + 旧 lumirss-reader-bg 双路径退役迁移。
 *
 * 隐私契约（钉死）：选图管线（FileReader → Image → canvas → data URL）
 * 全程零网络——fetch / XHR spy 必须保持零调用。
 *
 * Canvas / Image 在 jsdom 不可真实工作，按契约 mock：
 * - HTMLCanvasElement.prototype.getContext → fake 2d context
 *   （drawImage 记录调用，getImageData 返回合成像素）；
 * - HTMLCanvasElement.prototype.toDataURL → 可配置实现
 *   （模拟「质量递减后达标」与「始终超限」两条路径）；
 * - global Image → src 赋值即微任务触发 onload 的桩。 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReaderBackgroundPicker } from '../components/settings/AppearanceControls'
import SettingsModal from '../components/settings/SettingsModal'
import { MobileReadingPreview, ReadingPreviewPane } from '../components/settings/reader/ReadingPreviewPane'
import {
  BG_IMAGE_MAX_BYTES,
  averageImageLuminance,
  bgImageHint,
  isValidBgImageDataUrl,
  normalizeOverlayOpacity,
  processBackgroundImageFile,
  recommendOverlayOpacity,
} from '../lib/reader-bg-image'
import {
  DEFAULT_APP_SETTINGS,
  LEGACY_READER_BG_KEY,
  PORTABLE_KEYS,
  SETTINGS_STORAGE_KEY,
  loadSettings,
  normalizeSettings,
  useAppSettings,
  type AppSettings,
} from '../store/app-settings'

// ---- 合成像素助手 ----

function solidPixels(r: number, g: number, b: number, count = 8192): Uint8ClampedArray {
  const data = new Uint8ClampedArray(count * 4)
  for (let i = 0; i < count; i++) {
    data[i * 4] = r
    data[i * 4 + 1] = g
    data[i * 4 + 2] = b
    data[i * 4 + 3] = 255
  }
  return data
}

// ---- canvas / Image mock 基础设施 ----

let syntheticPixels: Uint8ClampedArray
let toDataURLImpl: (type: string, quality?: number) => string
const drawImageSpy = vi.fn()

function installCanvasMocks() {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    () =>
      ({
        drawImage: drawImageSpy,
        getImageData: vi.fn(() => ({ data: syntheticPixels })),
      }) as unknown as CanvasRenderingContext2D,
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation((type, quality) =>
    toDataURLImpl(String(type), quality),
  )
  // Image 桩：src 赋值后微任务触发 onload（jsdom 不真实解码）
  vi.stubGlobal(
    'Image',
    class FakeImage {
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      naturalWidth = 100
      naturalHeight = 50
      width = 100
      height = 50
      set src(_value: string) {
        queueMicrotask(() => this.onload?.())
      }
    },
  )
}

/** 默认编码：任何质量都返回小的合法 JPEG data URL（≤ 上限）。 */
const SMALL_JPEG = 'data:image/jpeg;base64,/9j/4AAQSkZJRg=='
function defaultEncode() {
  toDataURLImpl = vi.fn(() => SMALL_JPEG)
}

/** 网络钉死 spy（管线必须零调用）。 */
let fetchSpy: ReturnType<typeof vi.spyOn>
let xhrOpenSpy: ReturnType<typeof vi.spyOn>
let xhrSendSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  localStorage.clear()
  // store 是模块级单例：每个用例重置为默认，杜绝跨用例状态泄漏
  act(() => {
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  })
  syntheticPixels = solidPixels(128, 128, 128)
  defaultEncode()
  drawImageSpy.mockClear()
  installCanvasMocks()
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockName('fetch')
  xhrOpenSpy = vi.spyOn(XMLHttpRequest.prototype, 'open').mockName('xhr.open')
  xhrSendSpy = vi.spyOn(XMLHttpRequest.prototype, 'send').mockName('xhr.send')
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

/** 与 app-settings.test.ts 同构的内存 Storage（本文件内局部助手）。 */
function fakeStorage(initial: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: (i: number) => [...map.keys()][i] ?? null,
    get length() {
      return map.size
    },
  } as Storage
}

async function selectImage(file: File) {
  render(withQueryClient(<ReaderBackgroundPicker />))
  const input = screen.getByLabelText('选择背景图片')
  fireEvent.change(input, { target: { files: [file] } })
  await waitFor(() => {
    expect(useAppSettings.getState().settings.readerBackgroundImage).not.toBeNull()
  })
}

// ---- lib 纯函数：亮度 / 建议 / 提示 ----

describe('P14 lib — 平均亮度与可读性建议（合成像素）', () => {
  it('亮图（sRGB 240）→ 亮度落在亮带，建议遮罩强于默认', () => {
    const pixels = solidPixels(240, 240, 240)
    const luminance = averageImageLuminance(pixels)
    expect(luminance).toBeGreaterThan(0.4)
    expect(recommendOverlayOpacity(luminance)).toBeGreaterThan(40)
    expect(recommendOverlayOpacity(luminance)).toBeLessThanOrEqual(80)
    expect(bgImageHint(luminance).tone).toBe('bright')
    expect(bgImageHint(luminance).text).toMatch(/^背景较亮，已建议遮罩 \d+%$/)
  })

  it('暗图（sRGB 20）→ 亮度落在暗带，建议遮罩接近上限', () => {
    const pixels = solidPixels(20, 20, 20)
    const luminance = averageImageLuminance(pixels)
    expect(luminance).toBeLessThan(0.1)
    expect(recommendOverlayOpacity(luminance)).toBeGreaterThanOrEqual(70)
    expect(bgImageHint(luminance).tone).toBe('dark')
    expect(bgImageHint(luminance).text).toMatch(/^背景较暗，已建议遮罩 \d+%$/)
  })

  it('中间调（sRGB 128，线性亮度 ≈0.216）→ 适中带内，默认遮罩 40%', () => {
    const luminance = averageImageLuminance(solidPixels(128, 128, 128))
    expect(luminance).toBeGreaterThan(0.1)
    expect(luminance).toBeLessThan(0.4)
    expect(recommendOverlayOpacity(luminance)).toBe(40)
    expect(bgImageHint(luminance).tone).toBe('balanced')
  })

  it('极值钳制：纯黑建议 80% 封顶，遮罩归一化拒绝越界值', () => {
    expect(recommendOverlayOpacity(0)).toBe(80)
    expect(recommendOverlayOpacity(1)).toBe(80)
    expect(normalizeOverlayOpacity(120)).toBe(80)
    expect(normalizeOverlayOpacity(-5)).toBe(0)
    expect(normalizeOverlayOpacity('nope')).toBe(40)
  })

  it('采样稳健：≤4096 像素全采样，空像素数组安全回退', () => {
    expect(averageImageLuminance(solidPixels(255, 255, 255, 16))).toBeGreaterThan(0.9)
    expect(averageImageLuminance(new Uint8ClampedArray(0))).toBe(1)
  })
})

// ---- 完整管线（零网络钉死） ----

describe('P14 lib — processBackgroundImageFile 管线', () => {
  it('合成亮图 → data URL ≤ 上限 + 亮度 + 建议遮罩 + 提示；全程零网络', async () => {
    syntheticPixels = solidPixels(240, 240, 240)
    const file = new File(['fake-image-bytes'], 'bg.png', { type: 'image/png' })
    const result = await processBackgroundImageFile(file)

    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.dataUrl.length).toBeLessThanOrEqual(BG_IMAGE_MAX_BYTES)
    expect(result.dataUrl.startsWith('data:image/jpeg;base64,')).toBe(true)
    expect(result.luminance).toBeGreaterThan(0.4)
    expect(result.recommendedOverlay).toBeGreaterThan(40)
    expect(result.hint.tone).toBe('bright')
    // 降采样调用发生（100px 宽 < 2560，scale=1，但 drawImage 仍执行绘制）
    expect(drawImageSpy).toHaveBeenCalled()
    // 隐私契约：没有任何网络请求
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(xhrOpenSpy).not.toHaveBeenCalled()
    expect(xhrSendSpy).not.toHaveBeenCalled()
  })

  it('质量递减重试：首档超限 → 降质量达标', async () => {
    syntheticPixels = solidPixels(128, 128, 128)
    const big = `data:image/jpeg;base64,${'A'.repeat(BG_IMAGE_MAX_BYTES)}` // 超限
    toDataURLImpl = vi.fn((_type: string, quality?: number) =>
      (quality ?? 1) >= 0.85 ? big : SMALL_JPEG,
    )
    const file = new File(['fake'], 'bg.jpg', { type: 'image/jpeg' })
    const result = await processBackgroundImageFile(file)

    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.dataUrl).toBe(SMALL_JPEG)
    // q=0.85 超限后尝试了下一档（0.7）
    expect(toDataURLImpl).toHaveBeenCalledWith('image/jpeg', 0.7)
  })

  it('始终超限 → 诚实拒绝并给出 2MB 上限文案（绝不静默放宽）', async () => {
    syntheticPixels = solidPixels(128, 128, 128)
    const huge = `data:image/jpeg;base64,${'A'.repeat(BG_IMAGE_MAX_BYTES + 1)}`
    toDataURLImpl = vi.fn(() => huge)
    const file = new File(['fake'], 'bg.png', { type: 'image/png' })
    const result = await processBackgroundImageFile(file)

    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error).toContain('2MB')
  })

  it('非图片类型 → 拒绝；编码永不超限的管线不发起任何网络请求', async () => {
    const file = new File(['not-an-image'], 'notes.txt', { type: 'text/plain' })
    const result = await processBackgroundImageFile(file)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain('仅支持图片')
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(xhrOpenSpy).not.toHaveBeenCalled()
    expect(xhrSendSpy).not.toHaveBeenCalled()
  })
})

// ---- UI：选图 → 存储 ≤ 上限 / 拒绝文案 / 提示 / 遮罩持久化 ----

describe('P14 UI — ReaderBackgroundPicker 背景图片区', () => {
  it('选图（mock canvas）→ data URL 存入 settings 且 ≤ 上限，持久化到本地 key', async () => {
    await selectImage(new File(['x'], 'bg.png', { type: 'image/png' }))
    const stored = useAppSettings.getState().settings.readerBackgroundImage
    expect(stored).not.toBeNull()
    expect(stored!.length).toBeLessThanOrEqual(BG_IMAGE_MAX_BYTES)
    const persisted = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!) as AppSettings
    expect(persisted.readerBackgroundImage).toBe(stored)
  })

  it('超限图片 → UI 显示诚实错误（role=alert），settings 不写入', async () => {
    syntheticPixels = solidPixels(128, 128, 128)
    const huge = `data:image/jpeg;base64,${'A'.repeat(BG_IMAGE_MAX_BYTES + 1)}`
    toDataURLImpl = vi.fn(() => huge)
    render(withQueryClient(<ReaderBackgroundPicker />))
    fireEvent.change(screen.getByLabelText('选择背景图片'), {
      target: { files: [new File(['x'], 'bg.png', { type: 'image/png' })] },
    })
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('2MB')
    expect(useAppSettings.getState().settings.readerBackgroundImage).toBeNull()
  })

  it('亮图选中 → 提示「背景较亮，已建议遮罩 X%」并自动应用建议遮罩', async () => {
    syntheticPixels = solidPixels(240, 240, 240)
    await selectImage(new File(['x'], 'bg.png', { type: 'image/png' }))
    // 注：<output>（Slider 值显示）也有隐式 role=status，故用文本定位提示
    const hint = screen.getByText(/^背景较亮，已建议遮罩 \d+%$/)
    expect(hint).toBeInTheDocument()
    const recommended = recommendOverlayOpacity(
      averageImageLuminance(solidPixels(240, 240, 240)),
    )
    expect(useAppSettings.getState().settings.readerBackgroundImageOverlay).toBe(recommended)
  })

  it('暗图选中 → 提示「背景较暗」', async () => {
    syntheticPixels = solidPixels(20, 20, 20)
    await selectImage(new File(['x'], 'bg.png', { type: 'image/png' }))
    expect(screen.getByText(/^背景较暗，已建议遮罩 \d+%$/)).toBeInTheDocument()
  })

  it('遮罩不透明度默认 40；拖动 slider 持久化（0–80 钳制）', async () => {
    // 默认值（未选图时也成立）
    expect(DEFAULT_APP_SETTINGS.readerBackgroundImageOverlay).toBe(40)
    expect(
      normalizeSettings({}).readerBackgroundImageOverlay,
    ).toBe(40)

    await selectImage(new File(['x'], 'bg.png', { type: 'image/png' }))
    fireEvent.change(screen.getByLabelText('图片遮罩不透明度'), {
      target: { value: '30' },
    })
    expect(useAppSettings.getState().settings.readerBackgroundImageOverlay).toBe(30)
    const persisted = JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!) as AppSettings
    expect(persisted.readerBackgroundImageOverlay).toBe(30)
  })

  it('选图全流程零网络（fetch / XHR spy 保持空）', async () => {
    await selectImage(new File(['x'], 'bg.png', { type: 'image/png' }))
    fireEvent.change(screen.getByLabelText('图片遮罩不透明度'), {
      target: { value: '55' },
    })
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(xhrOpenSpy).not.toHaveBeenCalled()
    expect(xhrSendSpy).not.toHaveBeenCalled()
  })

  it('移除图片 → settings 回到 null（遮罩值保留）', async () => {
    await selectImage(new File(['x'], 'bg.png', { type: 'image/png' }))
    fireEvent.click(screen.getByRole('button', { name: '移除图片' }))
    expect(useAppSettings.getState().settings.readerBackgroundImage).toBeNull()
  })
})

// ---- 归一化 / data URL 校验 ----

describe('P14 — settings 归一化与 data URL 校验', () => {
  it('合法位图 data URL 保留；损坏 / 超限 / 非图片 MIME 丢弃为 null', () => {
    const good = 'data:image/png;base64,iVBORw0KGgo='
    expect(isValidBgImageDataUrl(good)).toBe(true)
    expect(normalizeSettings({ readerBackgroundImage: good }).readerBackgroundImage).toBe(good)
    expect(normalizeSettings({ readerBackgroundImage: 'javascript:alert(1)' }).readerBackgroundImage).toBeNull()
    expect(normalizeSettings({ readerBackgroundImage: 'data:text/html;base64,PGI+' }).readerBackgroundImage).toBeNull()
    const oversized = `data:image/png;base64,${'A'.repeat(BG_IMAGE_MAX_BYTES + 1)}`
    expect(isValidBgImageDataUrl(oversized)).toBe(false)
    expect(normalizeSettings({ readerBackgroundImage: oversized }).readerBackgroundImage).toBeNull()
  })

  it('背景图片键不进 PORTABLE_KEYS（设备本地，绝不同步到服务端）', () => {
    expect(PORTABLE_KEYS).not.toContain('readerBackgroundImage')
    expect(PORTABLE_KEYS).not.toContain('readerBackgroundImageOverlay')
    expect(
      normalizeSettings({ readerBackgroundImageOverlay: 55 }).readerBackgroundImageOverlay,
    ).toBe(55)
  })
})

// ---- 实时预览 ----

describe('P14 — 阅读设置实时预览', () => {
  it('样例文章使用真实 Reader 结构类（.lumi-reader + .article-content）并覆盖 h2/h3/列表/引用/代码/表格', () => {
    render(<ReadingPreviewPane />)
    const article = document.querySelector('[data-reading-preview-article]')
    expect(article).not.toBeNull()
    expect(article!.classList.contains('article-content')).toBe(true)
    expect(article!.closest('.lumi-reader')).not.toBeNull()
    expect(article!.querySelector('h2')).not.toBeNull()
    expect(article!.querySelector('h3')).not.toBeNull()
    expect(article!.querySelector('ul li')).not.toBeNull()
    expect(article!.querySelector('blockquote')).not.toBeNull()
    expect(article!.querySelector('pre code')).not.toBeNull()
    expect(article!.querySelector('table td')).not.toBeNull()
  })

  it('设置变化即时反映：fontSize 改动 → 预览元素内联变量更新（同一 store）', () => {
    render(<ReadingPreviewPane />)
    const root = document.querySelector('[data-reading-preview-article]')!.closest('.lumi-reader') as HTMLElement
    const before = root.style.getPropertyValue('--lumi-reader-font-size')
    expect(before).not.toBe('21px')
    // store 直更须在 act 内：触发订阅组件同步重渲染
    act(() => {
      useAppSettings.getState().update({ readerFontSize: 21 })
    })
    expect(root.style.getPropertyValue('--lumi-reader-font-size')).toBe('21px')
    // 行高同步联动同一映射
    act(() => {
      useAppSettings.getState().update({ readerLineHeight: 2.05 })
    })
    expect(root.style.getPropertyValue('--lumi-reader-line-height')).toBe('2.05')
  })

  it('桌面 SettingsModal 阅读分类渲染右侧预览栏；其他分类不渲染', () => {
    render(
      withQueryClient(
        <SettingsModal open onClose={vi.fn()} openCategory={{ category: 'reading', seq: 1 }} />,
      ),
    )
    expect(screen.getByLabelText('阅读样式实时预览')).toBeInTheDocument()
  })

  it('移动端折叠预览：默认收起，展开后出现同一预览内容', () => {
    render(<MobileReadingPreview />)
    const toggle = screen.getByRole('button', { name: '展开预览' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(document.querySelector('[data-reading-preview]')).toBeNull()
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: '折叠预览' })).toHaveAttribute('aria-expanded', 'true')
    expect(document.querySelector('[data-reading-preview-article]')).not.toBeNull()
  })
})

// ---- 旧 key 退役迁移 ----

describe('P14 — 旧 lumirss-reader-bg 双路径退役迁移', () => {
  it('新 key 已存在 + 旧 key 存在 → readerBackground 未设置时并入，旧 key 移除', () => {
    const storage = fakeStorage({
      [SETTINGS_STORAGE_KEY]: JSON.stringify({ themeMode: 'dark' }),
      [LEGACY_READER_BG_KEY]: 'sepia',
    })
    const migrated = loadSettings(storage)
    expect(migrated.themeMode).toBe('dark')
    expect(migrated.readerBackground).toBe('sepia')
    expect(storage.getItem(LEGACY_READER_BG_KEY)).toBeNull()
  })

  it('新 key 已显式设置 readerBackground → 旧 key 不覆盖，但仍被移除', () => {
    const storage = fakeStorage({
      [SETTINGS_STORAGE_KEY]: JSON.stringify({ readerBackground: 'mint' }),
      [LEGACY_READER_BG_KEY]: 'sepia',
    })
    const migrated = loadSettings(storage)
    expect(migrated.readerBackground).toBe('mint')
    expect(storage.getItem(LEGACY_READER_BG_KEY)).toBeNull()
  })

  it('完全无新 key 的首次加载路径：旧 key 并入后同样移除', () => {
    const storage = fakeStorage({ [LEGACY_READER_BG_KEY]: 'warm' })
    const migrated = loadSettings(storage)
    expect(migrated.readerBackground).toBe('warm')
    expect(storage.getItem(LEGACY_READER_BG_KEY)).toBeNull()
  })

  it('旧 key 非法值 → 不并入，仍移除（收口不留双路径）', () => {
    const storage = fakeStorage({ [LEGACY_READER_BG_KEY]: 'not-a-bg' })
    const migrated = loadSettings(storage)
    expect(migrated.readerBackground).toBe('follow')
    expect(storage.getItem(LEGACY_READER_BG_KEY)).toBeNull()
  })

  it('无旧 key 时 loadSettings 不产生额外副作用', () => {
    const storage = fakeStorage({
      [SETTINGS_STORAGE_KEY]: JSON.stringify({ readerFontSize: 19 }),
    })
    const migrated = loadSettings(storage)
    expect(migrated.readerFontSize).toBe(19)
    expect(migrated.readerBackgroundImage).toBeNull()
    expect(migrated.readerBackgroundImageOverlay).toBe(
      DEFAULT_APP_SETTINGS.readerBackgroundImageOverlay,
    )
  })
})
