/** app-settings store 测试 — 0010 Gate A（AC17/V11）。 */

import { describe, expect, it } from 'vitest'
import {
  type AppSettings,
  DEFAULT_APP_SETTINGS,
  SETTINGS_STORAGE_KEY,
  isValidFontUrl,
  loadSettings,
  normalizeSettings,
  persistSettings,
} from '../store/app-settings'

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

describe('normalizeSettings — 不可信输入逐字段归一化', () => {
  it('null / 非对象 → 全默认', () => {
    expect(normalizeSettings(null)).toEqual(DEFAULT_APP_SETTINGS)
    expect(normalizeSettings('garbage')).toEqual(DEFAULT_APP_SETTINGS)
  })

  it('合法值全部保留', () => {
    const valid: AppSettings = {
      ...DEFAULT_APP_SETTINGS,
      themeMode: 'dark',
      readerBackground: 'sepia',
      readerFontSize: 21,
      readerLineHeight: 1.65,
      readerContentWidth: 900,
      sidebarWidth: 300,
      timelineWidth: 460,
    }
    expect(normalizeSettings(valid)).toEqual(valid)
  })

  it('非法枚举回退默认（不抛错）', () => {
    const bad = normalizeSettings({
      language: 'en-US',
      themeMode: 'blue',
      readerBackground: 'not-a-bg',
    })
    expect(bad.language).toBe('zh-CN')
    expect(bad.themeMode).toBe('system')
    expect(bad.readerBackground).toBe('follow')
  })

  it('0017：超范围数值吸附到连续网格并钳制到边界', () => {
    const bad = normalizeSettings({
      readerFontSize: 33, // > max → 28
      readerLineHeight: 9.9, // > max → 2.4
      readerContentWidth: 123, // < min → 560
      readerPageMargin: 1, // < min → 12
      readerParagraphSpacing: 0.44, // snap 到 0.05 网格 → 0.45
    })
    expect(bad.readerFontSize).toBe(28)
    expect(bad.readerLineHeight).toBe(2.4)
    expect(bad.readerContentWidth).toBe(560)
    expect(bad.readerPageMargin).toBe(12)
    expect(bad.readerParagraphSpacing).toBe(0.45)
  })

  it('0017：NaN / Infinity 回退默认', () => {
    const bad = normalizeSettings({ readerFontSize: Number.NaN, readerLineHeight: Infinity })
    expect(bad.readerFontSize).toBe(17)
    expect(bad.readerLineHeight).toBe(1.85)
  })

  it('分栏宽度 clamp 到边界内', () => {
    const clamped = normalizeSettings({ sidebarWidth: 50, timelineWidth: 9999 })
    expect(clamped.sidebarWidth).toBe(220)
    expect(clamped.timelineWidth).toBe(460)
  })

  it('未知字段丢弃', () => {
    const result = normalizeSettings({ ...DEFAULT_APP_SETTINGS, evil: '<script>' })
    expect((result as unknown as Record<string, unknown>).evil).toBeUndefined()
  })
})

describe('normalizeSettings — 0012 新增 Reader 字段', () => {
  it('合法 0012 值全部保留', () => {
    const valid: AppSettings = {
      ...DEFAULT_APP_SETTINGS,
      readerCustomFontId: 'font-0123456789abcdef',
      readerFontUrl: 'https://cdn.example.com/fonts/NotoSerifSC.woff2',
      readerFontUrlName: '思源宋体',
      readerTextIndent: '2em',
      readerHangingPunctuation: true,
      readerChineseConversion: 'tw',
      readerShowReadingTime: true,
      readerCodeHighlight: 'off',
      readerCodeTheme: 'github-dark',
      readerBionic: true,
    }
    expect(normalizeSettings(valid)).toEqual(valid)
  })

  it('非法枚举 / 非法字体引用回退默认', () => {
    const bad = normalizeSettings({
      readerCustomFontId: "'; DROP TABLE",
      readerFontUrl: 'javascript:alert(1)',
      readerTextIndent: '4em',
      readerChineseConversion: 'pinyin',
      readerCodeHighlight: 'always',
      readerCodeTheme: 'evil-theme',
    })
    expect(bad.readerCustomFontId).toBeNull()
    expect(bad.readerFontUrl).toBeNull()
    expect(bad.readerTextIndent).toBe('off')
    expect(bad.readerChineseConversion).toBe('off')
    expect(bad.readerCodeHighlight).toBe('auto')
    expect(bad.readerCodeTheme).toBe('auto')
  })

  it('旧 0010a 设置（无 0012 字段）继续加载 → 0012 字段全部默认', () => {
    // 0010a 时代持久化的 JSON 没有 0012 字段——必须无损加载
    const legacy = normalizeSettings({ themeMode: 'dark', readerFontSize: 19, readerJustify: true })
    expect(legacy.themeMode).toBe('dark')
    expect(legacy.readerFontSize).toBe(19)
    expect(legacy.readerJustify).toBe(true)
    expect(legacy.readerCustomFontId).toBeNull()
    expect(legacy.readerFontUrl).toBeNull()
    expect(legacy.readerTextIndent).toBe('off')
    expect(legacy.readerChineseConversion).toBe('off')
    expect(legacy.readerBionic).toBe(false)
  })

  it('corrupted 0012 字段不致整体失败', () => {
    const bad = normalizeSettings({
      readerCustomFontId: 42,
      readerFontUrl: { evil: true },
      readerHangingPunctuation: 'yes',
    })
    expect(bad.readerCustomFontId).toBeNull()
    expect(bad.readerFontUrl).toBeNull()
    expect(bad.readerHangingPunctuation).toBe(false)
  })
})

