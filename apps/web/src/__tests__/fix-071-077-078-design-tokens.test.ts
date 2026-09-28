/**
 * FIX-071 / FIX-077 / FIX-078 — 设计令牌覆盖审计（source-level 断言）。
 *
 * 背景（审计结论，2026-09 R2）：
 * - 反馈语义（success / warning / danger 淡底）在 30+ 处以 `--lumi-success`
 *   `--lumi-warning` `--lumi-danger-soft` 等名字被引用，但 themes.css 从未
 *   定义它们——每处都靠各自手写的 fallback 兜底，且 fallback 值互不相同
 *   （danger 文本 #dc2626 vs #b3261e vs #b91c1c；warning #d97706 vs #b45309
 *   vs 「降级为 muted 文本」），甚至有无 fallback 的引用直接解析为
 *   transparent/inherit（成功状态圆点不可见）。FIX-077：补齐状态 token 并
 *   统一命名，同语义同一令牌。
 * - 深色主题破坏（FIX-078）：danger 徽标上写死 text-white（深色 danger 是
 *   浅玫瑰底 #d08087，白字对比 ≈1.9:1）；用户气泡写死 `--lumi-on-accent,
 *   #fff`（该变量不存在，深色 accent #8993f5 上白字 ≈2.8:1）。正确做法是
 *   用 themes.css 里已有的 *-contrast token。
 * - 本测试为 source-level 断言（jsdom 无真实级联样式），防止回潮。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const webRoot = resolve(__dirname, '../..')
const srcRoot = resolve(webRoot, 'src')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'generated') continue
      out.push(...walk(p))
    } else if (/\.(ts|tsx|css)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

const sources = walk(srcRoot)

const staticCss = [
  'styles/tokens.css',
  'styles/themes.css',
  'index.css',
]
  .map((f) => readFileSync(resolve(srcRoot, f), 'utf-8'))
  .join('\n')

/** 静态定义在 styles/*.css 与 index.css 里的 token 名。 */
const definedTokens = new Set(
  [...staticCss.matchAll(/(--lumi-[a-z0-9-]+)\s*:/g)].map((m) => m[1]),
)

/**
 * 运行时挂载的 token（store/app-settings.ts applyReaderTypography /
 * applyAccent / App.tsx timeline 宽度），静态 CSS 里没有定义是设计内的。
 * 前缀 --lumi-reader-* 的消费侧一律带 var() fallback（index.css）。
 */
const RUNTIME_TOKENS = new Set(['--lumi-timeline-width'])
function isRuntimeToken(name: string): boolean {
  return name.startsWith('--lumi-reader-') || RUNTIME_TOKENS.has(name)
}

describe('FIX-071: token 覆盖（引用必有定义或运行时挂载）', () => {
  it('app-settings 确实挂载了运行时 allowlist 里的非 reader token', () => {
    const appSettings = readFileSync(
      resolve(srcRoot, 'store/app-settings.ts'),
      'utf-8',
    )
    const app = readFileSync(resolve(srcRoot, 'App.tsx'), 'utf-8')
    expect(app).toContain('--lumi-timeline-width')
    expect(appSettings).toContain("'--lumi-reader-bg-image'")
  })

  it('每个 var(--lumi-*) 引用要么静态定义、要么在运行时 allowlist', () => {
    const dangling = new Map<string, string[]>()
    for (const file of sources) {
      const text = readFileSync(file, 'utf-8')
      for (const m of text.matchAll(/var\((--lumi-[a-z0-9-]+)/g)) {
        const name = m[1]
        if (definedTokens.has(name) || isRuntimeToken(name)) continue
        const rel = relative(srcRoot, file)
        const list = dangling.get(name) ?? []
        list.push(rel)
        dangling.set(name, list)
      }
    }
    expect(
      [...dangling.entries()].map(([name, files]) => `${name}: ${files.join(', ')}`),
    ).toEqual([])
  })
})

describe('FIX-077: 反馈状态语义统一（success / warning / danger）', () => {
  const themesCss = readFileSync(resolve(srcRoot, 'styles/themes.css'), 'utf-8')
  const darkIdx = themesCss.indexOf("[data-theme='dark']")
  expect(darkIdx).toBeGreaterThan(0)
  const lightBlock = themesCss.slice(0, darkIdx)
  const darkBlock = themesCss.slice(darkIdx)

  it.each(['--lumi-success', '--lumi-success-soft', '--lumi-warning', '--lumi-danger-soft'])(
    '%s 在 Light 与 Dark 两个主题块中都有定义',
    (token) => {
      expect(lightBlock).toContain(`${token}:`)
      expect(darkBlock).toContain(`${token}:`)
    },
  )

  it('不允许再发明 danger 别名（--lumi-danger-text / --lumi-text-danger）', () => {
    const offenders = sources
      .filter((f) => /--lumi-danger-text|--lumi-text-danger/.test(readFileSync(f, 'utf-8')))
      .map((f) => relative(srcRoot, f))
    expect(offenders).toEqual([])
  })

  it('反馈色硬编码字面量只允许出现在记录在案的色板文件', () => {
    // 这些是「数据色板」而非 UI 反馈 chrome：
    // - AppearanceControls：shiki 代码主题预览 swatch（内容数据）
    // - GraphPage：cytoscape 节点/边可视化配色（数据可视化）
    // - lib/reader-style.ts：Reader 纸张/高亮预设（独立阅读主题，设计如此）
    // - AnnotationsManager：批注高亮色板常量（red: '#dc2626' 属高亮笔
    //   色板，同 AnnotationsLayer / SearchTimelinePanel 家族——非错误反馈）
    const ALLOWLIST = new Set([
      'components/settings/AppearanceControls.tsx',
      'components/pages/GraphPage.tsx',
      'lib/reader-style.ts',
      'components/AnnotationsManager.tsx',
    ])
    const FEEDBACK_LITERALS =
      /#dc2626|#b3261e|#b91c1c|#d97706|#b45309|rgba\(220,\s*38,\s*38|rgba\(22,\s*163,\s*74|rgba\(220,\s*80,\s*80/i
    const offenders: string[] = []
    for (const file of sources) {
      const rel = relative(srcRoot, file)
      if (ALLOWLIST.has(rel)) continue
      // token 定义文件正是字面量应当存在的地方，不在扫描范围
      if (rel.startsWith('styles/') || rel === 'index.css') continue
      if (FEEDBACK_LITERALS.test(readFileSync(file, 'utf-8'))) offenders.push(rel)
    }
    expect(offenders).toEqual([])
  })
})

describe('FIX-078: 深色主题色彩泄漏', () => {
  it('danger 徽标前景用 --lumi-danger-contrast，不再写死 text-white', () => {
    for (const rel of [
      'components/MediaFailuresPanel.tsx',
      'components/settings/RecentLoginsPanel.tsx',
    ]) {
      const text = readFileSync(resolve(srcRoot, rel), 'utf-8')
      expect(text, rel).toContain('var(--lumi-danger-contrast)')
      expect(text, rel).not.toMatch(/text-white\b/)
    }
  })

  it('accent 底上的前景用 --lumi-accent-contrast（--lumi-on-accent 别名废除）', () => {
    const offenders = sources
      .filter((f) => /--lumi-on-accent/.test(readFileSync(f, 'utf-8')))
      .map((f) => relative(srcRoot, f))
    expect(offenders).toEqual([])
  })

  it('被引用却从未定义的装饰 token 已补齐（shadow-sm / font-default）', () => {
    expect(definedTokens.has('--lumi-shadow-sm')).toBe(true)
    expect(definedTokens.has('--lumi-font-default')).toBe(true)
  })
})
