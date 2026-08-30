/** theme-pack 测试 — 0012 Gate 6（AC9/AC10/AC11）。 */

import { describe, expect, it } from 'vitest'
import {
  exportThemePack,
  parseThemePack,
  previewThemePack,
  serializeThemePack,
  themePackToPatch,
  ThemePackError,
} from '../lib/theme-pack'
import { DEFAULT_APP_SETTINGS } from '../store/app-settings'

function settingsWith(overrides: Record<string, unknown>): typeof DEFAULT_APP_SETTINGS {
  return { ...DEFAULT_APP_SETTINGS, ...overrides } as typeof DEFAULT_APP_SETTINGS
}

describe('exportThemePack — 导出', () => {
  it('只导出 reader 白名单字段 + customCss，绝不含 secret/布局/账号', () => {
    const settings = settingsWith({
      readerFontSize: 19,
      readerTextIndent: '2em',
      readerChineseConversion: 'tw',
      customCss: 'p { margin: 1em; }',
      // 以下字段绝不允许出现在主题包里
      accentColor: '#ff0000',
      sidebarWidth: 300,
      translationSettings: undefined,
    })
    const pack = exportThemePack(settings, { name: '测试主题' })
    const keys = Object.keys(pack.reader)
    expect(keys).toContain('readerFontSize')
    expect(keys).toContain('readerTextIndent')
    expect(keys).not.toContain('accentColor')
    expect(keys).not.toContain('sidebarWidth')
    expect(keys).not.toContain('translationSettings')
    expect(keys).not.toContain('filterRules')
    expect(keys).not.toContain('rsshubSettings')
    expect((pack as unknown as Record<string, unknown>).accentColor).toBeUndefined()
    expect(pack.customCss).toBe('p { margin: 1em; }')
    expect(pack.metadata.name).toBe('测试主题')
    expect(pack.type).toBe('reader-theme')
    expect(pack.appName).toBe('LumiRSS')
    expect(pack.schemaVersion).toBe(1)
  })

  it('metadata 超长截断', () => {
    const pack = exportThemePack(DEFAULT_APP_SETTINGS, { name: 'x'.repeat(200) })
    expect(pack.metadata.name.length).toBe(64)
  })
})

