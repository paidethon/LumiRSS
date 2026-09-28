/**
 * FIX-295 — 卡片阴影不叠加（BASELINE 守卫）。
 *
 * 契约（tokens.css）：--lumi-shadow-* 仅浮层用（popover / dialog /
 * floating + 最小档 sm）。审计结论（2026-09 R2，web12）：全仓库 33 个
 * 携带阴影的元素逐一核验，全部是 fixed/absolute 定位的独立浮层（弹层、
 * 工具条、toast、chip、灯箱、底部导航）或浮层内的 thumb/选中页签——
 * 不存在「卡片套卡片、同语义阴影叠出深色脏边」的实修点。特记两个级联
 * 收敛点（非叠加）：
 * - MobileTabBar：lumi-glass（unlayered box-shadow）与
 *   shadow-floating 工具类同元素——cascade layers 语义下任一模式只
 *   渲染一条 box-shadow（glass 开 = glass 阴影；glass off = 浮层阴影）；
 * - Tabs 选中页签 shadow-sm / Switch·RecentReads thumb shadow-sm 是
 *   表面内小元素的物理投影语义，非浮层深度语义，允许保留。
 *
 * 守卫方式：钉住「允许携带阴影的文件集合 + 各文件条数」。新增阴影
 * 使用必须显式更新本清单并确认不与宿主阴影同语义嵌套（防止回归为
 * 未审计的 card-in-card 叠影）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const componentsRoot = resolve(__dirname, '../components')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      out.push(...walk(p))
    } else if (name.endsWith('.tsx')) {
      out.push(p)
    }
  }
  return out
}

const SHADOW_CLASS = /shadow-(?:\[var\(--lumi-shadow-[a-z]+\)\]|(?:sm|md|lg|xl)\b)/g

/** 审计过的浮层阴影清单（2026-09 R2）：文件 → 携带阴影的元素条数。 */
const AUDITED_SHADOW_CARRIERS: Record<string, number> = {
  'AgentW5.tsx': 1,
  'AnnotationPopover.tsx': 1,
  'AnnotationsLayer.tsx': 1,
  'ArticleContent.tsx': 2,
  'ArticleFindBar.tsx': 1,
  'ArticleLightbox.tsx': 1,
  'ArticleLinksPanel.tsx': 1,
  'ArticleToc.tsx': 1,
  'CommandPalette.tsx': 1,
  'DictSelectionLayer.tsx': 1,
  'InstallHint.tsx': 1,
  'MatchExplain.tsx': 1,
  'MobileTabBar.tsx': 1,
  'Reader.tsx': 4,
  'ReaderHeader.tsx': 1,
  'ReaderKeyNav.tsx': 1,
  'ReaderPager.tsx': 5,
  'ReaderRemainingTime.tsx': 1,
  'ReadingBreakReminder.tsx': 1,
  'ReadingRuler.tsx': 3,
  'RecentReads.tsx': 1,
  'SearchHitsChip.tsx': 3,
  'SettingsConflictDialog.tsx': 1,
  'SpeechSelectionLayer.tsx': 1,
  'UndoSnackbar.tsx': 1,
  'VersionUpdateToast.tsx': 2,
  'WhatsNewTour.tsx': 1,
  'ui/Dialog.tsx': 1,
  'ui/Menu.tsx': 1,
  'ui/Popover.tsx': 1,
  'ui/Sheet.tsx': 1,
  'ui/Switch.tsx': 1,
  'ui/Tabs.tsx': 1,
}

describe('FIX-295 阴影不叠加（浮层专用契约）', () => {
  it('themes.css 保留「阴影仅浮层用」契约注释', () => {
    const themes = readFileSync(resolve(__dirname, '../styles/themes.css'), 'utf8')
    expect(themes).toMatch(/阴影（仅浮层用/)
  })

  it('携带阴影的文件集合与条数与审计清单一致', () => {
    const actual: Record<string, number> = {}
    for (const file of walk(componentsRoot)) {
      const rel = file.slice(componentsRoot.length + 1)
      const n = [...readFileSync(file, 'utf8').matchAll(SHADOW_CLASS)].length
      if (n > 0) actual[rel] = n
    }
    expect(actual).toEqual(AUDITED_SHADOW_CARRIERS)
  })

  it('UI 弹层原语各只声明一条阴影（无重复包裹层叠影）', () => {
    for (const f of ['ui/Dialog.tsx', 'ui/Sheet.tsx', 'ui/Popover.tsx', 'ui/Menu.tsx']) {
      const src = readFileSync(resolve(componentsRoot, f), 'utf8')
      expect(src.match(SHADOW_CLASS)?.length, f).toBe(1)
    }
  })

  it('非浮层小元素阴影仅限既定 3 处（Tabs 选中页签 + Switch/RecentReads thumb）', () => {
    // Tabs 选中页签引用 --lumi-shadow-sm token（非 shadow-sm 工具类）
    const tabs = readFileSync(resolve(componentsRoot, 'ui/Tabs.tsx'), 'utf8')
    expect(tabs).toContain('data-selected:shadow-[var(--lumi-shadow-sm)]')
    // Switch / RecentReads thumb：物理投影语义的既有小元素
    const switchSrc = readFileSync(resolve(componentsRoot, 'ui/Switch.tsx'), 'utf8')
    expect(switchSrc).toMatch(/bg-white shadow-sm\b/)
    const recent = readFileSync(resolve(componentsRoot, 'RecentReads.tsx'), 'utf8')
    expect(recent).toMatch(/bg-white shadow\b/)
  })
})