describe('isValidFontUrl — 字体 URL 白名单（Gate 3）', () => {
  it('仅接受 http/https 绝对地址', () => {
    expect(isValidFontUrl('https://fonts.example.com/a.woff2')).toBe(true)
    expect(isValidFontUrl('http://192.168.1.10:8000/a.woff2')).toBe(true)
  })

  it('拒绝其它协议 / 相对路径 / 非字符串', () => {
    expect(isValidFontUrl('javascript:alert(1)')).toBe(false)
    expect(isValidFontUrl('data:font/woff2;base64,AAA')).toBe(false)
    expect(isValidFontUrl('file:///etc/passwd')).toBe(false)
    expect(isValidFontUrl('/fonts/a.woff2')).toBe(false)
    expect(isValidFontUrl('fonts/a.woff2')).toBe(false)
    expect(isValidFontUrl('')).toBe(false)
    expect(isValidFontUrl(null)).toBe(false)
    expect(isValidFontUrl(123)).toBe(false)
  })
})

describe('loadSettings — 新 key 读取与旧 key 迁移（V11）', () => {
  it('storage 为 null → 默认', () => {
    expect(loadSettings(null)).toEqual(DEFAULT_APP_SETTINGS)
  })

  it('无任何 key → 默认（不写入）', () => {
    expect(loadSettings(fakeStorage())).toEqual(DEFAULT_APP_SETTINGS)
  })

  it('新 key 存在 → 直接读取（不触发迁移）', () => {
    const s = fakeStorage({
      [SETTINGS_STORAGE_KEY]: JSON.stringify({ themeMode: 'dark', readerFontSize: 19 }),
    })
    expect(loadSettings(s).themeMode).toBe('dark')
    expect(loadSettings(s).readerFontSize).toBe(19)
  })

  it('旧 key 迁移：lumirss-theme + lumirss-reader-bg 并入（AC17）', () => {
    const s = fakeStorage({
      'lumirss-theme': 'dark',
      'lumirss-reader-bg': 'sepia',
    })
    const migrated = loadSettings(s)
    expect(migrated.themeMode).toBe('dark')
    expect(migrated.readerBackground).toBe('sepia')
    // 其余字段保持默认
    expect(migrated.readerFontSize).toBe(DEFAULT_APP_SETTINGS.readerFontSize)
  })

  it('旧 key 非法值 → 忽略迁移', () => {
    const s = fakeStorage({ 'lumirss-theme': 'purple', 'lumirss-reader-bg': 'not-a-bg' })
    expect(loadSettings(s).themeMode).toBe('system')
    expect(loadSettings(s).readerBackground).toBe('follow')
  })

  it('损坏 JSON → 回退默认不抛错', () => {
    const s = fakeStorage({ [SETTINGS_STORAGE_KEY]: '{broken' })
    expect(loadSettings(s)).toEqual(DEFAULT_APP_SETTINGS)
  })
})

