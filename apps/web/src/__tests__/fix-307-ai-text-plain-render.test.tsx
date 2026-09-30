/**
 * FIX-307 — 流式/局部 Markdown 未闭合代码块不影响文章外布局
 * （BASELINE_OK 守卫）。
 *
 * 既有事实（无产品改动，逐条钉死）：
 * 1. 本产品没有「流式 Markdown 渲染器」：所有 AI 文本出口（文章对话、
 *    摘要、Agent 消息）都以纯文本节点渲染（textContent /
 *    whitespace-pre-wrap），永不进入 HTML/Markdown 解析路径——未闭合
 *    的 ``` 围栏只是普通字符，不可能生成 <pre>/<code> 结构、更不可能
 *    把后续内容吞进代码块撑破文章外布局；
 * 2. 全仓唯一的 Markdown→HTML 渲染器是 lib/md-preview（用户自己笔记的
 *    预览，非流式、非 AI 输出）：它没有围栏状态机——未闭合围栏行只会
 *    成为已转义的普通段落文本，输出仍过 DOMPurify 最终边界；
 * 3. 静态边界：AI 输出面组件不持有 dangerouslySetInnerHTML，
 *    mdPreviewHtml 只被笔记预览（NotesManager）引用。
 *
 * 未来若引入真正的流式 Markdown 渲染：必须在局部容器内渲染未完成
 * 结构并在最终结果上重新安全解析——届时本套件需随之演进为行为断言。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ArticleConversation from '../components/ArticleConversation'
import { mdPreviewHtml } from '../lib/md-preview'

const read = (rel: string): string =>
  readFileSync(resolve(__dirname, '..', rel), 'utf-8')

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const UNCLOSED_FENCE_REPLY =
  '答案开头\n```ts\nconst x = 1\n// 围栏未闭合，后续全部是"代码块"形态文本'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-307: AI 文本纯文本渲染，未闭合围栏不产生结构', () => {
  it('对话助手消息含未闭合代码围栏：渲染为气泡内文本，无 pre/code 结构', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/entries/e1.a/conversation') {
          return Promise.resolve(
            jsonResponse({
              status: 'active',
              messages: [
                {
                  id: 1,
                  role: 'assistant',
                  content: UNCLOSED_FENCE_REPLY,
                  createdAt: '2026-10-01T00:00:00+00:00',
                },
              ],
            }),
          )
        }
        throw new Error(`unexpected fetch: ${url}`)
      }),
    )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <ArticleConversation entryRef="e1.a" articleTitle="标题" open onClose={() => {}} />
      </QueryClientProvider>,
    )
    await waitFor(() => {
      expect(screen.getByText(/答案开头/)).toBeInTheDocument()
    })
    // 围栏文本原样可见（是字符，不是结构）。
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument()
    // 没有任何 Markdown 结构被生成；文档里没有 <pre>/<code>。
    expect(document.querySelector('pre')).toBeNull()
    expect(document.querySelector('code')).toBeNull()
    // 助手消息所在文本节点完整包含未闭合围栏（未吞并兄弟内容）。
    const bubbleText = screen.getByText(/答案开头/).textContent ?? ''
    expect(bubbleText).toContain('```ts')
  })

  it('唯一的 Markdown 渲染器（笔记预览）：未闭合围栏只是转义文本，无 pre 吞并', () => {
    const html = mdPreviewHtml(
      '## 笔记\n```js\nalert("<script>window.broken=true</script>")\n后续正文也被围栏吞掉了吗',
    )
    // 无围栏结构：``` 行只是普通转义段落。
    expect(html).not.toContain('<pre')
    expect(html).not.toContain('<code')
    // 围栏行原样可见（已转义）。
    expect(html).toContain('```js')
    // 注入形态在「先转义」一步失去语法，DOMPurify 兜底。
    expect(html).not.toContain('<script')
    expect(html).toContain('&lt;script&gt;')
  })

  it('静态边界：AI 输出面不持 dangerouslySetInnerHTML；mdPreview 只进笔记预览', () => {
    for (const file of [
      'components/ArticleConversation.tsx',
      'components/ReaderSummary.tsx',
      'components/pages/AgentWorkbenchPage.tsx',
    ]) {
      expect(read(file), file).not.toContain('dangerouslySetInnerHTML')
    }
    // 全仓（components/lib，排除测试）引用 mdPreviewHtml 的只有 NotesManager。
    const { readdirSync, statSync } = require('node:fs') as typeof import('node:fs')
    const { join } = require('node:path') as typeof import('node:path')
    const hits: string[] = []
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir)) {
        const full = join(dir, entry)
        if (statSync(full).isDirectory()) {
          if (entry === '__tests__') continue
          walk(full)
        } else if (/\.tsx?$/.test(entry)) {
          const text = readFileSync(full, 'utf-8')
          if (text.includes('mdPreviewHtml')) hits.push(full)
        }
      }
    }
    walk(resolve(__dirname, '..', 'components'))
    walk(resolve(__dirname, '..', 'lib'))
    // md-preview.ts 是定义处自身，排除后唯一消费者是笔记预览。
    const consumers = hooks_to_basenames(hits).filter((n) => n !== 'md-preview.ts')
    expect(consumers).toEqual(['NotesManager.tsx'])
  })
})

function hooks_to_basenames(paths: string[]): string[] {
  return paths.map((p) => p.split('/').pop() ?? p).sort()
}
