/** F068 双语对照导出 — 配对顺序、修订标记、缺段占位、特殊字符转义
 * （F012 同源 guardCell）、导出范围负向（不含未选内容）+ 组件接线。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildBilingualMarkdownExport,
  translationOf,
  type BilingualSegmentInput,
} from '../lib/reader-export'
import { BilingualExportSection } from '../components/BilingualExportSection'
import type { EntryDetail, TranslationSegmentState } from '../api/types'

const SEGMENTS: BilingualSegmentInput[] = [
  { index: 0, source: '第一段原文。', machineText: '第一段机翻。', userRevision: null },
  { index: 1, source: '第二段原文。', machineText: '第二段机翻。', userRevision: '第二段我改过。' },
  { index: 2, source: '=SUM(A1) 公式形似段落', machineText: '+cmd 形似译文', userRevision: null },
  { index: 3, source: '未翻译段原文。', machineText: null, userRevision: null },
]

describe('F068 buildBilingualMarkdownExport', () => {
  it('F068: 配对顺序正确；修订标记/机器标记/缺段占位；特殊字符转义', () => {
    const md = buildBilingualMarkdownExport(
      { title: '测试文章', source: '示例源', date: '2026-09-19', url: 'https://x/a', segments: SEGMENTS },
      { scope: 'all' },
    )
    // 配对顺序：原文段紧跟其后是对应译文段
    const order = ['第一段原文。', '第一段机翻。', '第二段我改过。', '未翻译段原文。'].map((t) =>
      md.indexOf(t),
    )
    expect(order.every((n) => n >= 0)).toBe(true)
    expect(order).toEqual([...order].sort((a, b) => a - b))
    // 修订标记：人工修订优先于机器
    expect(md).toContain('已人工修订')
    expect(md).toContain('机器翻译')
    // 缺段占位
    expect(md).toContain('未翻译')
    // F012 同源转义：公式形似段落前置撇号
    expect(md).toContain("'=SUM(A1) 公式形似段落")
    expect(md).toContain("'+cmd 形似译文")
    // translationOf 状态判定
    expect(translationOf(SEGMENTS[1] as BilingualSegmentInput)).toEqual({ text: '第二段我改过。', status: 'revised' })
    expect(translationOf(SEGMENTS[3] as BilingualSegmentInput)).toEqual({ text: null, status: 'missing' })
  })

  it('F068: visible 范围只含所选段落（负向：不含未选内容）+ 预览计数', () => {
    const md = buildBilingualMarkdownExport(
      { title: '测试文章', source: '示例源', date: '', url: null, segments: SEGMENTS },
      { scope: 'visible', visibleIndexes: [0, 2] },
    )
    expect(md).toContain('第一段原文。')
    expect(md).toContain('=SUM(A1)'.replace('=', "'="))
    // 负向：未选段落完全不出现
    expect(md).not.toContain('第二段我改过。')
    expect(md).not.toContain('未翻译段原文。')
    expect(md).toContain('共 2 段（当前可见）')
  })
})

// ---- 组件接线 ----

const DETAIL = {
  entryRef: 'e1.a',
  title: '测试文章',
  feedTitle: '示例源',
  publishedAt: '2026-09-19T00:00:00Z',
  url: 'https://x/a',
} as unknown as EntryDetail

const STATES: TranslationSegmentState[] = [
  { index: 0, status: 'success', translatedText: '第一段机翻。', cached: true, revisionStale: false, noTranslate: false, protectedTerms: [] },
  { index: 1, status: 'success', translatedText: '第二段机翻。', cached: true, userRevision: '第二段我改过。', revisedAt: '2026-09-19T01:00:00Z', revisionStale: false, noTranslate: false, protectedTerms: [] },
]

const BLOCKS = [
  { index: 0, text: '第一段原文。' },
  { index: 1, text: '第二段原文。' },
]

function renderSection(getVisibleIndexes: () => number[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <BilingualExportSection
        detail={DETAIL}
        segments={STATES}
        blocks={BLOCKS}
        getVisibleIndexes={getVisibleIndexes}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F068 导出对照稿组件', () => {
  it('F068: 范围选择→预览条数→下载 Markdown（blob 内容为双语对照稿）', async () => {
    renderSection(() => [1])
    fireEvent.click(screen.getByRole('button', { name: /导出对照稿/ }))
    // 预览条数：全文 2 段（与已加载块一致）
    expect(screen.getByText(/预览：2 段/)).toBeInTheDocument()
    // 切换可见范围 → 预览 1 段
    fireEvent.change(screen.getByLabelText('导出范围'), { target: { value: 'visible' } })
    expect(screen.getByText(/预览：1 段/)).toBeInTheDocument()

    let downloaded: Blob | null = null
    const createObjectURL = vi.fn((blob: Blob) => {
      downloaded = blob
      return 'blob:x'
    })
    const originalCreate = URL.createObjectURL
    URL.createObjectURL = createObjectURL as typeof URL.createObjectURL
    try {
      fireEvent.click(screen.getByRole('button', { name: '下载 Markdown' }))
    } finally {
      URL.createObjectURL = originalCreate
    }
    expect(createObjectURL).toHaveBeenCalled()
    const text = await (downloaded as unknown as Blob).text()
    expect(text).toContain('（双语对照稿）')
    expect(text).toContain('已人工修订')
    expect(text).not.toContain('未翻译段原文。')
  })
})
