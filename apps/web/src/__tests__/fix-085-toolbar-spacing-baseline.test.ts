/**
 * FIX-085 — 工具栏横向间距与分组分隔基线守卫（source-level 断言）。
 *
 * 裁决：BASELINE_OK。工具栏间距/分组已收敛为两层惯用法，主次操作
 * 排序有稳定锚点：
 * - 芯片工具行（列表工具行 / 批量操作栏）：flex-wrap items-center +
 *   gap-1.5；与内容区之间用 --lumi-separator 横向分隔（border-b/t）；
 * - 阅读页分段控件组（ReaderHeader role="group" 簇）：组内 gap-0.5 +
 *   p-0.5 + border-[var(--lumi-border)] + radius-md——分组用带边框容器
 *   表达，组间距由外层 gap-1/gap-1.5 承担（不手绘竖分隔线）；
 * - 主/次操作排序：批量栏 = 计数与全选/清除（次）在左，flex-1 弹性
 *   spacer 把主操作（AI 批量入口）稳定推到右端；列表工具行 =
 *   未读 segmented（带边框容器表达分组）在左，flex-1 spacer 后视图
 *   选单与工具按钮右聚（R11 顶栏迁移后的新基线）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const entryList = read('components/EntryList.tsx')
const readerHeader = read('components/ReaderHeader.tsx')

describe('FIX-085: 芯片工具行——统一横向间距与内容区分隔', () => {
  it('列表工具行：flex items-center gap-1.5，border-b separator 与列表分隔', () => {
    expect(entryList).toContain(
      'flex flex-wrap items-center gap-1.5 border-b border-[var(--lumi-separator)] px-4 py-1',
    )
  })

  it('批量操作栏：同 gap-1.5 节奏，border-t separator 贴列表底', () => {
    expect(entryList).toMatch(/role="toolbar"[\s\S]{0,200}border-t border-\[var\(--lumi-separator\)\]/)
    expect(entryList).toMatch(/<div className="flex flex-wrap items-center gap-1\.5">/)
  })
})

describe('FIX-085: 主/次操作稳定排序', () => {
  it('批量栏：计数/全选/清除（次）在左，flex-1 spacer 把主操作推到右端', () => {
    const barStart = entryList.indexOf('data-testid="batch-bar"')
    expect(barStart, '批量操作栏应存在').toBeGreaterThan(-1)
    // 批量栏整体约 6KB JSX；窗口取 12KB 覆盖到主操作按钮为止。
    const bar = entryList.slice(barStart, barStart + 12000)
    const count = bar.indexOf('data-testid="selected-count"')
    const selectAll = bar.indexOf('全选已加载')
    const clear = bar.indexOf('清除', selectAll)
    const spacer = bar.indexOf('<span className="flex-1" />')
    const primary = bar.indexOf('data-testid="ask-batch-open"')
    for (const [label, idx] of [
      ['selected-count（计数）', count],
      ['全选已加载', selectAll],
      ['清除', clear],
      ['flex-1 spacer', spacer],
      ['ask-batch-open（主操作）', primary],
    ] as const) {
      expect(idx, `${label} 应在批量栏窗口内`).toBeGreaterThan(-1)
    }
    expect(count).toBeLessThan(selectAll)
    expect(selectAll).toBeLessThan(clear)
    expect(clear).toBeLessThan(spacer)
    expect(spacer).toBeLessThan(primary)
  })

  it('列表工具行（R11 顶栏）：未读 segmented 左位（带边框分组容器），flex-1 后视图/工具右聚', () => {
    const rowStart = entryList.indexOf('data-testid="list-toolbar"')
    expect(rowStart, '列表顶栏应存在').toBeGreaterThan(-1)
    const row = entryList.slice(rowStart, rowStart + 9000)
    const segmented = row.indexOf('role="group"')
    const spacer = row.indexOf('<span className="flex-1" />')
    const viewMenu = row.indexOf('<Menu')
    const tools = row.indexOf('data-testid="tools-drawer-open"')
    for (const [label, idx] of [
      ['未读 segmented（role=group）', segmented],
      ['flex-1 spacer', spacer],
      ['视图选单', viewMenu],
      ['工具按钮', tools],
    ] as const) {
      expect(idx, `${label} 应在顶栏窗口内`).toBeGreaterThan(-1)
    }
    expect(segmented, 'segmented 应锚在左位').toBeLessThan(spacer)
    expect(spacer).toBeLessThan(viewMenu)
    expect(viewMenu).toBeLessThan(tools)
    // 触控目标：行内控件桌面 32px / 移动 44px（min-h-8 max-lg:min-h-11）
    expect(row).toContain('min-h-8 max-lg:min-h-11')
  })
})

describe('FIX-085: 阅读页分段控件组——组内密度与分组边界', () => {
  it('分段组统一 gap-0.5 + p-0.5 + border + radius-md（带边框容器表达分组）', () => {
    const cluster = readerHeader.match(
      /className=\{?"[^"]*gap-0\.5[^"]*rounded-\[var\(--lumi-radius-md\)\] border border-\[var\(--lumi-border\)\] p-0\.5[^"]*"/g,
    )
    expect(cluster, 'ReaderHeader 分段组数量应 ≥5').not.toBeNull()
    expect(cluster!.length).toBeGreaterThanOrEqual(5)
  })

  it('阅读页工具行：外层 gap-1 lg:gap-1.5（组间距单一来源，随断点升档）', () => {
    expect(readerHeader).toContain('mt-4 flex flex-wrap items-center gap-1 lg:gap-1.5')
  })
})
