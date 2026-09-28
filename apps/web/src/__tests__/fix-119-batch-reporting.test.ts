/** FIX-119 — 批量操作必须汇报成功/失败数量（BASELINE_OK 核验）。
 *
 * 现状核验（已有实现与既有套件，无修复需求）：
 * 1. 积压整理（F024 mark-all-read）：结果区汇报「已标记 N 条为已读，
 *    M 条失败」+ 失败清单 + 「重试失败项」（累计重试合并 applied）——
 *    backlog-panel.test.tsx 已断言部分失败文案与重试入口；
 * 2. N049 分批处理：每批执行完汇报「本批已标记 N 条为已读（M 条失败）；
 *    可整批撤销」——本文件补静态断言（渲染路径由 hooks+服务端 mock 驱动，
 *    已有 e2e 覆盖交互）；
 * 3. OPML 批量导入：结果卡汇报 新增/移动/跳过/失败 数量与失败清单——
 *    opml-import.test.tsx「结果卡按成功/跳过/失败汇报」已断言。
 *
 * 突变注入验证：把任一结果文案的失败计数去掉（只显示成功）→ 对应
 * 断言变红。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const BACKLOG_SRC = readFileSync(join(process.cwd(), 'src/components/BacklogPanel.tsx'), 'utf8')
const OPML_FLOW_SRC = readFileSync(join(process.cwd(), 'src/components/OpmlImportFlow.tsx'), 'utf8')
const OPML_DIALOG_SRC = readFileSync(join(process.cwd(), 'src/components/OpmlImportDialog.tsx'), 'utf8')

describe('FIX-119 批量操作结果汇报（BASELINE_OK）', () => {
  it('mark-all-read：成功计数 + 失败计数 + 失败清单 + 重试失败项', () => {
    expect(BACKLOG_SRC).toMatch(/已标记 \{result\.applied\} 条为已读/)
    expect(BACKLOG_SRC).toMatch(/\{result\.failed\.length\} 条失败/)
    expect(BACKLOG_SRC).toContain('重试失败项')
  })

  it('N049 分批：每批汇报已标记数量与失败数量（可整批撤销）', () => {
    expect(BACKLOG_SRC).toMatch(/本批已标记 \{result\.applied\} 条为已读/)
    expect(BACKLOG_SRC).toMatch(/result\.failed\.length > 0/)
    expect(BACKLOG_SRC).toContain('可整批撤销')
  })

  it('OPML 导入结果卡：新增/移动/跳过/失败 数量齐备', () => {
    // Flow 摘要卡（导入向导共用）
    expect(OPML_FLOW_SRC).toMatch(/result\.added\.length/)
    expect(OPML_FLOW_SRC).toMatch(/result\.skipped\.length/)
    expect(OPML_FLOW_SRC).toMatch(/result\.failed\.length/)
    // Dialog 树导入结果（含移动数）
    expect(OPML_DIALOG_SRC).toMatch(/result\.added\.length/)
    expect(OPML_DIALOG_SRC).toMatch(/result\.moved\.length/)
    expect(OPML_DIALOG_SRC).toMatch(/result\.skipped\.length/)
    expect(OPML_DIALOG_SRC).toMatch(/result\.failed\.length/)
  })
})