describe('0017 连续数值迁移（legacy → numeric）', () => {
  it('旧离散字号/行高/宽度 → 数值不变（identity 映射）', () => {
    const s = normalizeSettings({ readerFontSize: 15, readerLineHeight: 1.65, readerContentWidth: 900 })
    expect(s.readerFontSize).toBe(15)
    expect(s.readerLineHeight).toBe(1.65)
    expect(s.readerContentWidth).toBe(900)
  })

  it('旧段距枚举 → 连续 em 值', () => {
    expect(normalizeSettings({ readerParagraphSpacing: 'compact' }).readerParagraphSpacing).toBe(0.5)
    expect(normalizeSettings({ readerParagraphSpacing: 'normal' }).readerParagraphSpacing).toBe(0.85)
    expect(normalizeSettings({ readerParagraphSpacing: 'loose' }).readerParagraphSpacing).toBe(1.25)
  })

  it('连续值吸附到 step 网格', () => {
    expect(normalizeSettings({ readerLineHeight: 1.86 }).readerLineHeight).toBe(1.85)
    expect(normalizeSettings({ readerContentWidth: 761 }).readerContentWidth).toBe(760)
  })

  it('旧设置对象含 translationSettings 字段 → 安全丢弃（不迁移浏览器端 Key）', () => {
    const legacy = {
      ...DEFAULT_APP_SETTINGS,
      translationSettings: {
        providers: [{ type: 'microsoft', apiKey: 'sk-legacy-secret' }],
      },
    }
    const s = normalizeSettings(legacy)
    expect((s as unknown as Record<string, unknown>).translationSettings).toBeUndefined()
  })
})

describe('persistSettings 往返', () => {
  it('写 → 读完全一致', () => {
    const s = fakeStorage()
    const custom: AppSettings = { ...DEFAULT_APP_SETTINGS, readerFontSize: 21, themeMode: 'light' }
    persistSettings(s, custom)
    expect(loadSettings(s)).toEqual(custom)
  })
})

describe('store update（集成）', () => {
  it('update 局部合并 + 持久化 + 归一化', async () => {
    const { useAppSettings } = await import('../store/app-settings')
    localStorage.clear()
    useAppSettings.getState().update({ readerFontSize: 19 })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(19)
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerFontSize).toBe(19)
    // 非法值经 update 也被归一化：超范围 → 钳制到最大
    useAppSettings.getState().update({ readerFontSize: 99 as never })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(28)
    localStorage.clear()
  })

  it('reset 恢复全部默认', async () => {
    const { useAppSettings } = await import('../store/app-settings')
    localStorage.clear()
    useAppSettings.getState().update({ themeMode: 'dark', dimRead: true })
    useAppSettings.getState().reset()
    expect(useAppSettings.getState().settings).toEqual(DEFAULT_APP_SETTINGS)
    localStorage.clear()
  })
})

describe('0020 Gate 3 — appearance DOM 副作用（accent 对比 + reduce motion）', () => {
  it('亮色自定义 accent → 近黑前景；中/深色 accent → 白前景（可读对比）', async () => {
    const { useAppSettings } = await import('../store/app-settings')
    localStorage.clear()
    const root = document.documentElement
    // 亮黄 accent：白字不可读 → 近黑前景
    useAppSettings.getState().update({ accentColor: '#ffeb3b' })
    expect(root.style.getPropertyValue('--lumi-accent-contrast').trim()).toBe('#1c1c1e')
    // 默认 accent（Lumi Mist #6d78e8，中深）→ 白前景（不回归默认观感）
    useAppSettings.getState().update({ accentColor: '#6d78e8' })
    expect(root.style.getPropertyValue('--lumi-accent-contrast').trim()).toBe('#ffffff')
    // 深色 accent → 白前景
    useAppSettings.getState().update({ accentColor: '#1a1a2e' })
    expect(root.style.getPropertyValue('--lumi-accent-contrast').trim()).toBe('#ffffff')
    useAppSettings.getState().reset()
    localStorage.clear()
  })

  it('reduceMotion 把 data-motion-reduce 挂到 <html>（tokens.css 消费）', async () => {
    const { useAppSettings } = await import('../store/app-settings')
    localStorage.clear()
    const root = document.documentElement
    useAppSettings.getState().update({ reduceMotion: true })
    expect(root.dataset.motionReduce).toBe('true')
    useAppSettings.getState().update({ reduceMotion: false })
    expect(root.dataset.motionReduce).toBeUndefined()
    useAppSettings.getState().reset()
    localStorage.clear()
  })
})