describe('parseThemePack — 导入校验', () => {
  it('合法包 → 保留合法字段', () => {
    const pack = exportThemePack(settingsWith({ readerFontSize: 21, readerTextIndent: '2em' }))
    const parsed = parseThemePack(serializeThemePack(pack))
    expect(parsed.reader.readerFontSize).toBe(21)
    expect(parsed.reader.readerTextIndent).toBe('2em')
    expect(parsed.metadata.name).toBe(pack.metadata.name)
  })

  it('export → import → export 语义 round-trip', () => {
    const settings = settingsWith({
      readerFontFamily: 'serif',
      readerFontSize: 19,
      readerLineHeight: 2.05,
      readerBackground: 'sepia',
      readerJustify: true,
      readerTextIndent: '2em',
      readerChineseConversion: 's2t',
      customCss: 'img { border-radius: 6px; }',
    })
    const first = exportThemePack(settings, { name: 'RT', description: 'd' })
    const parsed = parseThemePack(serializeThemePack(first))
    const reExported = exportThemePack(
      settingsWith({ ...parsed.reader, customCss: parsed.customCss } as Record<string, unknown>),
      parsed.metadata,
    )
    // reader 段与 customCss 语义一致（createdAt 会更新，不比对）
    expect(reExported.reader).toEqual(first.reader)
    expect(reExported.customCss).toBe(first.customCss)
    expect(reExported.metadata.name).toBe('RT')
  })

  it('非法 JSON → not-json', () => {
    expect(() => parseThemePack('{broken')).toThrow(ThemePackError)
    try {
      parseThemePack('{broken')
    } catch (e) {
      expect((e as ThemePackError).code).toBe('not-json')
    }
  })

  it('信封错误 → bad-envelope', () => {
    expect(() => parseThemePack('{"type":"other"}')).toThrow(ThemePackError)
    expect(() => parseThemePack('{"type":"reader-theme","appName":"Other"}')).toThrow(
      ThemePackError,
    )
    expect(() => parseThemePack('"just a string"')).toThrow(ThemePackError)
  })

  it('版本不支持 → unsupported-version', () => {
    const pack = exportThemePack(DEFAULT_APP_SETTINGS)
    const raw = JSON.parse(serializeThemePack(pack))
    raw.schemaVersion = 99
    expect(() => parseThemePack(JSON.stringify(raw))).toThrow(ThemePackError)
  })

  it('reader 段为空 → empty-reader', () => {
    expect(() =>
      parseThemePack(
        JSON.stringify({
          schemaVersion: 1,
          appName: 'LumiRSS',
          type: 'reader-theme',
          metadata: { name: 'x' },
          reader: {},
          customCss: '',
        }),
      ),
    ).toThrow(ThemePackError)
  })

  it('恶意/非法 reader 字段值 → normalize 回退默认（不崩溃）', () => {
    const raw = JSON.stringify({
      schemaVersion: 1,
      appName: 'LumiRSS',
      type: 'reader-theme',
      metadata: { name: 'evil' },
      reader: {
        readerFontSize: 'alert(1)',
        readerTextIndent: '99em',
        readerChineseConversion: 'leet',
        evilField: '<script>',
      },
      customCss: '',
    })
    const parsed = parseThemePack(raw)
    expect(parsed.reader.readerFontSize).toBe(17)
    expect(parsed.reader.readerTextIndent).toBe('off')
    expect(parsed.reader.readerChineseConversion).toBe('off')
    expect((parsed.reader as Record<string, unknown>).evilField).toBeUndefined()
  })

  it('customCss 无法解析 → bad-custom-css', () => {
    const raw = JSON.stringify({
      schemaVersion: 1,
      appName: 'LumiRSS',
      type: 'reader-theme',
      metadata: { name: 'x' },
      reader: { readerFontSize: 17 },
      customCss: 'p { broken',
    })
    try {
      parseThemePack(raw)
      expect.unreachable('应抛出')
    } catch (e) {
      expect((e as ThemePackError).code).toBe('bad-custom-css')
    }
  })

  it('metadata 恶意超长 → 截断', () => {
    const raw = JSON.stringify({
      schemaVersion: 1,
      appName: 'LumiRSS',
      type: 'reader-theme',
      metadata: { name: 'x'.repeat(5000), description: 'd'.repeat(5000) },
      reader: { readerFontSize: 17 },
    })
    const parsed = parseThemePack(raw)
    expect(parsed.metadata.name.length).toBeLessThanOrEqual(64)
    expect(parsed.metadata.description.length).toBeLessThanOrEqual(280)
  })

  it('兼容 0010a 旧 reader-presets JSON（AC11）', () => {
    const legacy = JSON.stringify({
      schemaVersion: 1,
      appName: 'LumiRSS',
      type: 'reader-presets',
      presets: [
        {
          id: 'user-abc',
          name: '我的预设',
          builtin: false,
          vars: {
            readerFontFamily: 'serif',
            readerFontSize: 19,
            readerLineHeight: 2.05,
            readerBackground: 'sepia',
            readerParagraphSpacing: 'loose',
            readerJustify: true,
          },
        },
      ],
    })
    const parsed = parseThemePack(legacy)
    expect(parsed.reader.readerFontFamily).toBe('serif')
    expect(parsed.reader.readerFontSize).toBe(19)
    expect(parsed.reader.readerBackground).toBe('sepia')
  })
})

describe('themePackToPatch — 应用', () => {
  it('patch 只含 reader 字段 + customCss', () => {
    const pack = exportThemePack(settingsWith({ readerFontSize: 21, customCss: 'a{}' }))
    const patch = themePackToPatch(pack)
    expect(patch.readerFontSize).toBe(21)
    expect(patch.customCss).toBe('a{}')
    expect(Object.keys(patch).length).toBe(16)
  })
})

describe('previewThemePack — 预览摘要', () => {
  it('显示名称/字体/背景/字号/行高/中文排版/customCss 状态', () => {
    const pack = exportThemePack(
      settingsWith({
        readerFontSize: 19,
        readerTextIndent: '2em',
        readerChineseConversion: 'tw',
        readerBackground: 'sepia',
        customCss: 'p{}',
      }),
      { name: '期刊', description: '描述' },
    )
    const p = previewThemePack(pack)
    expect(p.name).toBe('期刊')
    expect(p.fontSize).toBe(19)
    expect(p.backgroundLabel).toBe('米黄')
    expect(p.chineseConversion).toBe('简 → 台湾正体')
    expect(p.textIndent).toBe('首行缩进 2 字符')
    expect(p.hasCustomCss).toBe(true)
  })

  it('引用本机不存在的自定义字体 → missingFont + 提示回退', () => {
    const pack = exportThemePack(settingsWith({ readerCustomFontId: 'font-abcdef1234567890' }))
    const p = previewThemePack(pack, () => false)
    expect(p.missingFont).toBe(true)
    expect(p.fontFamilyLabel).toContain('缺少')
    // 本机存在 → 不报缺
    const ok = previewThemePack(pack, (id) => id === 'font-abcdef1234567890')
    expect(ok.missingFont).toBe(false)
  })
})
