/**
 * FIX-296 — 可变内容对话框滚动条出现时内容不横跳。
 *
 * 背景：内容区自身滚动（overflow-y-auto）的浮层，内容高度在打开后
 * 变化（表单折叠/展开、命令面板输入过滤、AI 消息追加、列表异步加载）
 * 时滚动条出现/消失，可用宽度随之 ±滚动条宽，内容整体横跳。
 *
 * 修复：给这些滚动容器加 `scrollbar-gutter: stable`（Tailwind 任意
 * 属性 `[scrollbar-gutter:stable]`；v4 无内置工具类）——gutter 恒定
 * 预留，出现滚动条只是占用已预留的空间，布局不位移。自定义滚动条为
 * 6px（tokens.css），预留成本即 6px 空白条。
 *
 * 覆盖（审计「打开后内容高度会变的滚动容器」）：
 * - ui/Dialog 内容区（全部表单对话框共用原语）；
 * - CommandPalette 命令列表（输入过滤，行数随查询变化）；
 * - ArticleConversation 消息区（对话持续追加）；
 * - RecentReads 列表（异步加载，空→有内容）。
 * SettingsConflictDialog 的列表内容静态（打开后高度不变）→ 不加
 * （restrained，避免无意义预留）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const componentsRoot = resolve(__dirname, '../components')

const GUTTER = '[scrollbar-gutter:stable]'

describe('FIX-296 可变内容滚动容器预留滚动条宽度', () => {
  it.each([
    ['ui/Dialog.tsx', 'min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]'],
    ['CommandPalette.tsx', 'max-h-[50dvh] min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]'],
    ['ArticleConversation.tsx', 'flex-1 overflow-y-auto [scrollbar-gutter:stable]'],
    ['RecentReads.tsx', 'min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]'],
  ])('%s 的可变内容滚动容器带 scrollbar-gutter stable', (file, needle) => {
    const src = readFileSync(resolve(componentsRoot, file), 'utf8')
    expect(src, file).toContain(needle)
  })

  it('静态内容浮层不加无意义预留（SettingsConflictDialog 保持原样）', () => {
    const src = readFileSync(resolve(componentsRoot, 'SettingsConflictDialog.tsx'), 'utf8')
    expect(src).not.toContain(GUTTER)
  })
})
