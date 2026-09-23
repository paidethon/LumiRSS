/** P16 导出到 Obsidian — 交接执行纯逻辑与诚实文案（lib/obsidian-handoff）。
 *
 * - 真实实现 + deps 注入：uri / file 双路径裁决、剪贴板备用、复制失败
 *   只读降级、未知变量如实标注；
 * - 诚实语义：URI 打开成功文案必须是「已打开 Obsidian（请在 Obsidian
 *   确认保存）」—— 所有 outcome 文案都不得出现「已写入」。 */

import {
  FILE_FALLBACK_MESSAGE,
  URI_OPENED_MESSAGE,
  runObsidianHandoff,
  type HandoffResultLike,
} from '../lib/obsidian-handoff'
import { describe, expect, it, vi } from 'vitest'

// ---- lib（真实实现） ----

describe('runObsidianHandoff（P16 lib）', () => {
  const base: HandoffResultLike = {
    mode: 'uri',
    uri: 'obsidian://new?vault=MyVault&file=x.md&content=hi',
    reason: null,
    filename: 'x.md',
    content: '# 文章',
    unknownVars: [],
    deviceLabel: '台式机',
  }

  it('uri 模式：打开链接 + 复制备用，文案为「已打开 Obsidian（请在 Obsidian 确认保存）」', async () => {
    const openUri = vi.fn(() => true)
    const copyText = vi.fn().mockResolvedValue(true)
    const outcome = await runObsidianHandoff(base, { openUri, copyText })
    expect(outcome.kind).toBe('uri-opened')
    expect(openUri).toHaveBeenCalledWith(base.uri)
    expect(copyText).toHaveBeenCalledWith('# 文章')
    expect(outcome.message).toBe(URI_OPENED_MESSAGE)
    expect(outcome.message).toContain('已打开 Obsidian（请在 Obsidian 确认保存）')
    expect(outcome.fallbackContent).toBeNull()
  })

  it('uri 模式打开失败：退化为仅剪贴板，文案如实说明', async () => {
    const outcome = await runObsidianHandoff(base, {
      openUri: () => false,
      copyText: vi.fn().mockResolvedValue(true),
    })
    expect(outcome.kind).toBe('clipboard-only')
    expect(outcome.message).toContain('无法自动打开 Obsidian')
    expect(outcome.message).toContain('内容已复制到剪贴板')
  })

  it('uri 模式复制失败：fallbackContent 携带全文（诚实降级，不假装已复制）', async () => {
    const outcome = await runObsidianHandoff(base, {
      openUri: () => true,
      copyText: vi.fn().mockResolvedValue(false),
    })
    expect(outcome.fallbackContent).toBe('# 文章')
  })

  it('file 模式（tooLong）：下载 .md + 剪贴板，文案如实说明走了哪条路', async () => {
    const download = vi.fn(() => true)
    const outcome = await runObsidianHandoff(
      { ...base, mode: 'file', uri: null, reason: 'tooLong' },
      { copyText: vi.fn().mockResolvedValue(true), download },
    )
    expect(download).toHaveBeenCalledWith('x.md', '# 文章', 'text/markdown')
    expect(outcome.kind).toBe('file-fallback')
    expect(outcome.message).toBe(FILE_FALLBACK_MESSAGE)
    expect(outcome.message).toContain('已下载 .md 文件并复制到剪贴板')
  })

  it('file 模式下载失败：诚实报错 + 内容降级展示', async () => {
    const outcome = await runObsidianHandoff(
      { ...base, mode: 'file', uri: null, reason: 'tooLong' },
      {
        copyText: vi.fn().mockResolvedValue(false),
        download: () => false,
      },
    )
    expect(outcome.kind).toBe('error')
    expect(outcome.message).toContain('下载失败')
    expect(outcome.fallbackContent).toBe('# 文章')
  })

  it('未知变量在文案中如实标注（不静默）', async () => {
    const outcome = await runObsidianHandoff(base, {
      openUri: () => true,
      copyText: vi.fn().mockResolvedValue(true),
    })
    const withUnknown = { ...base, unknownVars: ['oops'] }
    const outcome2 = await runObsidianHandoff(withUnknown, {
      openUri: () => true,
      copyText: vi.fn().mockResolvedValue(true),
    })
    expect(outcome2.message).toContain('{{oops}}')
    expect(outcome.message).not.toContain('{{oops}}')
  })

  it('诚实边界：任何 outcome 文案都不出现「已写入」', async () => {
    const cases: Array<[HandoffResultLike, Parameters<typeof runObsidianHandoff>[1]]> = [
      [base, { openUri: () => true, copyText: vi.fn().mockResolvedValue(true) }],
      [base, { openUri: () => false, copyText: vi.fn().mockResolvedValue(false) }],
      [
        { ...base, mode: 'file', uri: null, reason: 'tooLong' },
        { copyText: vi.fn().mockResolvedValue(true), download: () => true },
      ],
      [
        { ...base, mode: 'file', uri: null, reason: 'tooLong' },
        { copyText: vi.fn().mockResolvedValue(false), download: () => false },
      ],
    ]
    for (const [result, deps] of cases) {
      const outcome = await runObsidianHandoff(result, deps)
      expect(outcome.message).not.toContain('已写入')
    }
  })
})
